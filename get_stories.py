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
)


def main():
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
        exit()

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
      - top stories: hero + several cells, section="top", ranks 1-5
        (Apple News Plus story cells are skipped; audio/promo cells are skipped)
      - "Trending Stories" header — used to detect section boundary
      - trending stories: up to 4 cells, section="trending", ranks 1-4
        (Apple News Plus trending stories are saved even if no link)

    Section is determined by the visible y-position of the "Trending Stories"
    header element, not by the audio cell boundary (which is unreliable).
    Cell positions are snapshotted before long-pressing to avoid stale elements.
    '''
    window_size = driver.get_window_size()
    window_height = window_size['height']
    window_width = window_size['width']
    safe_y = window_height - TAB_BAR_HEIGHT - SAFE_TAP_MARGIN

    stories = []
    seen_labels = set()
    top_rank = 0
    trending_rank = 0
    no_progress_streak = 0
    passed_audio = False      # True once the audio cell has been seen
    cells_after_audio = 0    # cells encountered after audio, before trending appears

    for attempt in range(20):
        if top_rank >= 5 and trending_rank >= 4:
            break

        # Find y-position of the Trending Stories section header (if visible)
        trending_section_y = None
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

        print("Attempt {}: {} cells, trending_header_y={}".format(
            attempt + 1, len(snapshots), trending_section_y))

        made_progress = False
        for s in snapshots:
            label = s['label']

            if label and label in seen_labels:
                continue

            # Determine section by position relative to Trending Stories header
            in_trending = trending_section_y is not None and s['y'] > trending_section_y

            is_plus_story = 'Apple News Plus' in label
            # Promo cell: short label containing "News+" but not an actual story
            is_promo = not is_plus_story and 'News+' in label and len(label) < 40
            # Audio cell: contains podcast/audio markers
            is_audio = 'Play Now' in label or 'Listen to the day' in label

            if is_promo:
                seen_labels.add(label)
                continue  # News+ promo tab, no story

            if in_trending:
                if trending_rank >= 4:
                    seen_labels.add(label)
                    continue
                trending_rank += 1
                rank = trending_rank
                section = 'trending'
            elif is_audio:
                passed_audio = True
                rank = 'audio'
                section = 'top'
            elif passed_audio:
                # After audio but trending section not yet visible — skip entirely
                cells_after_audio += 1
                seen_labels.add(label)
                continue
            elif is_plus_story:
                rank = 'plus'
                section = 'top'
            elif top_rank >= 5:
                seen_labels.add(label)
                continue
            else:
                top_rank += 1
                rank = top_rank
                section = 'top'

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

            link = ''
            if raw:
                idx = raw.find('https://apple.news')
                if idx >= 0:
                    link = raw[idx:]

            # For numeric-ranked top stories, reclaim the slot if no link.
            # Plus/audio/trending rows are saved even without a link.
            if not link and section == 'top' and isinstance(rank, int):
                top_rank -= 1
                continue

            stories.append((link, rank, section, run_time, pub_time, publication, headline))
            print("  [{}/{}]{} {} | {} | {}".format(
                section, rank,
                ' (no link)' if not link else '',
                publication, headline[:60], link[:50] if link else ''))
            made_progress = True

        if not made_progress:
            no_progress_streak += 1
            # While scrolling past post-audio filler looking for Trending,
            # don't give up early — keep going until cells_after_audio limit.

            still_searching_trending = passed_audio and trending_section_y is None
            if no_progress_streak >= 10 and not still_searching_trending:
                break  # nothing new after consecutive scrolls
        else:
            no_progress_streak = 0

        # After the audio cell, if trending still hasn't appeared after ~5
        # sections (~40 cells) of filler, it won't — stop scrolling.
        if passed_audio and trending_section_y is None and cells_after_audio >= 40:
            print("Trending not found after {} cells post-audio, stopping".format(cells_after_audio))
            break

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

            stories.append((link, rank, 'top', run_time, pub_time, publication, headline))
            print("  [top/{}] {} | {} | {}".format(rank, publication, headline[:60], link[:50]))

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
            writer.writerow(['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'headline'])
        for row in stories:
            writer.writerow(row)



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


def long_press(driver, x, y, duration=1.5):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(x, y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(duration)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


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
        tap(driver, 200, 80)  # top of screen, well above any context menu
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
