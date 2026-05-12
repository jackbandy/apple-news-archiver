'''
verify_backfill_links.py

Parses backfill-log.txt to find (headline, link) pairs that were written to
stories.csv by the desktop backfill script. For each link, opens it in the
iOS simulator via Apple News and checks that the displayed article title
matches the original headline. Removes the link from stories.csv if it does
not match (i.e., it was a channel or wrong-article link).

Usage:
    .venv/bin/python verify_backfill_links.py            # dry-run
    .venv/bin/python verify_backfill_links.py --confirm  # write changes
    .venv/bin/python verify_backfill_links.py --limit N  # process only N links
'''

import os
import re
import csv
import sys
import time
import shutil
import random
import argparse
import difflib
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from appium.webdriver.common.appiumby import AppiumBy

from util.appium_session import start_driver
from util.setup import wda_needs_rebuild, clear_wda_derived_data

from config import (
    device_name_and_os, device_os, udid,
    output_file, APP_PATH,
)

BACKUP_PATH = output_file + '.verify_bak'
LOG_PATH = 'backfill-log.txt'

# Minimum similarity between log headline and displayed article title to keep
# the link. Below this threshold the link is considered wrong and removed.
MATCH_THRESHOLD = 0.45

# How long to wait after opening a link before reading the title
ARTICLE_LOAD_SECS = 5.0

# How many title candidates to inspect
MAX_TITLE_CANDIDATES = 10

# If any of these substrings appears in any visible text element, the link
# opened a real Apple News+ article that requires a subscription — treat as OK.
PAYWALL_MARKERS = {
    'Your trial also includes',
    'unlock 500+ publications',
    'Enjoy stories from 500+',
    'Unlock this story',
    'One month free',
}

# If this substring appears, the link opened a publication/channel page rather
# than an article — treat as a bad link and remove it.
CHANNEL_MARKER = '500+ premium publications'

# Apple News UI section headers / chrome strings that are never article titles.
UI_CHROME = {
    'people also read',
    'news+ recommended reads',
    'recommended reads',
    'top stories',
    'trending stories',
    'editor\'s picks',
    'more from',
    'related articles',
    'keep reading',
}

# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s']", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def parse_log(log_path):
    '''
    Parse backfill-log.txt and return a list of (headline, link) pairs for
    every entry where a link was successfully found.

    Log format (relevant lines):
        [N/987] 'some headline text'
          ...
          -> https://apple.news/Xxx (N rows)
    '''
    pairs = []
    current_headline = None

    headline_re = re.compile(r"^\[(\d+)/\d+\]\s+'(.+)'$")
    link_re = re.compile(r"->\s+(https://apple\.news/\S+)\s+\(\d+ rows?\)")

    with open(log_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n').rstrip()
            # Strip ANSI escape sequences that showed up in the log
            line = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line)
            line = re.sub(r'\^\[\[.', '', line)

            m = headline_re.match(line.strip())
            if m:
                current_headline = m.group(2).strip()
                continue

            m = link_re.search(line)
            if m and current_headline:
                link = m.group(1).strip()
                pairs.append((current_headline, link))
                # Don't reset current_headline; a headline can appear once.

    return pairs


def tap(driver, x, y):
    driver.execute_script('mobile: tap', {'x': x, 'y': y})


# ---------------------------------------------------------------------------
# Article title extraction
# ---------------------------------------------------------------------------

def open_link_in_news(driver, link):
    '''Open an apple.news link using a deep link.'''
    try:
        driver.execute_script('mobile: deepLink', {
            'url': link,
            'bundleId': 'com.apple.news',
        })
    except Exception as e:
        print('  deepLink failed: {}'.format(e))
        # Fallback: use simctl
        subprocess.run(
            ['xcrun', 'simctl', 'openurl', udid, link],
            capture_output=True,
        )


