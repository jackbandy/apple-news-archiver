'''
backfill_links.py

For each row in stories.csv where link is empty, searches Apple News via the
iOS simulator (Appium) to find and fill in the apple.news link.

Usage:
    .venv/bin/python backfill_links.py            # dry-run: shows what would change
    .venv/bin/python backfill_links.py --confirm  # actually writes updates

Safety:
  - Default mode is dry-run; use --confirm to write changes
  - Creates a .bak backup before any write
  - Never overwrites a row that already has a link
  - Skips headlines that are empty, too short, or generic ("Apple News Plus")
  - Requires headline similarity >= MATCH_THRESHOLD to accept a result
'''

import os
import re
import csv
import sys
import time
import shutil
import argparse
import difflib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

from util.appium_session import start_driver
from util.setup import wda_needs_rebuild, clear_wda_derived_data

from config import (
    device_name_and_os, device_os, udid,
    output_file, APP_PATH,
    TAB_BAR_HEIGHT, SAFE_TAP_MARGIN, MIN_STORY_CELL_HEIGHT,
)

BACKUP_PATH = output_file + '.bak'
MATCH_THRESHOLD = 0.55    # minimum similarity ratio to accept a search result
MAX_RESULTS_TO_CHECK = 5  # how many search result cells to try per query
SEARCH_WAIT_SECS = 3.0    # wait after typing before reading results
BETWEEN_SEARCH_SECS = 1.5 # pause between consecutive searches

# Headlines that are generic/uninformative and cannot be matched reliably
SKIP_HEADLINES = {
    '', 'apple news plus', 'apple news today',
}


# ---------------------------------------------------------------------------
# Headline helpers
# ---------------------------------------------------------------------------

