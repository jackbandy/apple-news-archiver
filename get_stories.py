'''
get_stories.py

Collects Apple News stories (Top an Trending)
by long-pressing each story card to copy its link.

Each story is appended to stories.csv with the
timestamp of first appearance.
'''
__author__ = "Jack Bandy"
# Refactored in March 2026 with help from Claude

import os
import re
import csv
import json
import fcntl
import signal
import datetime
import subprocess
from time import sleep
from shutil import rmtree
from glob import glob
from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

from config import (
    device_name_and_os, device_os, udid,
    output_folder, output_file,
    COLLECT_TOP_STORIES, APP_PATH,
    MIN_STORY_CELL_HEIGHT, TAB_BAR_HEIGHT, SAFE_TAP_MARGIN, MAX_TOP_STORIES,
    MAX_TOP_HOME, MAX_READER_FAVORITES, MAX_POPULAR_STORIES, MAX_TRENDING,
    MAX_RUN_SECONDS,
)


LOCK_PATH = '/tmp/apple_news_scraper.lock'

# Path where Appium stores the compiled WDA xctest bundle.
_WDA_DERIVED_DATA_PATTERN = os.path.expanduser(
    '~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*'
)

# Appium embeds the target SDK in the xctestrun filename, e.g.:
#   WebDriverAgentRunner_iphonesimulator26.2-arm64.xctestrun
# We parse this to detect iOS SDK version mismatches before connecting.
_XCTESTRUN_GLOB = os.path.join(_WDA_DERIVED_DATA_PATTERN, 'Build/Products/*.xctestrun')


def wda_needs_rebuild(target_udid):
    '''Return True if WDA must be rebuilt before the next Appium session.

    Detection logic:
      1. Look for a compiled WDA xctestrun file under Xcode DerivedData.
         If none exists, WDA has never been built → needs build.
      2. Ask the simulator what iOS version it is running (xcrun simctl).
      3. Compare that version to the SDK version embedded in the xctestrun
         filename (e.g. "iphonesimulator26.2" → "26.2").
         If they differ, the old bundle will crash when Appium tries to
         start a session on the newer runtime → needs rebuild.

    When this function returns True, callers should:
      - delete DerivedData via clear_wda_derived_data()
      - set the Appium capability usePrebuiltWDA=False

    On any error (simctl unavailable, unexpected filename format, etc.)
    returns False so as not to trigger an unnecessary rebuild.
    '''
    xctestrun_files = glob(_XCTESTRUN_GLOB)
    if not xctestrun_files:
        return True  # no build at all

    # Ask the simulator for its current runtime version.
    try:
        result = subprocess.run(
            ['xcrun', 'simctl', 'list', 'devices', '--json'],
            capture_output=True, text=True, check=True,
        )
        devices_json = json.loads(result.stdout)
    except Exception as e:
        print("wda_needs_rebuild: could not query simctl ({}) — skipping rebuild check".format(e))
        return False

    # Find the runtime key for our target UDID.
    # Runtime keys look like "com.apple.CoreSimulator.SimRuntime.iOS-26-3".
    sim_version = None
    for runtime_key, device_list in devices_json.get('devices', {}).items():
        for device in device_list:
            if device.get('udid') == target_udid:
                m = re.search(r'iOS-(\d+)-(\d+)', runtime_key)
                if m:
                    sim_version = '{}.{}'.format(m.group(1), m.group(2))
                break
        if sim_version:
            break

    if not sim_version:
        print("wda_needs_rebuild: could not find simulator {} in simctl output — skipping rebuild check".format(target_udid))
        return False

    # Check whether any existing xctestrun was compiled for the current SDK.
    # Filename format: WebDriverAgentRunner_iphonesimulator<SDK>-<arch>.xctestrun
    for path in xctestrun_files:
        basename = os.path.basename(path)
        if 'iphonesimulator{}'.format(sim_version) in basename:
            return False  # existing build matches current simulator version

    # All found xctestrun files target a different SDK.
    built_versions = [os.path.basename(p) for p in xctestrun_files]
    print("wda_needs_rebuild: simulator is iOS {} but WDA was built for: {}".format(
        sim_version, built_versions))
    return True