def get_screen_texts(driver):
    '''
    Return all visible text strings from the current screen.
    Queries both XCUIElementTypeStaticText and XCUIElementTypeOther (which
    often carries the accessible label of article headline containers).
    Deduplicates by text content.
    '''
    seen = set()
    texts = []

    element_types = [
        AppiumBy.CLASS_NAME, 'XCUIElementTypeStaticText',
        AppiumBy.CLASS_NAME, 'XCUIElementTypeOther',
    ]

    for cls in ('XCUIElementTypeStaticText', 'XCUIElementTypeOther'):
        try:
            elements = driver.find_elements(AppiumBy.CLASS_NAME, cls)
            for el in elements:
                try:
                    name = (el.get_attribute('name') or '').strip()
                    value = (el.get_attribute('value') or '').strip()
                    text = name if len(name) >= len(value) else value
                    if text and text not in seen:
                        seen.add(text)
                        y = el.location.get('y', 9999)
                        texts.append((y, text))
                except Exception:
                    continue
        except Exception as e:
            print('  get_screen_texts error ({}): {}'.format(cls, e))

    return texts


def is_paywall_screen(texts):
    '''Return True if any visible text contains an Apple News+ paywall marker.'''
    for _y, text in texts:
        if any(marker in text for marker in PAYWALL_MARKERS):
            return True
    return False


def is_channel_screen(texts):
    '''Return True if any visible text contains the publication/channel page marker.'''
    for _y, text in texts:
        if CHANNEL_MARKER in text:
            return True
    return False


def get_article_title(texts):
    '''
    Extract the most likely article title from screen texts.
    Returns the best candidate string, or '' if nothing useful found.

    Filters out known Apple News UI chrome strings, then returns the longest
    text in the topmost band of the screen.
    '''
    candidates = [
        (y, t) for y, t in texts
        if len(t) >= 15 and normalize(t) not in UI_CHROME
    ]

    if not candidates:
        return ''

    candidates.sort(key=lambda t: t[0])

    # Among the topmost candidates, return the longest (most likely full title)
    top_band = [c for c in candidates[:MAX_TITLE_CANDIDATES]
                if c[0] <= candidates[0][0] + 200]
    if top_band:
        return max(top_band, key=lambda t: len(t[1]))[1]

    return candidates[0][1]


def best_matching_text(headline, texts):
    '''
    Among all screen texts, return (sim, text) for the one most similar to
    the headline. Used as a fallback when positional title extraction fails.
    '''
    best_sim = 0.0
    best_text = ''
    for _y, text in texts:
        if normalize(text) in UI_CHROME:
            continue
        sim = similarity(headline, text)
        if sim > best_sim:
            best_sim = sim
            best_text = text
    return best_sim, best_text


