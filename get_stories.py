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
)


LOCK_PATH = '/tmp/apple_news_scraper.lock'


def main():
    # Prevent overlapping runs (e.g. if a previous cron job is still running)
    lock_fd = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running — exiting")
        lock_fd.close()
        return

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

    print("Opening app...")
    options = XCUITestOptions()
    options.app = APP_PATH
    options.device_name = device_name_and_os
    options.udid = udid
    options.platform_version = device_os
    options.no_reset = True
    options.set_capability('locationServicesEnabled', True)
    options.set_capability('gpsEnabled', True)

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
                ranked = collect_top_stories_view(driver, run_time)
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
      - "Top Stories": hero + several cells, section="top", ranks 1-5
      - "Reader Favorites" header — collected as section="reader_favorites"
      - "For You" / "Latest Puzzles" / "Editors' Picks" — skipped entirely
      - "Trending Stories" header — collected as section="trending", ranks 1-4

    Section boundaries are determined by the visible y-position of the
    corresponding header elements (XCUITest returns off-screen elements with
    negative y, so boundaries stay active after scrolling past them).
    Cell positions are snapshotted before long-pressing to avoid stale elements.
    '''
    window_size = driver.get_window_size()
    window_height = window_size['height']
    window_width = window_size['width']
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN

    # Headers that mark sections to skip entirely (algorithmic / non-editorial).
    # Add new section names here as they're discovered.
    SKIP_ZONE_HEADERS = ("For You", "Editors' Picks", "Latest Puzzles")

    stories = []
    seen_labels = set()
    top_rank = 0           # numeric rank within top section
    top_total = 0          # total top rows collected (numeric + plus + audio), cap = MAX_TOP_HOME
    reader_favorites_rank = 0
    popular_rank = 0
    trending_rank = 0
    no_progress_streak = 0

    for attempt in range(40):
        if top_total >= MAX_TOP_HOME and trending_rank >= MAX_TRENDING:
            break

        # Locate section header y-positions (XCUITest returns off-screen
        # elements with negative y, so these stay active after scrolling past).
        reader_favorites_y = None
        for_you_y = None
        popular_section_y = None
        trending_section_y = None
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Reader Favorites')
            reader_favorites_y = el.location['y']
        except Exception:
            pass
        for header in SKIP_ZONE_HEADERS:
            try:
                el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, header)
                y = el.location['y']
                if for_you_y is None or y < for_you_y:
                    for_you_y = y
            except Exception:
                pass
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Popular in News+')
            popular_section_y = el.location['y']
        except Exception:
            pass
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Trending Stories')
            trending_section_y = el.location['y']
        except Exception:
            pass

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

        print("Attempt {}: {} cells, reader_fav_y={}, for_you_y={}, popular_y={}, trending_y={}".format(
            attempt + 1, len(snapshots), reader_favorites_y, for_you_y, popular_section_y, trending_section_y))

        made_progress = False
        for s in snapshots:
            label = s['label']

            if label and label in seen_labels:
                continue

            in_trending = trending_section_y is not None and s['y'] > trending_section_y
            in_popular = (popular_section_y is not None and s['y'] > popular_section_y
                          and not in_trending)
            in_for_you = (for_you_y is not None and s['y'] > for_you_y
                          and not in_popular and not in_trending)
            in_reader_favorites = (reader_favorites_y is not None and s['y'] > reader_favorites_y
                                   and not in_for_you and not in_popular and not in_trending)

            if in_for_you:
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

            if in_trending:
                if trending_rank >= MAX_TRENDING:
                    seen_labels.add(label)
                    continue
                trending_rank += 1
                rank = trending_rank
                section = 'trending'
            elif in_popular:
                if popular_rank >= MAX_POPULAR_STORIES:
                    seen_labels.add(label)
                    continue
                popular_rank += 1
                rank = popular_rank
                section = 'popular'
            elif in_reader_favorites:
                if reader_favorites_rank >= MAX_READER_FAVORITES:
                    seen_labels.add(label)
                    continue
                reader_favorites_rank += 1
                rank = reader_favorites_rank
                section = 'reader_favorites'
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

            publication, headline, pub_time = '', '', ''
            try:
                if section == 'trending':
                    headline = label.strip()
                else:
                    publication, headline, _ = parse_cell_label(label)
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

            article_headline = get_article_headline(driver, x_c, y_c, window_height)

            stories.append((link, rank, section, run_time, pub_time, publication, headline, article_headline))
            print("  [{}/{}]{}".format(section, rank, ' (no link)' if not link else ''))
            print("    Publisher:        {}".format(publication or '—'))
            print("    Display Headline: {}".format(headline))
            print("    Article Headline: {}".format(article_headline or '—'))
            print("    Link:             {}".format(link or '—'))
            made_progress = True

        if not made_progress:
            no_progress_streak += 1
            # Keep scrolling if we can see we're mid-feed but Trending not yet found.
            still_searching_trending = (
                (for_you_y is not None or reader_favorites_y is not None
                 or popular_section_y is not None)
                and trending_section_y is None
            )
            if no_progress_streak >= 10 and not still_searching_trending:
                break  # nothing new after consecutive scrolls
            if no_progress_streak >= 20:
                print("Trending not found after scrolling through mid-feed, stopping")
                break
        else:
            no_progress_streak = 0

        # Scroll down to reveal more content
        from_y = min(safe_y - 50, window_height - 150)
        to_y = max(100, from_y - 400)
        swipe(driver, 100, from_y, 100, to_y)
        sleep(1)

    return stories


def collect_top_stories_view(driver, run_time):
    '''
    In the Top Stories view, scroll through cells and collect links via
    long-press → Copy Link. Assigns a numeric rank to each story.
    New stories are always saved; previously-seen stories are saved only
    if rank <= 5. Stops after MAX_TOP_STORIES ranked.

    Cell positions are snapshotted at the start of each scroll attempt
    to avoid stale element errors.
    '''
    stories = []
    seen_this_run = set()
    rank = 0

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

            publication, headline, pub_time = '', '', ''
            try:
                publication, headline, _ = parse_cell_label(s['label'])
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

            article_headline = get_article_headline(driver, x_c, y_c, window_height)

            stories.append((link, rank, 'top', run_time, pub_time, publication, headline, article_headline))
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
            writer.writerow(['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'headline', 'article_headline'])
        for row in stories:
            writer.writerow(row)


def save_json(stories, run_time):
    '''Write a JSON file for this run to data_output/json/<run_time>.json.'''
    json_folder = os.path.join(output_folder, 'json')
    os.makedirs(json_folder, exist_ok=True)
    filename = run_time.replace(':', '-').replace(' ', '_') + '.json'
    path = os.path.join(json_folder, filename)

    keys = ['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'headline', 'article_headline']
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
    '''Tap a story card at (x, y), extract the article headline element
    (XCUIElementTypeOther with traits="Header"), then tap the Back button.
    Returns the headline string, or '' on failure.'''
    tap(driver, x, y)
    sleep(3)

    article_headline = ''
    try:
        # The article ScrollView's name attribute is "Publication, Headline" —
        # the most reliable source and avoids matching section/category labels.
        scroll_els = driver.find_elements(
            AppiumBy.XPATH, '//XCUIElementTypeScrollView[contains(@name, ",")]'
        )
        for el in scroll_els:
            name = (el.get_attribute('name') or '').strip()
            if len(name) > 20:
                _, headline, _ = parse_cell_label(name)
                if headline:
                    article_headline = headline
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

    return article_headline


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
