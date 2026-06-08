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
import json
import fcntl
import signal
import datetime
import subprocess
import traceback
from time import sleep
from glob import glob
from appium.webdriver.common.appiumby import AppiumBy

from util.gestures import (
    tap, swipe, back_swipe, long_press_copy_link, get_article_headline,
)
from util.parsing import parse_cell_label, parse_pub_date
from util.setup import wda_needs_reinstall, clear_wda_derived_data, wipe_app_data_folder
from util.appium_session import start_driver
from util.story_rows import (
    deduplicate_rows,
    read_csv_rows,
    story_tuple_to_row,
    write_csv_rows_atomic,
)

from config import (
    device_name_and_os, device_os, udid,
    output_folder, output_file,
    COLLECT_TOP_STORIES, APP_PATH,
    MIN_STORY_CELL_HEIGHT, TAB_BAR_HEIGHT, SAFE_TAP_MARGIN, MAX_TOP_STORIES,
    MAX_TOP_HOME, MAX_READER_FAVORITES, MAX_POPULAR_STORIES, MAX_TRENDING,
    MAX_RUN_SECONDS, EXTRA_SECTION_HEADERS,
)


LOCK_PATH = '/tmp/apple_news_scraper.lock'
PENDING_PATH = '/tmp/get_stories_pending'  # signals verify_links_desktop.py to pause


class ScraperRunError(RuntimeError):
    pass


def _remove_pending_marker():
    try:
        os.unlink(PENDING_PATH)
    except OSError:
        pass


def _acquire_run_lock():
    """Return the locked file handle, or None if another scraper owns it."""
    import time as _time

    lock_fd = open(LOCK_PATH, 'w')
    deadline = _time.time() + 60
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_fd
        except BlockingIOError:
            if _time.time() >= deadline:
                print("Another instance is already running — exiting")
                lock_fd.close()
                return None
            _time.sleep(1)


def _install_timeout():
    if MAX_RUN_SECONDS > 0:
        def _timeout_handler(signum, frame):
            raise ScraperRunError(
                "Run exceeded {} seconds".format(MAX_RUN_SECONDS)
            )

        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUN_SECONDS)


def _collect_run(driver, run_time):
    print("Collecting home page stories...")
    all_stories = collect_home_page(driver, run_time)

    if COLLECT_TOP_STORIES:
        print("Navigating to Top Stories view...")
        top_stories_el = None
        for _ in range(10):
            try:
                top_stories_el = driver.find_element(
                    AppiumBy.ACCESSIBILITY_ID, 'Top Stories'
                )
                break
            except Exception:
                sleep(1)
        if not top_stories_el:
            raise ScraperRunError(
                "COLLECT_TOP_STORIES is enabled, but the Top Stories view "
                "could not be found"
            )

        tap(
            driver,
            100,
            top_stories_el.location['y'] + top_stories_el.size['height'] // 2,
        )
        sleep(4)
        home_links = {row[0] for row in all_stories if row[0]}
        all_stories.extend(
            collect_top_stories_view(driver, run_time, seen_links=home_links)
        )

    if not all_stories:
        raise ScraperRunError("No stories found")
    return all_stories


def _warn_for_missing_sections(stories):
    present = {story[2] for story in stories}
    expected = {'top': MAX_TOP_HOME}
    expected.update({
        'trending': MAX_TRENDING,
        'reader_favorites': MAX_READER_FAVORITES,
        'popular': MAX_POPULAR_STORIES,
    })
    expected.update({section: 1 for section in EXTRA_SECTION_HEADERS.values()})
    missing = [
        section
        for section, configured_max in expected.items()
        if configured_max > 0 and section not in present
    ]
    if missing:
        print(
            "Warning: run completed without these configured sections: {}".format(
                ', '.join(sorted(missing))
            )
        )


