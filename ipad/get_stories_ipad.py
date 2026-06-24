'''
get_stories_ipad.py

Collects Apple News stories from the iPad Today feed (landscape, 3-column).
Sections: Top Stories (always first) plus optional Trending Stories, Reader
Favorites, and a Featured Recipe — handled in whatever order they appear.

Links are copied via each card's "..." (ellipsis) button -> Copy Link. One
rotated screenshot is saved per scroll pass. Stories are appended to
data_output_ipad/stories.csv with a per-run JSON file alongside.

See ipad/IPAD-PLAN.md for the full layout reference.
'''
__author__ = "Jack Bandy"

import os
import re
import sys
import signal
import datetime
import subprocess
from time import sleep
from collections import deque
from glob import glob

from appium.webdriver.common.appiumby import AppiumBy

# Make the repo root (for util/) and this folder (for ipad_device_loader) importable
# regardless of the caller's working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from util.gestures import tap, swipe, long_press
from util.io import save_stories as _save_stories, save_json as _save_json
from util.parsing import parse_cell_label, parse_pub_date
from util.setup import (
    wda_needs_reinstall, clear_wda_derived_data, wipe_app_data_folder,
    wait_for_wda_teardown, relaunch_simulator,
)
from util.appium_session import start_driver

from ipad_device_loader import (
    device_name_and_os, device_os, udid,
    output_folder, output_file, APP_PATH,
    MIN_STORY_CELL_HEIGHT, CONTENT_X_MIN, MAX_PASSES,
    MAX_RUN_SECONDS, HEADLESS_SIMULATOR,
)


# Section headers, located by ACCESSIBILITY_ID. Top Stories is always first;
# the other two are optional and may appear in any order below it. Featured
# Recipe lives in a nested CollectionView and is handled separately.
SECTION_HEADERS = {
    'Top Stories':      'top',
    'Trending Stories': 'trending',
    'Reader Favorites': 'reader_favorites',
}

# When either of these sub-headers becomes visible, Top Stories is exhausted.
TOP_STOP_HEADERS = (
    'Selected by the Apple News editors',
    'More Apple News Top Stories',
)


def swipe_up(driver, win_h):
    '''Advance ~1/3 of the screen. Smaller increments keep cells in view long
    enough to capture links without skipping over content.'''
    step = win_h // 5
    start_y = int(win_h * 0.75)
    swipe(driver, 800, start_y, 800, start_y - step, duration=0.15)