def clear_wda_derived_data():
    '''Delete all WDA DerivedData directories so Appium rebuilds from source.

    Safe to call even if no DerivedData exists (glob returns empty list).
    Appium will rebuild WDA automatically on the next session when
    usePrebuiltWDA=False is set in the capabilities.
    '''
    for path in glob(_WDA_DERIVED_DATA_PATTERN):
        try:
            rmtree(path)
            print("clear_wda_derived_data: removed {}".format(path))
        except Exception as e:
            print("clear_wda_derived_data: could not remove {} ({})".format(path, e))


def main():
    # Prevent overlapping runs (e.g. if a previous cron job is still running)
    lock_fd = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running — exiting")
        lock_fd.close()
        return

    if MAX_RUN_SECONDS > 0:
        def _timeout_handler(signum, frame):
            print("Run exceeded {} seconds — terminating".format(MAX_RUN_SECONDS))
            raise SystemExit(1)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUN_SECONDS)

    # Terminate the app cleanly before wiping data (avoids the app rewriting
    # cache files as we delete them)
    try:
        subprocess.run(['xcrun', 'simctl', 'terminate', udid, 'com.apple.news'],
                       check=False, capture_output=True)
    except Exception:
        pass

    # Wipe Caches/ and tmp/ for a fresh feed
    user = os.environ['USER']
    app_data_pattern = '/Users/{}/Library/Developer/CoreSimulator/Devices/{}/data/Containers/Data/Application/*/Library'.format(user, udid)
    matches = glob(app_data_pattern + '/Caches/News')
    for folder in matches:
        try:
            wipe_app_data_folder(folder)
        except Exception:
            print("Couldn't wipe {}".format(folder))
    # Also wipe tmp/
    tmp_matches = glob(app_data_pattern.replace('/Library', '/tmp'))
    for folder in tmp_matches:
        try:
            wipe_app_data_folder(folder)
        except Exception:
            pass

    os.makedirs(output_folder, exist_ok=True)

    rebuild = wda_needs_rebuild(udid)
    if rebuild:
        print("WDA DerivedData is stale or missing — clearing for rebuild")
        clear_wda_derived_data()

    print("Opening app...")
    options = XCUITestOptions()
    options.app = APP_PATH
    options.device_name = device_name_and_os
    options.udid = udid
    options.platform_version = device_os
    options.no_reset = True
    options.set_capability('locationServicesEnabled', True)
    options.set_capability('gpsEnabled', True)
    if rebuild:
        # Tell Appium not to reuse any cached WDA bundle; build fresh from source.
        # This is only set when wda_needs_rebuild() detected a version mismatch,
        # so normal runs pay no build overhead.
        options.set_capability('usePrebuiltWDA', False)
        # A fresh WDA build from source can take several minutes. Raise both
        # timeouts so Appium doesn't give up before the build finishes.
        options.set_capability('wdaLaunchTimeout', 300000)    # 5 min
        options.set_capability('wdaConnectionTimeout', 300000)  # 5 min

    try:
        driver = webdriver.Remote(
            command_executor='http://localhost:4723',
            options=options
        )
    except Exception as e:
        print("Error connecting to Appium: {}".format(e))
        lock_fd.close()
        return

    sleep(8)  # wait for feed to fully load

    try:
        run_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Collect stories from the home page (top 1-5 and trending 1-4)
        print("Collecting home page stories...")
        all_stories = collect_home_page(driver, run_time)

        # Optionally navigate into the Top Stories view for ranked collection
        if COLLECT_TOP_STORIES:
            print("Navigating to Top Stories view...")
            top_stories_el = None
            for _ in range(10):
                try:
                    top_stories_el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Top Stories')
                    break
                except Exception:
                    sleep(1)
            if top_stories_el:
                tap(driver, 100,
                    top_stories_el.location['y'] + top_stories_el.size['height'] // 2)
                sleep(4)
                home_links = {row[0] for row in all_stories if row[0]}
                ranked = collect_top_stories_view(driver, run_time, seen_links=home_links)
                all_stories.extend(ranked)
            else:
                print("Could not find 'Top Stories' element, skipping")

        if all_stories:
            save_stories(all_stories)
            save_json(all_stories, run_time)
            print("Saved {} story rows".format(len(all_stories)))
        else:
            print("No stories found")

    except Exception as e:
        print("Error: {}".format(e))

    try:
        driver.terminate_app('com.apple.news')
    except Exception:
        pass
    driver.quit()



def collect_home_page(driver, run_time):
    '''
    Collect stories from the Apple News home page, scrolling as needed.

    Layout (top to bottom):
      - "Top Stories": hero + several cells, section="top"
      - "Reader Favorites" header — collected as section="reader_favorites"
      - "Popular in News+" header — collected as section="popular"
      - "Trending Stories" header — collected as section="trending"
      - Any other header (e.g. "For You", "Food") — skip until next target header

    Section boundaries are determined by header y-positions. XCUITest returns
    off-screen elements with negative y, so boundaries remain active after
    scrolling past them. Cells are snapshotted before long-pressing to avoid
    stale elements.
    '''
    window_size = driver.get_window_size()
    window_height = window_size['height']
    window_width = window_size['width']
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN

    # Headers for sections we want to collect from, mapped to their section name.
    TARGET_SECTION_HEADERS = {
        'Reader Favorites':   'reader_favorites',
        'Popular in News+':   'popular',
        'Trending Stories':   'trending',
        'Chicago':            'chicago',
        'Illinois':           'illinois',
        'Illinois Politics':  'illinois_politics',
    }
    # Any header not in TARGET_SECTION_HEADERS triggers a skip zone.
    # Stories between a skip header and the next target header are ignored.
    SKIP_HEADERS = ("For You", "Editors' Picks", "Latest Puzzles", "Food")

    stories = []
    seen_labels = set()
    top_rank = 0
    top_total = 0
    reader_favorites_rank = 0
    popular_rank = 0
    trending_rank = 0
    chicago_rank = 0
    illinois_rank = 0
    illinois_politics_rank = 0
    no_progress_streak = 0

    for attempt in range(40):
        if (top_total >= MAX_TOP_HOME and trending_rank >= MAX_TRENDING
                and reader_favorites_rank >= MAX_READER_FAVORITES
                and popular_rank >= MAX_POPULAR_STORIES):
            break

        # Build a sorted list of (y, section_or_None) for every known header
        # visible or scrolled past. section=None means skip zone.
        # XCUITest returns off-screen elements with negative y, so past headers
        # remain in the list and continue to define section boundaries.
        header_boundaries = []
        for name, section in TARGET_SECTION_HEADERS.items():
            try:
                el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, name)
                header_boundaries.append((el.location['y'], section))
            except Exception:
                pass
        for name in SKIP_HEADERS:
            try:
                el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, name)
                header_boundaries.append((el.location['y'], None))
            except Exception:
                pass
        header_boundaries.sort()

        # Local sections (chicago/illinois/illinois_politics) are considered
        # exhausted once any subsequent header has appeared after them — i.e.,
        # they are not the last entry in the sorted boundary list.
        LOCAL_SECTIONS = ('chicago', 'illinois', 'illinois_politics')
        exhausted_sections = {
            s for i, (y, s) in enumerate(header_boundaries)
            if s in LOCAL_SECTIONS and i < len(header_boundaries) - 1
        }

        cells = driver.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeCell')
        visible = sorted(
            [c for c in cells
             if c.size['height'] >= MIN_STORY_CELL_HEIGHT
             and c.location['y'] >= 60
             and c.location['y'] < safe_y],
            key=lambda c: c.location['y']
        )

        # Snapshot before any long-pressing
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

        print("Attempt {}: {} cells, headers={}".format(
            attempt + 1, len(snapshots),
            [(y, s) for y, s in header_boundaries]))

        made_progress = False
        for s in snapshots:
            label = s['label']

            if label and label in seen_labels:
                continue

            # Find active section: walk sorted boundaries, last one at or above
            # cell's y wins. Default to 'top' before any header is encountered.
            # None means we're in a skip zone.
            active_section = 'top'
            for (h_y, h_section) in header_boundaries:
                if h_y <= s['y']:
                    active_section = h_section
                else:
                    break

            if active_section is None:
                seen_labels.add(label)
                continue

            is_plus_story = 'Apple News Plus' in label
            # Promo cell: short label containing "News+" but not an actual story
            is_promo = not is_plus_story and 'News+' in label and len(label) < 40
            # Audio cell: contains podcast/audio markers
            is_audio = 'Play Now' in label or 'Listen to the day' in label

            if is_promo:
                seen_labels.add(label)
                continue  # News+ promo tab, no story

            if active_section == 'trending':
                if trending_rank >= MAX_TRENDING:
                    seen_labels.add(label)
                    continue
                trending_rank += 1
                rank = trending_rank
                section = 'trending'
            elif active_section == 'popular':
                if popular_rank >= MAX_POPULAR_STORIES:
                    seen_labels.add(label)
                    continue
                popular_rank += 1
                rank = popular_rank
                section = 'popular'
            elif active_section == 'reader_favorites':
                if reader_favorites_rank >= MAX_READER_FAVORITES:
                    seen_labels.add(label)
                    continue
                reader_favorites_rank += 1
                rank = reader_favorites_rank
                section = 'reader_favorites'
            elif active_section in LOCAL_SECTIONS:
                if active_section in exhausted_sections:
                    seen_labels.add(label)
                    continue
                if active_section == 'chicago':
                    chicago_rank += 1
                    rank = chicago_rank
                elif active_section == 'illinois':
                    illinois_rank += 1
                    rank = illinois_rank
                else:
                    illinois_politics_rank += 1
                    rank = illinois_politics_rank
                section = active_section
            elif top_total >= MAX_TOP_HOME:
                # Top section is full — skip until a named section header appears
                seen_labels.add(label)
                continue
            elif is_audio:
                rank = 'audio'
                section = 'top'
                top_total += 1
            elif is_plus_story:
                rank = 'plus'
                section = 'top'
                top_total += 1
            else:
                top_rank += 1
                rank = top_rank
                section = 'top'
                top_total += 1

            x_c = max(80, min(s['x'] + s['w'] // 2, window_width - 80))
            y_c = max(100, min(s['y'] + s['h'] // 2, safe_y - 20))

            publication, author, headline, pub_time = '', '', '', ''
            try:
                if section == 'trending':
                    # Trending label format: "Headline[, Apple News Plus], time ago[, Author]"
                    # Split on the time marker to isolate headline and author.
                    # Publication is not present in trending cell labels; it is
                    # filled in from the article view (get_article_headline) below.
                    tm = re.search(r',\s*\d+\s+(?:minute|hour|day|week|month)s?\s+ago', label)
                    if tm:
                        headline = label[:tm.start()].strip()
                        # Strip trailing ", Apple News Plus" that sometimes precedes the time marker
                        headline = re.sub(r',\s*Apple News Plus\s*$', '', headline).strip()
                        author = label[tm.end():].lstrip(', ').strip()
                    else:
                        headline = label.strip()
                else:
                    publication, headline, author = parse_cell_label(label)
                pub_time = parse_pub_date(label)
            except Exception:
                pass

            raw, _ = long_press_copy_link(driver, x_c, y_c, window_height)
            seen_labels.add(label)

            # If the long-press accidentally opened a story (0 cells visible),
            # swipe back to the home feed before continuing.
            if raw is None:
                check = driver.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeCell')
                if not any(c.size['height'] >= MIN_STORY_CELL_HEIGHT for c in check):
                    print("  Navigated away from home feed, swiping back...")
                    back_swipe(driver, window_height)
                    sleep(2)
                    break  # restart the outer attempt loop with a fresh cell scan

            link = ''
            if raw:
                idx = raw.find('https://apple.news')
                if idx >= 0:
                    link = raw[idx:]

            # For numeric-ranked top stories, reclaim the slot if no link.
            # Plus/audio/trending rows are saved even without a link.
            if not link and section == 'top' and isinstance(rank, int):
                top_rank -= 1
                top_total -= 1
                continue

            article_headline, article_publication = get_article_headline(driver, x_c, y_c, window_height)
            if not publication:
                publication = article_publication

            stories.append((link, rank, section, run_time, pub_time, publication, author, headline, article_headline))
            print("  [{}/{}]{}".format(section, rank, ' (no link)' if not link else ''))
            print("    Publisher:        {}".format(publication or '—'))
            print("    Display Headline: {}".format(headline))
            print("    Article Headline: {}".format(article_headline or '—'))
            print("    Link:             {}".format(link or '—'))
            made_progress = True

        if not made_progress:
            no_progress_streak += 1
            # Keep scrolling if we've seen mid-feed headers but not Trending yet.
            found_sections = {s for (_, s) in header_boundaries if s is not None}
            still_searching_trending = (
                bool(header_boundaries) and 'trending' not in found_sections
            )
            if no_progress_streak >= 10 and not still_searching_trending:
                break  # nothing new after consecutive scrolls
            if no_progress_streak >= 20:
                print("Trending not found after scrolling through mid-feed, stopping")
                break
        else:
            no_progress_streak = 0

        # Scroll down to reveal more content. Start from center rather than
        # near the bottom to avoid the "Continue Reading" pill above the tab bar.
        from_y = min(window_height // 2 + 50, window_height - 200)
        to_y = max(100, from_y - 400)
        swipe(driver, 100, from_y, 100, to_y)
        sleep(1)

    return stories


def collect_top_stories_view(driver, run_time, seen_links=None):
    '''
    In the Top Stories view, scroll through cells and collect links via
    long-press → Copy Link. Assigns a numeric rank to each story reflecting
    its true position in the feed. Stories whose links are in seen_links
    (already collected from the home page) are counted for ranking but not
    added to the output. Stops after MAX_TOP_STORIES ranked.

    Cell positions are snapshotted at the start of each scroll attempt
    to avoid stale element errors.
    '''
    stories = []
    seen_this_run = set()
    rank = 0
    if seen_links is None:
        seen_links = set()

    window_size = driver.get_window_size()
    window_height = window_size['height']
    window_width = window_size['width']
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN

    for attempt in range(30):
        if rank >= MAX_TOP_STORIES:
            break

        cells = driver.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeCell')
        visible = sorted(
            [c for c in cells
             if c.size['height'] >= MIN_STORY_CELL_HEIGHT
             and c.location['y'] >= 60
             and c.location['y'] < safe_y],
            key=lambda c: c.location['y']
        )

        # Snapshot before long-pressing
        snapshots = []
        for cell in visible:
            label = ''
            try:
                for el in cell.find_elements(AppiumBy.CLASS_NAME, 'XCUIElementTypeOther'):
                    name = el.get_attribute('name') or ''
                    if ',' in name and len(name) > 20:
                        label = name
                        break
            except Exception:
                pass
            snapshots.append({
                'x': cell.location['x'], 'y': cell.location['y'],
                'w': cell.size['width'],  'h': cell.size['height'],
                'label': label,
            })

        print("Attempt {}: {} cells visible".format(attempt + 1, len(snapshots)))

        if not snapshots:
            swipe(driver, 100, 600, 100, 350)
            sleep(1)
            continue

        for s in snapshots:
            if rank >= MAX_TOP_STORIES:
                break

            x_c = max(80, min(s['x'] + s['w'] // 2, window_width - 80))
            y_c = max(100, min(s['y'] + s['h'] // 2, safe_y - 20))

            publication, author, headline, pub_time = '', '', '', ''
            try:
                publication, headline, author = parse_cell_label(s['label'])
                pub_time = parse_pub_date(s['label'])
            except Exception:
                pass

            raw, _ = long_press_copy_link(driver, x_c, y_c, window_height)
            if not raw:
                continue

            idx = raw.find('https://apple.news')
            if idx < 0:
                continue
            link = raw[idx:]

            if link in seen_this_run:
                continue
            seen_this_run.add(link)
            rank += 1

            if link in seen_links:
                print("  [top/{}] (already collected from home page, skipping)".format(rank))
                continue

            article_headline, article_publication = get_article_headline(driver, x_c, y_c, window_height)
            if not publication:
                publication = article_publication

            stories.append((link, rank, 'top', run_time, pub_time, publication, author, headline, article_headline))
            print("  [top/{}]".format(rank))
            print("    Publisher:        {}".format(publication or '—'))
            print("    Display Headline: {}".format(headline))
            print("    Article Headline: {}".format(article_headline or '—'))
            print("    Link:             {}".format(link))

        # Scroll down to reveal new content
        from_y = min(window_height - 200, safe_y - 50)
        to_y = max(100, from_y - 300)
        swipe(driver, 100, from_y, 100, to_y)
        sleep(1)

    return stories



# data I/O

def save_stories(stories):
    '''Append story rows to stories.csv, writing header if file is new.'''
    write_header = not os.path.exists(output_file)
    with open(output_file, 'a', newline='') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'author', 'headline', 'article_headline'])
        for row in stories:
            writer.writerow(row)


def save_json(stories, run_time):
    '''Write a JSON file for this run to data_output/json/<run_time>.json.'''
    json_folder = os.path.join(output_folder, 'json')
    os.makedirs(json_folder, exist_ok=True)
    filename = run_time.replace(':', '-').replace(' ', '_') + '.json'
    path = os.path.join(json_folder, filename)

    keys = ['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'author', 'headline', 'article_headline']
    records = [dict(zip(keys, row)) for row in stories]

    payload = {
        'run_time': run_time,
        'story_count': len(records),
        'stories': records,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print("JSON saved to {}".format(path))



# touch / gesture helpers

def tap(driver, x, y):
    driver.execute_script('mobile: tap', {'x': x, 'y': y})


def swipe(driver, from_x, from_y, to_x, to_y, duration=1.0):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(from_x, from_y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(duration)
    actions.w3c_actions.pointer_action.move_to_location(to_x, to_y)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


def back_swipe(driver, window_height):
    '''Quick left-edge swipe to trigger iOS back navigation.'''
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(5, window_height // 2)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.move_to_location(200, window_height // 2)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


def long_press(driver, x, y, duration=1.5):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(x, y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(duration)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


def get_article_headline(driver, x, y, window_height):
    '''Tap a story card at (x, y), extract the publication and headline from
    the article view, then tap the Back button.

    Returns (headline, publication) — either or both may be '' on failure.

    Primary source: the article ScrollView whose name attribute is
    "Publication, Headline". This is the most reliable element and also
    provides the publication name, which is useful for sections (e.g.
    trending) where the cell label does not include a publication.

    Fallback (headline only): XCUIElementTypeOther elements with
    traits="Header", skipping short category labels like "World news".
    '''
    tap(driver, x, y)
    sleep(3)

    article_headline = ''
    article_publication = ''
    try:
        # The article ScrollView's name attribute is "Publication, Headline".
        scroll_els = driver.find_elements(
            AppiumBy.XPATH, '//XCUIElementTypeScrollView[contains(@name, ",")]'
        )
        for el in scroll_els:
            name = (el.get_attribute('name') or '').strip()
            if len(name) > 20:
                pub, headline, _ = parse_cell_label(name)
                if headline:
                    article_headline = headline
                    article_publication = pub
                    break
    except Exception:
        pass

    if not article_headline:
        try:
            # Fallback: traits="Header" elements, skipping short category labels
            # (e.g. "World news", "Technology") which appear before the headline.
            els = driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeOther[@traits="Header"]')
            for el in els:
                val = (el.get_attribute('value') or '').strip()
                if len(val) > 20:
                    article_headline = val
                    break
        except Exception:
            pass

    try:
        back_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'BackButton')
        tap(driver, back_btn.location['x'] + back_btn.size['width'] // 2,
            back_btn.location['y'] + back_btn.size['height'] // 2)
    except Exception:
        back_swipe(driver, window_height)
    sleep(2)

    return article_headline, article_publication


def long_press_copy_link(driver, x, y, window_height):
    '''Long-press at (x, y) and tap "Copy Link" from the context menu.
    Returns (link_text, None). Dismisses via top of screen if no Copy Link.'''
    print("  Long-pressing at {}, {}".format(x, y))
    long_press(driver, x, y, duration=1.5)
    sleep(0.1)

    try:
        copy_el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Copy Link')
        cx = copy_el.location['x'] + copy_el.size['width'] // 2
        cy = copy_el.location['y'] + copy_el.size['height'] // 2
        tap(driver, cx, cy)
        sleep(0.5)
        return driver.get_clipboard_text(), None
    except Exception:
        print("  No 'Copy Link' found, dismissing")
        tap(driver, 200, 30)  # status bar — safely above all story cards
        sleep(1.5)
        return None, None



# metadata parsing

def parse_cell_label(label):
    '''Parse a cell label into (publication, headline, author).

    Handles these formats:
      "Publication, Headline, time ago[, Author]"
      "BREAKING, Publication, Headline, time ago[, Author]"
      "Publication, Apple News Plus, Headline, time ago[, Author]"
      "Headline with commas, Apple News Plus, time ago[, Author]"  (trending, no publication)
      "Blurb text..., Play Now, ..."  (audio cell — no publication)

    The key disambiguation: if the text before ", Apple News Plus, " contains
    a comma, it is a multi-part headline with no publication. If it has no
    comma, it is a publication name.
    '''
    if not label:
        return '', '', ''

    # Audio cells: the blurb is the headline, publisher is Apple News Today
    for audio_marker in (', Play Now', ', Listen to the day'):
        if audio_marker in label:
            headline = label.split(audio_marker, 1)[0].strip()
            return 'Apple News Today', headline, ''

    plus_marker = ', Apple News Plus, '
    if plus_marker in label:
        before_plus, after_plus = label.split(plus_marker, 1)
        if ',' not in before_plus:
            # "Publication, Apple News Plus, Headline, time, Author"
            publication = before_plus
            rest = after_plus
        else:
            # "Headline with commas, Apple News Plus, time, Author" — no publication
            publication = ''
            headline = before_plus
            time_match = re.search(r'^\d+\s+(?:hour|minute|day|week|month)s?\s+ago', after_plus)
            author = after_plus[time_match.end():].lstrip(', ').strip() if time_match else ''
            return publication, headline, author
    else:
        parts = label.split(', ', 1)
        if len(parts) < 2:
            return label, '', ''
        publication = parts[0]
        rest = parts[1]

        # Breaking news prefix: "BREAKING, ActualPublication, Headline..."
        if publication.strip() == 'BREAKING':
            sub = rest.split(', ', 1)
            if len(sub) >= 2:
                publication, rest = sub[0], sub[1]
            else:
                publication = ''

    time_match = re.search(r',\s*\d+\s+(?:hour|minute|day|week|month)s?\s+ago', rest)
    if time_match:
        headline = rest[:time_match.start()].strip()
        author = rest[time_match.end():].lstrip(', ').strip()
    else:
        headline = rest
        author = ''
    return publication, headline, author


def parse_pub_date(label):
    '''Estimate publication datetime from "X hours/minutes/days ago" in a cell label.'''
    m = re.search(r'(\d+)\s+(minute|hour|day|week|month)s?\s+ago', label)
    if not m:
        return ''
    n, unit = int(m.group(1)), m.group(2)
    delta = {
        'minute': datetime.timedelta(minutes=n),
        'hour':   datetime.timedelta(hours=n),
        'day':    datetime.timedelta(days=n),
        'week':   datetime.timedelta(weeks=n),
        'month':  datetime.timedelta(days=n * 30),
    }.get(unit, datetime.timedelta())
    return (datetime.datetime.now() - delta).strftime('%Y-%m-%d %H:%M:%S')



# utility

def wipe_app_data_folder(path):
    for f in os.listdir(path):
        full = '{}/{}'.format(path, f)
        if os.path.isfile(full):
            os.remove(full)
        else:
            rmtree(full)


if __name__ == '__main__':
    main()