def main():
    lock_fd = None
    driver = None
    try:
        # Signal verify_links_desktop.py to finish its current link and pause.
        open(PENDING_PATH, 'w').close()
        lock_fd = _acquire_run_lock()
        if lock_fd is None:
            return 0

        # The verifier can resume once this process releases the exclusive lock.
        _remove_pending_marker()
        _install_timeout()

        print("Device: {} ({})".format(device_name_and_os, udid))

        # Terminate the app cleanly before wiping data.
        try:
            subprocess.run(
                ['xcrun', 'simctl', 'terminate', udid, 'com.apple.news'],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass

        user = os.environ['USER']
        app_data_pattern = (
            '/Users/{}/Library/Developer/CoreSimulator/Devices/{}/data/'
            'Containers/Data/Application/*/Library'
        ).format(user, udid)
        for folder in glob(app_data_pattern + '/Caches/News'):
            try:
                wipe_app_data_folder(folder)
            except Exception:
                print("Couldn't wipe {}".format(folder))
        for folder in glob(app_data_pattern.replace('/Library', '/tmp')):
            try:
                wipe_app_data_folder(folder)
            except Exception:
                pass

        os.makedirs(output_folder, exist_ok=True)

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
                clear_wda_derived_data_fn=clear_wda_derived_data,
            )
        except Exception as exc:
            raise ScraperRunError(
                "Error connecting to Appium: {}".format(exc)
            ) from exc

        sleep(8)
        run_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        all_stories = _collect_run(driver, run_time)
        _warn_for_missing_sections(all_stories)

        # Preserve the raw run before updating the canonical aggregate.
        save_json(all_stories, run_time)
        added, merged = save_stories(all_stories)
        print(
            "Saved {} story rows ({} new observations, {} duplicates merged)".format(
                len(all_stories), added, merged
            )
        )
        return 0
    except ScraperRunError as exc:
        print("Scraper failed: {}".format(exc))
        return 1
    except Exception as exc:
        print("Scraper failed unexpectedly: {}".format(exc))
        traceback.print_exc()
        return 1
    finally:
        signal.alarm(0)
        _remove_pending_marker()
        if driver is not None:
            try:
                driver.terminate_app('com.apple.news')
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()

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
        **EXTRA_SECTION_HEADERS,
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
    extra_ranks = {section: 0 for section in EXTRA_SECTION_HEADERS.values()}
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

        # Extra sections (from EXTRA_SECTION_HEADERS) are considered
        # exhausted once any subsequent header has appeared after them — i.e.,
        # they are not the last entry in the sorted boundary list.
        LOCAL_SECTIONS = tuple(EXTRA_SECTION_HEADERS.values())
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
                extra_ranks[active_section] = extra_ranks.get(active_section, 0) + 1
                rank = extra_ranks[active_section]
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

            if is_plus_story:
                print("  Apple News+ story, skipping long-press")
                seen_labels.add(label)
                link = ''
            else:
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

            article_headline, article_publication = ('', '') if is_plus_story else get_article_headline(driver, x_c, y_c, window_height)
            if not publication:
                publication = article_publication

            stories.append((link, rank, section, run_time, pub_time, publication, author, headline, article_headline, is_plus_story))
            print("  [{}/{}]{}".format(section, rank, ' (Apple News+)' if is_plus_story else (' (no link)' if not link else '')))
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
            if no_progress_streak >= 40:
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

            if 'Apple News Plus' in (s.get('label') or ''):
                rank += 1
                print("  [top/{}] (Apple News+, no link available)".format(rank))
                continue

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

            stories.append((link, rank, 'top', run_time, pub_time, publication, author, headline, article_headline, False))
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
    '''Atomically merge new observations into the canonical stories CSV.'''
    existing = read_csv_rows(output_file)
    incoming = [story_tuple_to_row(story) for story in stories]
    clean_existing, _ = deduplicate_rows(existing)
    merged_rows, duplicates_removed = deduplicate_rows(existing + incoming)
    write_csv_rows_atomic(output_file, merged_rows)
    return len(merged_rows) - len(clean_existing), duplicates_removed


def save_json(stories, run_time):
    '''Write a JSON file for this run to data_output/json/<run_time>.json.'''
    json_folder = os.path.join(output_folder, 'json')
    os.makedirs(json_folder, exist_ok=True)
    filename = run_time.replace(':', '-').replace(' ', '_') + '.json'
    path = os.path.join(json_folder, filename)

    keys = ['link', 'rank', 'section', 'run_time', 'pub_time', 'publication', 'author', 'headline', 'article_headline']
    records = []
    for row in stories:
        d = dict(zip(keys, row))
        if len(row) > 9 and row[9]:
            d['link_status'] = 'P'
        records.append(d)

    payload = {
        'run_time': run_time,
        'story_count': len(records),
        'stories': records,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print("JSON saved to {}".format(path))



if __name__ == '__main__':
    raise SystemExit(main())