def normalize(text):
    '''Lowercase, strip punctuation, collapse whitespace.'''
    text = text.lower()
    text = re.sub(r"[^\w\s']", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def best_headline(row):
    '''Return the most informative headline for this row.'''
    h = (row.get('article_headline') or '').strip()
    if h and len(h) > 10:
        return h
    return (row.get('headline') or '').strip()


# ---------------------------------------------------------------------------
# Appium touch helpers (mirrors get_stories.py)
# ---------------------------------------------------------------------------

def tap(driver, x, y):
    driver.execute_script('mobile: tap', {'x': x, 'y': y})


def long_press(driver, x, y, duration=1.5):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(
        driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
    actions.w3c_actions.pointer_action.move_to_location(x, y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(duration)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


def back_swipe(driver, window_height):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(
        driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
    actions.w3c_actions.pointer_action.move_to_location(5, window_height // 2)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.move_to_location(200, window_height // 2)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


# ---------------------------------------------------------------------------
# Apple News search helpers
# ---------------------------------------------------------------------------

def navigate_to_search_tab(driver):
    '''Tap the Search tab in the Apple News tab bar.'''
    for attempt in range(3):
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Search')
            tap(driver, el.location['x'] + el.size['width'] // 2,
                el.location['y'] + el.size['height'] // 2)
            time.sleep(1.5)
            return True
        except Exception:
            time.sleep(1)
    return False


def type_search_query(driver, query):
    '''Find the search field, clear it, and type the query.'''
    field = None
    for attempt in range(5):
        try:
            field = driver.find_element(AppiumBy.CLASS_NAME, 'XCUIElementTypeSearchField')
            break
        except Exception:
            time.sleep(0.8)

    if field is None:
        return False

    try:
        field.clear()
    except Exception:
        pass
    field.send_keys(query)
    time.sleep(SEARCH_WAIT_SECS)
    return True


def clear_search(driver):
    '''Clear the search field to return to the blank search screen.'''
    try:
        field = driver.find_element(AppiumBy.CLASS_NAME, 'XCUIElementTypeSearchField')
        field.clear()
        time.sleep(0.5)
    except Exception:
        pass


def get_search_result_cells(driver, window_height):
    '''Return visible result cells (snapshotted) sorted by y position.'''
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN
    cells = driver.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeCell')
    visible = sorted(
        [c for c in cells
         if c.size['height'] >= MIN_STORY_CELL_HEIGHT
         and c.location['y'] >= 60
         and c.location['y'] < safe_y],
        key=lambda c: c.location['y']
    )
    snapshots = []
    for cell in visible:
        label = ''
        try:
            for el in cell.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeOther'):
                name = el.get_attribute('name') or ''
                if len(name) > 5:
                    label = name
                    break
        except Exception:
            pass
        snapshots.append({
            'x': cell.location['x'], 'y': cell.location['y'],
            'w': cell.size['width'],  'h': cell.size['height'],
            'label': label,
        })
    return snapshots


def long_press_copy_link(driver, x, y):
    '''Long-press at (x,y), tap Copy Link, return clipboard text or None.'''
    long_press(driver, x, y, duration=1.5)
    time.sleep(0.2)
    try:
        copy_el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Copy Link')
        cx = copy_el.location['x'] + copy_el.size['width'] // 2
        cy = copy_el.location['y'] + copy_el.size['height'] // 2
        tap(driver, cx, cy)
        time.sleep(0.5)
        return driver.get_clipboard_text()
    except Exception:
        # Dismiss any open context menu
        tap(driver, 200, 30)
        time.sleep(1.0)
        return None


def find_link_for_headline(driver, query_headline, window_height):
    '''
    Search for query_headline in Apple News, try to copy a link from the
    best-matching result. Returns (link, matched_label) or (None, None).
    '''
    window_width = driver.get_window_size()['width']

    if not type_search_query(driver, query_headline):
        print('  Could not find search field')
        return None, None

    cells = get_search_result_cells(driver, window_height)
    if not cells:
        print('  No search results returned')
        clear_search(driver)
        return None, None

    # Score cells by similarity to the query headline
    scored = []
    for s in cells[:MAX_RESULTS_TO_CHECK]:
        if not s['label']:
            continue
        sim = similarity(query_headline, s['label'])
        scored.append((sim, s))
    scored.sort(key=lambda t: t[0], reverse=True)

    best_sim, best_cell = scored[0] if scored else (0, None)
    print('  Best match (sim={:.2f}): {}'.format(best_sim, (best_cell or {}).get('label', '')[:80]))

    if best_sim < MATCH_THRESHOLD or best_cell is None:
        print('  Similarity below threshold, skipping')
        clear_search(driver)
        return None, None

    x_c = max(80, min(best_cell['x'] + best_cell['w'] // 2, window_width - 80))
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN
    y_c = max(100, min(best_cell['y'] + best_cell['h'] // 2, safe_y - 20))

    raw = long_press_copy_link(driver, x_c, y_c)
    if not raw:
        clear_search(driver)
        return None, None

    idx = raw.find('https://apple.news')
    if idx < 0:
        print('  Clipboard did not contain apple.news URL: {!r}'.format(raw[:80]))
        clear_search(driver)
        return None, None

    link = raw[idx:].split()[0]  # strip any trailing text
    clear_search(driver)
    return link, best_cell['label']


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Backfill missing Apple News links in stories.csv')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually write changes (default is dry-run)')
    parser.add_argument('--threshold', type=float, default=MATCH_THRESHOLD,
                        help='Minimum similarity to accept a search result (default: {})'.format(MATCH_THRESHOLD))
    parser.add_argument('--limit', type=int, default=0,
                        help='Max unique headlines to process (0 = all)')
    args = parser.parse_args()

    match_threshold = args.threshold

    # --- Load CSV ---
    with open(output_file, newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # --- Find rows needing backfill ---
    rows_needing_link = [r for r in rows if not r.get('link', '').strip()]
    print('Rows missing a link: {}/{}'.format(len(rows_needing_link), len(rows)))

    # Deduplicate by best headline; skip uninformative ones
    seen_queries = {}  # normalized_headline -> (original_headline, [row_indices])
    for i, row in enumerate(rows):
        if row.get('link', '').strip():
            continue
        h = best_headline(row)
        if not h or normalize(h) in SKIP_HEADLINES or len(h) < 15:
            continue
        key = normalize(h)
        if key not in seen_queries:
            seen_queries[key] = (h, [])
        seen_queries[key][1].append(i)

    queries = list(seen_queries.items())  # [(norm_key, (headline, [indices]))]
    print('Unique searchable headlines: {}'.format(len(queries)))

    if args.limit > 0:
        queries = queries[:args.limit]
        print('Limiting to {} queries'.format(len(queries)))

    if not queries:
        print('Nothing to do.')
        return

    if args.confirm:
        print('\nMode: WRITE (--confirm passed)')
    else:
        print('\nMode: DRY-RUN (pass --confirm to write changes)')

    print()

    # --- Start Appium ---
    print('Connecting to Appium...')
    rebuild = wda_needs_rebuild(udid)
    if rebuild:
        print('WDA DerivedData is stale or missing — clearing for rebuild')
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

    time.sleep(6)  # wait for app to load

    window_size = driver.get_window_size()
    window_height = window_size['height']

    if not navigate_to_search_tab(driver):
        print('WARNING: Could not tap Search tab — results may be unreliable')

    # --- Search for each unique headline ---
    found_links = {}   # norm_key -> link
    processed = 0
    succeeded = 0

    try:
        for norm_key, (headline, row_indices) in queries:
            processed += 1
            print('[{}/{}] Searching: {!r}'.format(processed, len(queries), headline[:70]))

            link, matched_label = find_link_for_headline(driver, headline, window_height)

            if link:
                found_links[norm_key] = link
                succeeded += 1
                print('  -> {} (would update {} row(s))'.format(link, len(row_indices)))
            else:
                print('  -> no link found')

            time.sleep(BETWEEN_SEARCH_SECS)

    except KeyboardInterrupt:
        print('\nInterrupted.')
    except Exception as e:
        print('Unexpected error: {}'.format(e))

    try:
        driver.terminate_app('com.apple.news')
    except Exception:
        pass
    driver.quit()

    print('\nResults: {}/{} headlines resolved'.format(succeeded, processed))

    if not found_links:
        print('No links found — nothing to write.')
        return

    # Count how many rows would be updated
    update_count = sum(len(seen_queries[k][1]) for k in found_links)
    print('Would update {} rows.'.format(update_count))

    if not args.confirm:
        print('\nDry-run complete. Re-run with --confirm to apply.')
        return

    # --- Write back ---
    print('Backing up {} -> {}'.format(output_file, BACKUP_PATH))
    shutil.copy2(output_file, BACKUP_PATH)

    updated = 0
    for norm_key, link in found_links.items():
        _, row_indices = seen_queries[norm_key]
        for i in row_indices:
            if rows[i].get('link', '').strip():
                continue  # double-check: never overwrite
            rows[i]['link'] = link
            updated += 1

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print('Done. Updated {} rows.'.format(updated))


if __name__ == '__main__':
    main()