def navigate_to_news_home(driver):
    '''Navigate back to Apple News home to reset state between links.'''
    # Tap the "Today" or "News+" tab to go home
    for tab_name in ('Today', 'News+', 'Top Stories'):
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, tab_name)
            tap(driver, el.location['x'] + el.size['width'] // 2,
                el.location['y'] + el.size['height'] // 2)
            time.sleep(1.0)
            return
        except Exception:
            continue

    # Fallback: back swipe to close article
    try:
        window_h = driver.get_window_size()['height']
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(
            driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
        actions.w3c_actions.pointer_action.move_to_location(5, window_h // 2)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.move_to_location(200, window_h // 2)
        actions.w3c_actions.pointer_action.release()
        actions.perform()
        time.sleep(0.8)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Verify backfilled Apple News links match their headlines')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually remove bad links (default is dry-run)')
    parser.add_argument('--threshold', type=float, default=MATCH_THRESHOLD,
                        help='Min similarity to keep a link (default: {})'.format(
                            MATCH_THRESHOLD))
    parser.add_argument('--limit', type=int, default=0,
                        help='Max unique links to verify (0 = all)')
    parser.add_argument('--log', default=LOG_PATH,
                        help='Path to backfill log (default: {})'.format(LOG_PATH))
    args = parser.parse_args()

    # --- Parse log ---
    print('Parsing log: {}'.format(args.log))
    pairs = parse_log(args.log)
    print('Log entries with links: {}'.format(len(pairs)))

    if not pairs:
        print('No (headline, link) pairs found in log. Nothing to do.')
        return

    # Deduplicate: for each unique link collect all headlines that map to it
    # (the same link might appear multiple times if found for different rows)
    link_to_headlines = {}
    for headline, link in pairs:
        link_to_headlines.setdefault(link, set()).add(headline)

    unique_links = list(link_to_headlines.items())  # [(link, {headlines})]
    random.shuffle(unique_links)
    print('Unique links to verify: {}'.format(len(unique_links)))

    if args.limit > 0:
        unique_links = unique_links[:args.limit]
        print('Limiting to {} links'.format(len(unique_links)))

    # --- Load CSV ---
    with open(output_file, newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # Build index: link -> [row indices] for rows that currently have that link
    link_to_row_indices = {}
    for i, row in enumerate(rows):
        lnk = (row.get('link') or '').strip()
        if lnk:
            link_to_row_indices.setdefault(lnk, []).append(i)

    print('Mode: {}'.format('WRITE' if args.confirm else 'DRY-RUN'))
    print()

    # --- Connect to Appium ---
    print('Connecting to Appium...')
    rebuild = wda_needs_rebuild(udid)
    if rebuild:
        print('WDA DerivedData stale/missing — clearing for rebuild')
        clear_wda_derived_data()

    try:
        driver = start_driver(
            app_path=APP_PATH,
            device_name=device_name_and_os,
            udid=udid,
            platform_version=device_os,
            rebuild_wda=rebuild,
            clear_wda_derived_data_fn=clear_wda_derived_data,
        )
    except Exception as e:
        print('Error connecting to Appium: {}'.format(e))
        sys.exit(1)

    time.sleep(5)  # wait for app to load

    # --- Verify each link ---
    bad_links = []   # links to clear
    processed = 0

    try:
        for link, headlines in unique_links:
            processed += 1
            # Use the longest headline as the canonical search target
            headline = max(headlines, key=len)
            row_indices = link_to_row_indices.get(link, [])

            publication = ''
            if row_indices:
                publication = (rows[row_indices[0]].get('publication') or '').strip()

            print('[{}/{}] {}'.format(processed, len(unique_links), link))
            print('  Headline: {!r}'.format(headline[:80]))
            if publication:
                print('  Source:   {!r}'.format(publication))
            print('  Affects {} row(s) in CSV'.format(len(row_indices)))

            open_link_in_news(driver, link)
            time.sleep(ARTICLE_LOAD_SECS)

            texts = get_screen_texts(driver)

            # Check all visible elements — if any matches the headline well
            # enough, the link is correct regardless of other signals.
            best_sim, best_text = best_matching_text(headline, texts)

            print('  Best match: {!r} (sim={:.2f})'.format(
                best_text[:80] if best_text else '(nothing)', best_sim))

            if best_sim >= args.threshold:
                print('  -> OK (headline found on screen)')
            elif is_paywall_screen(texts):
                print('  -> OK (paywall/plus article)')
            elif is_channel_screen(texts):
                print('  -> channel link — will remove')
                bad_links.append(link)
            elif best_sim == 0.0 and not texts:
                print('  -> BAD (no elements loaded) — will remove link')
                bad_links.append(link)
            else:
                print('  -> BAD (sim {:.2f} < {:.2f}) — will remove link'.format(
                    best_sim, args.threshold))
                bad_links.append(link)

            navigate_to_news_home(driver)
            time.sleep(1.0)

    except KeyboardInterrupt:
        print('\nInterrupted.')
    except Exception as e:
        print('Unexpected error: {}'.format(e))
    finally:
        try:
            driver.terminate_app('com.apple.news')
        except Exception:
            pass
        driver.quit()

    print('\nVerified {}/{} links'.format(processed, len(unique_links)))
    print('Bad links found: {}'.format(len(bad_links)))

    if not bad_links:
        print('All links look good. Nothing to remove.')
        return

    # Count affected rows
    affected_rows = sum(len(link_to_row_indices.get(lnk, [])) for lnk in bad_links)
    print('Would clear {} row(s) in CSV.'.format(affected_rows))

    if not args.confirm:
        print('\nDry-run complete. Re-run with --confirm to apply changes.')
        print('Bad links:')
        for lnk in bad_links:
            print('  {}'.format(lnk))
        return

    # --- Write back ---
    print('Backing up {} -> {}'.format(output_file, BACKUP_PATH))
    shutil.copy2(output_file, BACKUP_PATH)

    cleared = 0
    bad_set = set(bad_links)
    for i, row in enumerate(rows):
        if (row.get('link') or '').strip() in bad_set:
            rows[i]['link'] = ''
            cleared += 1

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print('Done. Cleared {} row(s).'.format(cleared))


if __name__ == '__main__':
    main()