def swipe_partial(driver, win_h):
    '''Scroll ~1/3 of the screen to reveal more top stories without jumping to
    the next section.'''
    swipe(driver, 800, 750, 800, 750 - win_h // 3, duration=0.1)


def _get_snaps(driver, win_h):
    '''Collect and return all visible content-area cells as dicts.'''
    snaps = []
    for c in driver.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeCell'):
        try:
            x, y = c.location['x'], c.location['y']
            w, h = c.size['width'], c.size['height']
        except Exception:
            continue
        if x < CONTENT_X_MIN or h < MIN_STORY_CELL_HEIGHT or y < 60 or y > win_h:
            continue
        label = ''
        try:
            for el in c.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeOther'):
                nm = el.get_attribute('name') or ''
                if len(nm) > 20 and ',' in nm:
                    label = nm
                    break
        except Exception:
            pass
        snaps.append({'x': x, 'y': y, 'w': w, 'h': h, 'label': label})
    return snaps


def _sort_snaps(snaps, boundaries):
    '''Sort snaps with section-awareness: trending uses column-major (x, y) so
    the left column gets ranks 1-3 and right column gets 4-6; all other
    sections use row-major (y, x).'''
    _SEC_ORDER = {'top': 0, 'trending': 1, 'reader_favorites': 2}
    for s in snaps:
        sec = 'top'
        for h_y, h_sec in boundaries:
            if h_y <= s['y']:
                sec = h_sec
            else:
                break
        s['_sec'] = sec
    snaps.sort(key=lambda s: (
        _SEC_ORDER.get(s['_sec'], 9),
        s['x'] if s['_sec'] == 'trending' else s['y'],
        s['y'] if s['_sec'] == 'trending' else s['x'],
    ))
    return snaps


def dismiss_cannot_connect(driver):
    '''Dismiss a "Cannot Connect" overlay if present.'''
    for label in ('OK', 'Try Again', 'Retry'):
        try:
            btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, label)
            tap(driver, btn.location['x'] + btn.size['width'] // 2,
                        btn.location['y'] + btn.size['height'] // 2)
            sleep(1)
            return True
        except Exception:
            pass
    return False


def copy_link_via_ellipsis(driver, x, y, w, h):
    '''Tap a card's bottom-right "..." button, then Copy Link. Returns the
    apple.news URL, or '' if no link is offered (e.g. News+ stories).'''
    tap(driver, x + w - 20, y + h - 20)
    sleep(0.6)
    try:
        btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Copy Link')
        tap(driver, btn.location['x'] + btn.size['width'] // 2,
                    btn.location['y'] + btn.size['height'] // 2)
        sleep(0.5)
        raw = driver.get_clipboard_text() or ''
        idx = raw.find('https://apple.news')
        return raw[idx:] if idx >= 0 else ''
    except Exception:
        # Dismiss floating menu; if we drilled into a story, navigate back.
        tap(driver, 200, 30)
        sleep(0.5)
        try:
            back_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'BackButton')
            tap(driver, back_btn.location['x'] + back_btn.size['width'] // 2,
                        back_btn.location['y'] + back_btn.size['height'] // 2)
            sleep(1.5)
        except Exception:
            pass
        return ''


def save_screenshot(driver, label, screenshots_dir):
    ts = datetime.datetime.now().strftime('%Y-%m-%d at %H.%M.%S')
    path = os.path.join(screenshots_dir, 'apple-news-{}-{}.png'.format(label, ts))
    driver.get_screenshot_as_file(path)


def parse_story(section, label):
    '''Parse a cell label into (publication, author, headline) for its section.'''
    publication = author = headline = ''
    if section == 'trending':
        # "Headline, time ago[, Author]" — no publication prefix.
        m = re.search(r',\s*\d+\s+(?:minute|hour|day|week|month)s?\s+ago', label)
        if m:
            headline = label[:m.start()].strip()
            author = label[m.end():].lstrip(', ').strip()
        else:
            headline = label.strip()
        headline = re.sub(r',\s*Apple News Plus\s*$', '', headline).strip()
    elif section == 'reader_favorites':
        # "Apple News Plus, Publication, Headline[, Author]" — no time field.
        parts = label.split(', ', 2)
        publication = parts[1] if len(parts) > 2 else ''
        headline = parts[2] if len(parts) > 2 else label.strip()
    else:  # top
        publication, headline, author = parse_cell_label(label)
    return publication, author, headline


def collect_recipe(driver):
    '''If the Featured Recipe header is visible, long-press the recipe card to
    copy its link. Returns ([(title, description, link)], header_found).'''
    rows = []
    try:
        driver.find_element(AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[contains(@value, "Featured Recipe")]')
    except Exception:
        return rows, False
    els = driver.find_elements(AppiumBy.XPATH,
        '//XCUIElementTypeOther[contains(@name, "RECIPE")]')
    for el in els:
        name = (el.get_attribute('name') or '').strip()
        # The featured card's name ends in ", RECIPE"; carousel items carry
        # extra trailing fields (publication, minutes, News+) and are skipped.
        if not name.endswith('RECIPE'):
            continue
        title = re.sub(r',\s*RECIPE\s*$', '', name).strip()
        description = el.get_attribute('value') or ''
        cx = el.location['x'] + el.size['width'] // 2
        cy = el.location['y'] + el.size['height'] // 2
        long_press(driver, cx, cy, duration=1.5)
        sleep(0.5)
        link = ''
        try:
            btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Copy Link')
            tap(driver, btn.location['x'] + btn.size['width'] // 2,
                        btn.location['y'] + btn.size['height'] // 2)
            sleep(0.5)
            raw = driver.get_clipboard_text() or ''
            idx = raw.find('https://apple.news')
            link = raw[idx:] if idx >= 0 else ''
        except Exception:
            tap(driver, 200, 30)
            sleep(0.5)
        rows.append((title, description, link))
    return rows, True


def collect_feed(driver, run_time, screenshots_dir):
    '''Scroll the feed, scanning content cells each pass. Sections are bounded
    by header y-positions (XCUITest reports scrolled-past headers with negative
    y, so they keep bounding the sections below them). Stop once no new stories
    appear for several passes or MAX_PASSES is reached.'''
    window = driver.get_window_size()
    win_h = window['height']

    stories = []
    seen_labels = set()
    ranks = {'top': 0, 'trending': 0, 'reader_favorites': 0}
    recipe_done = False
    recipe_seen = False
    top_done = False
    top_partial_done = False
    trending_seen = False
    rf_seen = False
    no_progress = 0

    for pass_i in range(MAX_PASSES):
        dismiss_cannot_connect(driver)

        boundaries = []
        on_screen = []
        for name, sec in SECTION_HEADERS.items():
            try:
                el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, name)
                y = el.location['y']
                boundaries.append((y, sec))
                if y > 0:
                    on_screen.append((y, name))
                    if sec == 'trending':
                        trending_seen = True
                    elif sec == 'reader_favorites':
                        rf_seen = True
            except Exception:
                pass
        boundaries.sort()

        if not top_done:
            for h_name in TOP_STOP_HEADERS:
                try:
                    el = driver.find_element(AppiumBy.XPATH,
                        '//XCUIElementTypeOther[contains(@name, "{}")]'.format(h_name))
                    if el.location['y'] < win_h:
                        top_done = True
                        print("  Top Stories capped by '{}'".format(h_name))
                        break
                except Exception:
                    pass

        shot_label = (sorted(on_screen)[0][1].lower().replace(' ', '-')
                      if on_screen else 'feed')
        save_screenshot(driver, shot_label, screenshots_dir)

        # Snapshot content cells before interacting so coordinates stay stable.
        # Trending sorts column-major (left col = ranks 1-3, right = 4-6).
        snaps = _sort_snaps(_get_snaps(driver, win_h), boundaries)

        print("Pass {}: {} cells, headers={}".format(
            pass_i + 1, len(snaps), [(y, s) for y, s in boundaries]))

        made_progress = False

        # Featured Recipe — tap-and-hold to get Copy Link, collected once.
        if not recipe_done:
            recipe_rows, _recipe_seen = collect_recipe(driver)
            if _recipe_seen:
                recipe_seen = True
            for title, desc, link in recipe_rows:
                key = 'recipe::' + title
                if key in seen_labels:
                    continue
                seen_labels.add(key)
                stories.append((link, 'recipe', 'recipe', run_time, '', '', '', title, desc, False))
                print("  [recipe]{} {}".format('' if link else ' (no link)', title))
                made_progress = True
                recipe_done = True

        snaps_queue = deque(snaps)
        while snaps_queue:
            s = snaps_queue.popleft()
            label = s['label']
            if not label or label in seen_labels:
                continue
            seen_labels.add(label)

            # Active section: last header at or above this cell; default 'top'.
            section = 'top'
            for h_y, h_sec in boundaries:
                if h_y <= s['y']:
                    section = h_sec
                else:
                    break

            if section == 'top' and (top_done or ranks.get('top', 0) >= 7):
                continue

            is_plus = 'Apple News Plus' in label
            publication, author, headline = parse_story(section, label)

            # Reader Favorites are all News+ (no Copy Link). Elsewhere, tap the
            # ellipsis for non-News+ stories only.
            link = ''
            if not is_plus and section != 'reader_favorites':
                link = copy_link_via_ellipsis(driver, s['x'], s['y'], s['w'], s['h'])

            ranks[section] = ranks.get(section, 0) + 1
            rank = ranks[section]

            pub_time = parse_pub_date(label)
            stories.append((link, rank, section, run_time, pub_time,
                            publication, author, headline, '', is_plus))
            print("  [{}/{}]{} {}".format(
                section, rank,
                ' (News+)' if is_plus else ('' if link else ' (no link)'),
                headline[:60]))
            made_progress = True

            # After top/2: partial scroll to pull remaining top stories into view,
            # then extend the queue with any newly visible cells.
            if section == 'top' and rank == 2 and not top_partial_done:
                top_partial_done = True
                swipe_partial(driver, win_h)
                sleep(1.0)
                snaps_queue.extend(_sort_snaps(_get_snaps(driver, win_h), boundaries))

        no_progress = 0 if made_progress else no_progress + 1

        # Stop early once every section that appeared in the feed is collected.
        if top_done:
            trending_ok = not trending_seen or ranks.get('trending', 0) > 0
            rf_ok = not rf_seen or ranks.get('reader_favorites', 0) > 0
            recipe_ok = not recipe_seen or recipe_done
            if trending_ok and rf_ok and recipe_ok:
                print("All sections collected — stopping")
                break

        if no_progress >= 3:
            print("No new stories after 3 passes — stopping")
            break

        swipe_up(driver, win_h)
        sleep(1.5)

    return stories


def save_stories(stories):
    _save_stories(stories, output_file)


def save_json(stories, run_time):
    _save_json(stories, run_time, output_folder)


def main():
    if MAX_RUN_SECONDS > 0:
        def _timeout_handler(signum, frame):
            print("Run exceeded {} seconds — terminating".format(MAX_RUN_SECONDS))
            raise SystemExit(1)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUN_SECONDS)

    print("Device: {} ({})".format(device_name_and_os, udid))

    # Terminate the app and wipe Caches/tmp for a fresh feed.
    subprocess.run(['xcrun', 'simctl', 'terminate', udid, 'com.apple.news'],
                   check=False, capture_output=True)
    base = '/Users/{}/Library/Developer/CoreSimulator/Devices/{}/data/Containers/Data/Application/*/Library'.format(
        os.environ['USER'], udid)
    for folder in glob(base + '/Caches/News') + glob(base.replace('/Library', '/tmp')):
        try:
            wipe_app_data_folder(folder)
        except Exception:
            pass

    screenshots_dir = os.path.join(output_folder, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)

    reinstall = wda_needs_reinstall(udid)
    if reinstall:
        print("WDA bundle missing or version mismatch — will force reinstall")
        clear_wda_derived_data()

    print("Opening app...")
    try:
        driver = start_driver(
            app_path=APP_PATH,
            device_name=device_name_and_os,
            udid=udid,
            platform_version=device_os,
            rebuild_wda=reinstall,
            headless_mode=HEADLESS_SIMULATOR,
            clear_wda_derived_data_fn=clear_wda_derived_data,
        )
    except Exception as e:
        print("Error connecting to Appium: {}".format(e))
        return

    # Landscape for the 3-column layout the reference traces describe.
    try:
        driver.orientation = 'LANDSCAPE'
    except Exception:
        pass
    sleep(8)  # wait for feed to fully load
    dismiss_cannot_connect(driver)

    run_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        print("Collecting iPad feed...")
        stories = collect_feed(driver, run_time, screenshots_dir)
        if stories:
            save_stories(stories)
            save_json(stories, run_time)
            print("Saved {} story rows".format(len(stories)))
        else:
            print("No stories found")
    except Exception as e:
        print("Error: {}".format(e))

    try:
        driver.terminate_app('com.apple.news')
    except Exception:
        pass
    driver.quit()

    # Hygiene: let WDA tear down, then shut the simulator down to clear
    # accumulated accessibility-automation state between runs.
    try:
        wait_for_wda_teardown()
        relaunch_simulator(udid)
    except Exception as e:
        print("Simulator relaunch failed: {}".format(e))


if __name__ == '__main__':
    main()
