'''
verify_links_desktop.py

Desktop link verification using Safari + macOS News.app.

For each unverified apple.news link:
  1. Open with the system default handler (`open link`).
  2. Detect whether Safari or News.app came to the foreground.
     - Safari: the link resolved to a public web article.
       Save the URL as resolved_link, then open in News via File > Share > Open in News.
     - News: the link opened directly in a new News.app window (News+ / app-only).
       Use curl to attempt URL resolution for resolved_link.
     - Neither / no new window: link is broken — mark M.
  3. In News.app: check for the "Sections" button (channel page → M), then compare
     the visible article title to the stored headline.
  4. Close the new News.app window after the decision.

Manages two columns in stories.csv:
  link_status   M = missing / removed, U = unverified, V = verified
  resolved_link full article URL discovered via redirect (e.g. vogue.com/…)

Usage:
    python3 verify_links_desktop.py                          # dry-run, process once
    python3 verify_links_desktop.py --confirm                # write changes to CSV
    python3 verify_links_desktop.py --confirm --duration-hours 48  # run for 48h, picking up new links
    python3 verify_links_desktop.py --limit N                # process at most N links per pass
    python3 verify_links_desktop.py --init                   # add/populate columns and exit
    python3 verify_links_desktop.py --threshold X            # similarity cutoff (default 0.45)
    python3 verify_links_desktop.py --debug-news             # dump News.app window tree and exit

Coordination with get_stories.py:
    Both scripts share /tmp/apple_news_scraper.lock.  verify_links_desktop.py acquires a
    shared (read) lock before each CSV read/write, so it automatically waits while
    get_stories.py holds the exclusive lock during a scrape run.
'''

import csv
import fcntl
import os
import random
import re
import sys
import time
import shutil
import difflib
import argparse
import subprocess
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, '..', 'docs', 'data', 'stories.csv')
BACKUP_PATH = CSV_PATH + '.verify_bak'
LOCK_PATH = '/tmp/apple_news_scraper.lock'  # shared with get_stories.py
PENDING_PATH = '/tmp/get_stories_pending'  # written by get_stories.py when it wants to run
IDLE_POLL_SECS = 60  # how long to sleep when no unverified links remain

MATCH_THRESHOLD = 0.45
OPEN_WAIT_SECS  = 6.0   # wait after `open -a Safari` for redirect to settle
NEWS_LOAD_SECS  = 4.0   # wait after Share → Open in News / open -a News
MIN_SLEEP_SECS  = 5     # minimum pause between links (rate-limit protection)

STATUS_MISSING    = 'M'
STATUS_UNVERIFIED = 'U'
STATUS_VERIFIED   = 'V'

# Page-text phrases that appear on Apple's "open in the app" interstitial or channel pages.
APPLE_NEWS_ONLY_MARKERS = [
    'only available in apple news',  # covers both article and channel interstitials
    'this channel is only available',
    'open in apple news',
    'get apple news',
]

# Markers indicating an Apple News+ paywall inside News.app → treat as verified.
PAYWALL_MARKERS = {
    'Your trial also includes',
    'unlock 500+ publications',
    'Enjoy stories from 500+',
    'Unlock this story',
    'One month free',
}

UI_CHROME = {
    'people also read',
    'news+ recommended reads',
    'recommended reads',
    'top stories',
    'trending stories',
    "editor's picks",
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


def best_headline(row):
    h = (row.get('article_headline') or '').strip()
    if h and len(h) > 10:
        return h
    return (row.get('headline') or '').strip()


def strip_title_prefix(title):
    '''Strip a short "PROFILE — " prefix from a Safari page title, if present.'''
    for sep in (' \u2014 ', ' \u2013 ', ' - '):   # em dash, en dash, hyphen
        idx = title.find(sep)
        if idx != -1:
            prefix = title[:idx]
            # Only strip if the prefix looks like a short profile name (< 30 chars,
            # no sentence punctuation), not a real mid-title separator.
            if len(prefix) < 30 and '.' not in prefix and ',' not in prefix:
                return title[idx + len(sep):]
    return title


def extract_pub_from_title(title):
    '''Extract publication name from a News.app window title "Headline - Publication" format.
    Returns '' if no clean suffix is found.'''
    for sep in (' \u2014 ', ' \u2013 ', ' - '):
        idx = title.rfind(sep)  # rfind: separator before the publication suffix
        if idx != -1:
            pub = title[idx + len(sep):].strip()
            # Sanity check: publication names are short and don't end in punctuation
            if pub and len(pub) <= 80 and not pub[-1] in '.?!':
                return pub
    return ''


# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------

def run_applescript(script, timeout=20):
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def check_accessibility():
    '''Return True if this process has Accessibility permission (probed via Finder).'''
    _, err, code = run_applescript('''
tell application "System Events"
    tell process "Finder"
        return count of windows
    end tell
end tell''', timeout=10)
    if code != 0:
        if 'assistive access' in err.lower() or 'not allowed' in err.lower():
            return False
    return True


def get_front_app():
    '''Return the name of the currently frontmost application.'''
    out, _, code = run_applescript('''
tell application "System Events"
    return name of first process whose frontmost is true
end tell''')
    return out.strip() if code == 0 else ''


# ---------------------------------------------------------------------------
# URL resolution (no browser required)
# ---------------------------------------------------------------------------

def resolve_url_with_curl(link):
    '''Follow the apple.news redirect chain and return the final non-Apple URL, or \'\'.'''
    try:
        result = subprocess.run(
            ['curl', '-s', '-L', '-o', '/dev/null', '-w', '%{url_effective}',
             '--max-time', '10', '--max-redirs', '10', link],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            hostname = (urlparse(url).hostname or '').lower()
            if not (hostname.endswith('apple.news') or
                    hostname.endswith('apple.com')):
                return url
    except Exception:
        pass
    return ''


# ---------------------------------------------------------------------------
# Safari interaction
# ---------------------------------------------------------------------------

def get_safari_url():
    '''Return the current URL from Safari, trying document URL, tab URL, and JS href in order.'''
    out, _, code = run_applescript('''
tell application "Safari"
    if (count of documents) > 0 then
        try
            set u to URL of document 1
            if u is not "" then return u
        end try
        try
            if (count of windows) > 0 and (count of tabs of front window) > 0 then
                set u to URL of current tab of front window
                if u is not "" then return u
            end if
        end try
        try
            return (do JavaScript "window.location.href" in current tab of front window)
        end try
    end if
    return ""
end tell''', timeout=15)
    url = out.strip() if code == 0 else ''
    return url if url not in ('about:blank', 'undefined', '') else ''


def get_safari_title():
    '''Return the page title from Safari's front document.'''
    out, _, code = run_applescript('''
tell application "Safari"
    if (count of documents) > 0 then
        return name of document 1
    end if
    return ""
end tell''', timeout=10)
    return out.strip() if code == 0 else ''


def get_safari_page_text():
    out, _, code = run_applescript('''
tell application "Safari"
    if (count of windows) > 0 then
        return (do JavaScript "document.body ? document.body.innerText.substring(0, 2000) : document.title" in current tab of front window)
    end if
    return ""
end tell''', timeout=15)
    return out.strip() if code == 0 else ''


def is_apple_news_only(page_text):
    '''Return True if the page is a dead-end "open in app" interstitial (not a News+ article page).'''
    pt_lower = page_text.lower()
    return any(m in pt_lower for m in APPLE_NEWS_ONLY_MARKERS)


def click_safari_open_button():
    '''Click the "Open" / "Open in News" button on an apple.news page. Returns True if clicked.'''
    out, _, code = run_applescript('''
tell application "Safari"
    if (count of windows) > 0 then
        set res to (do JavaScript "
            var els = document.querySelectorAll('a, button');
            for (var i = 0; i < els.length; i++) {
                var t = els[i].textContent.trim();
                if (t === 'Open' || t === 'Open in News' || t === 'Open in Apple News') {
                    els[i].click();
                    'clicked';
                }
            }
            'not found';
        " in current tab of front window)
        return res
    end if
    return "no window"
end tell''', timeout=10)
    return code == 0 and 'clicked' in out


def open_in_news(link):
    '''Open the apple.news link directly in News.app.'''
    result = subprocess.run(['open', '-a', 'News', link], capture_output=True)
    if result.returncode == 0:
        print('  Opened via open -a News')
        return True
    return False


def close_safari_window():
    '''Close the current Safari tab (or window if it is the only tab).'''
    run_applescript('''
tell application "Safari"
    if (count of windows) > 0 then
        set w to front window
        if (count of tabs of w) > 1 then
            close current tab of w
        else
            close w
        end if
    end if
end tell''', timeout=10)
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# News.app helpers
# ---------------------------------------------------------------------------

def count_news_windows():
    '''Return the number of windows currently open in News.app.'''
    out, _, code = run_applescript('''
tell application "System Events"
    tell process "News"
        return count of windows
    end tell
end tell''', timeout=10)
    try:
        return int(out) if code == 0 else 0
    except ValueError:
        return 0


def has_sections_button():
    '''
    Return True if the front News.app window has a "Sections" button,
    indicating a channel/publication page rather than a specific article.
    Searches buttons one and two levels deep from window 1.
    '''
    out, _, code = run_applescript('''
tell application "System Events"
    tell process "News"
        try
            set w to window 1
            repeat with btn in every button of w
                set n to name of btn
                set d to description of btn
                if n is "Sections" or d is "Sections" then return "true"
            end repeat
            repeat with el in every UI element of w
                try
                    repeat with btn in every button of el
                        set n to name of btn
                        set d to description of btn
                        if n is "Sections" or d is "Sections" then return "true"
                    end repeat
                end try
            end repeat
        end try
        return "false"
    end tell
end tell''', timeout=15)
    return code == 0 and out == 'true'


def close_news_front_window():
    '''Close the front News.app window with Cmd+W.'''
    run_applescript('''
tell application "System Events"
    tell process "News"
        if (count of windows) > 0 then
            keystroke "w" using command down
        end if
    end tell
end tell''', timeout=10)
    time.sleep(0.4)


def get_news_article_texts():
    '''Return (y, text) pairs from the front News.app window, sorted by y position.'''
    texts = []
    seen = set()

    def add(y, t):
        t = (t or '').strip()
        if t and t not in seen and len(t) >= 5:
            seen.add(t)
            texts.append((y, t))

    out, _, code = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to ""
        repeat with i from 1 to count of windows
            try
                set t to title of window i
                if t is not "" then set output to output & (i * 10) & "|" & t & linefeed
            end try
        end repeat
        try
            set w to window 1
            repeat with el in every UI element of w
                try
                    set pos to position of el
                    set py to item 2 of pos
                    try
                        set d to description of el
                        if d is not "" then set output to output & py & "|" & d & linefeed
                    end try
                    try
                        set v to value of el
                        if v is not "" and v is not d then set output to output & py & "|" & v & linefeed
                    end try
                    repeat with el2 in every UI element of el
                        try
                            set pos2 to position of el2
                            set py2 to item 2 of pos2
                            try
                                set d2 to description of el2
                                if d2 is not "" then set output to output & py2 & "|" & d2 & linefeed
                            end try
                            try
                                set v2 to value of el2
                                if v2 is not "" and v2 is not d2 then set output to output & py2 & "|" & v2 & linefeed
                            end try
                        end try
                    end repeat
                end try
            end repeat
            repeat with t in every static text of w
                try
                    set v to value of t
                    if v is not "" then
                        set pos to position of t
                        set output to output & (item 2 of pos) & "|" & v & linefeed
                    end if
                end try
            end repeat
        end try
        return output
    end tell
end tell''', timeout=40)

    if code == 0:
        for line in out.splitlines():
            if '|' in line:
                try:
                    y_str, text = line.split('|', 1)
                    add(int(y_str.strip()), text.strip())
                except (ValueError, IndexError):
                    pass

    return sorted(texts, key=lambda t: t[0])


def is_paywall_screen(texts):
    for _y, text in texts:
        if any(marker in text for marker in PAYWALL_MARKERS):
            return True
    return False


def best_matching_text(headline, texts):
    best_sim = 0.0
    best_text = ''
    for _y, text in texts:
        if normalize(text) in UI_CHROME:
            continue
        s = similarity(headline, text)
        if s > best_sim:
            best_sim = s
            best_text = text
    return best_sim, best_text


# ---------------------------------------------------------------------------
# Debug helper
# ---------------------------------------------------------------------------

def debug_news_windows():
    '''Dump the full window/element tree of News.app for diagnosis.'''
    out, err, code = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to "=== News.app windows ===" & linefeed
        repeat with i from 1 to count of windows
            try
                set w to window i
                set t to title of w
                set r to role of w
                set output to output & "[" & i & "] role=" & r & " title=" & t & linefeed
                repeat with el in every UI element of w
                    try
                        set d to description of el
                        set r2 to role of el
                        set pos to position of el
                        set sz to size of el
                        set output to output & "  el role=" & r2 & " desc=" & d & " pos=" & (item 1 of pos) & "," & (item 2 of pos) & " sz=" & (item 1 of sz) & "x" & (item 2 of sz) & linefeed
                    end try
                end repeat
            end try
        end repeat
        return output
    end tell
end tell''', timeout=30)
    print(out or err)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def save_csv(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ensure_columns(fieldnames, rows):
    for col in ('link_status', 'resolved_link', 'web_headline'):
        if col not in fieldnames:
            fieldnames = list(fieldnames) + [col]
    for row in rows:
        if not row.get('link_status'):
            link = (row.get('link') or '').strip()
            row['link_status'] = STATUS_MISSING if not link else STATUS_UNVERIFIED
        for col in ('resolved_link', 'web_headline'):
            if col not in row:
                row[col] = ''
    return fieldnames, rows


def save_result(link, result, backed_up):
    '''Under a shared lock: re-read CSV, apply one link's result, write back.

    Re-reading inside the lock guarantees we never clobber rows that get_stories.py
    appended between our last read and this write.  Returns updated backed_up flag.
    '''
    lock_fd = open(LOCK_PATH, 'a')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)  # blocks while get_stories.py holds EX lock
        fn, rows = load_csv(CSV_PATH)
        fn, rows = ensure_columns(fn, rows)
        new_status   = result['status']
        resolved     = result['resolved_link']
        web_headline = result.get('web_headline', '')
        new_pub      = result.get('publication', '')
        for row in rows:
            if row.get('link') == link and row.get('link_status') == STATUS_UNVERIFIED:
                row['link_status']   = new_status
                row['resolved_link'] = resolved
                if web_headline:
                    row['web_headline'] = web_headline
                if new_pub:
                    row['publication'] = new_pub
                if new_status == STATUS_MISSING:
                    row['link'] = ''
        if not backed_up:
            shutil.copy2(CSV_PATH, BACKUP_PATH)
        save_csv(CSV_PATH, fn, rows)
        return True
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def print_status_counts(rows):
    counts = {}
    for row in rows:
        s = row.get('link_status', '')
        counts[s] = counts.get(s, 0) + 1
    labels = {'M': 'missing', 'U': 'unverified', 'V': 'verified'}
    for s in sorted(counts):
        print('  {} ({}): {}'.format(s, labels.get(s, s), counts[s]))


# ---------------------------------------------------------------------------
# Priority yield to get_stories.py
# ---------------------------------------------------------------------------

def _yield_to_get_stories():
    '''If get_stories.py has signalled that it wants to run, wait until it finishes.

    get_stories.py writes PENDING_PATH before acquiring the exclusive lock, then
    deletes it once the lock is held.  We:
      1. Spin-wait (with sleep) until the pending file is gone — i.e. get_stories
         has acquired the lock.
      2. Then block on LOCK_SH until get_stories releases the exclusive lock.
    Step 2 is a no-op when get_stories has already finished by the time we check.
    '''
    if not os.path.exists(PENDING_PATH):
        return
    print('[{}] get_stories.py is pending — finishing current link then pausing...'.format(
        time.strftime('%H:%M:%S')))
    # Wait until get_stories holds the exclusive lock (pending file deleted).
    while os.path.exists(PENDING_PATH):
        time.sleep(1)
    # Block until the exclusive lock is released (get_stories finished).
    fd = open(LOCK_PATH, 'r')
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()
    print('[{}] get_stories.py finished — resuming'.format(time.strftime('%H:%M:%S')))


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------

def adaptive_sleep(links_done, total_links, end_time):
    '''Pace remaining links evenly to end_time with random jitter. No-op if end_time is None.'''
    if end_time is None:
        return
    links_remaining = total_links - links_done
    secs_remaining = end_time - time.time()
    if links_remaining <= 0 or secs_remaining <= 0:
        return
    target = secs_remaining / links_remaining
    sleep_secs = max(MIN_SLEEP_SECS, random.uniform(target * 0.5, target * 1.5))
    print('  Sleeping {:.0f}s (target {:.0f}s | {:.1f}h left for {} links)'.format(
        sleep_secs, target, secs_remaining / 3600, links_remaining))
    time.sleep(sleep_secs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Verify apple.news links via Safari + macOS News.app')
    parser.add_argument('--confirm', action='store_true',
                        help='Write changes to CSV (default: dry-run)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Max unique links to verify this batch (0 = all)')
    parser.add_argument('--threshold', type=float, default=MATCH_THRESHOLD,
                        help='Min similarity to mark verified (default: {})'.format(
                            MATCH_THRESHOLD))
    parser.add_argument('--init', action='store_true',
                        help='Add/populate link_status and resolved_link columns and exit')
    parser.add_argument('--debug-news', action='store_true',
                        help='Dump the News.app accessibility tree and exit')
    parser.add_argument('--duration-hours', type=float, default=None,
                        help='Spread links evenly across this many hours with random sleep between each')
    args = parser.parse_args()

    if not check_accessibility():
        print('ERROR: Accessibility (assistive access) permission is required.')
        print('Grant it: System Settings → Privacy & Security → Accessibility')
        print('  → click the + button and add Terminal (or your Python interpreter).')
        print('Also ensure: System Settings → Privacy & Security → Automation')
        print('  → Terminal → enable both Safari and News.')
        sys.exit(1)

    if args.debug_news:
        debug_news_windows()
        return

    fieldnames, rows = load_csv(CSV_PATH)
    fieldnames, rows = ensure_columns(fieldnames, rows)

    if args.init:
        print_status_counts(rows)
        if args.confirm:
            print('Backing up {} -> {}'.format(CSV_PATH, BACKUP_PATH))
            shutil.copy2(CSV_PATH, BACKUP_PATH)
            save_csv(CSV_PATH, fieldnames, rows)
            print('Columns initialized.')
        else:
            print('Dry-run — re-run with --confirm to write changes.')
        return

    end_time  = time.time() + args.duration_hours * 3600 if args.duration_hours else None
    backed_up = False

    while True:
        if end_time and time.time() >= end_time:
            print('Time budget exhausted.')
            break

        # Re-read CSV each iteration (picks up new links from get_stories.py).
        # Wait here if get_stories.py is currently running (holds the exclusive lock).
        lock_fd = open(LOCK_PATH, 'a')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            fieldnames, rows = load_csv(CSV_PATH)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        fieldnames, rows = ensure_columns(fieldnames, rows)

        link_to_indices = {}
        for i, row in enumerate(rows):
            if row.get('link_status') == STATUS_UNVERIFIED:
                lnk = (row.get('link') or '').strip()
                if lnk:
                    link_to_indices.setdefault(lnk, []).append(i)

        unique_links = list(link_to_indices.items())
        random.shuffle(unique_links)

        if not unique_links:
            if not end_time:
                print('Nothing to verify.')
                break
            print('[{}] No unverified links — waiting {}s for new stories...'.format(
                time.strftime('%H:%M:%S'), IDLE_POLL_SECS))
            time.sleep(IDLE_POLL_SECS)
            continue

        if args.limit > 0:
            unique_links = unique_links[:args.limit]

        print('[{}] {} unverified links | {}'.format(
            time.strftime('%H:%M:%S'), len(unique_links),
            'WRITE' if args.confirm else 'DRY-RUN'))
        print()

        interrupted = False
        try:
            for idx, (link, row_indices) in enumerate(unique_links, 1):
                if end_time and time.time() >= end_time:
                    print('Time budget exhausted.')
                    interrupted = True
                    break

                _yield_to_get_stories()

                headline    = max((best_headline(rows[i]) for i in row_indices), key=len)
                publication = (rows[row_indices[0]].get('publication') or '').strip()

                print('[{}/{}] {}'.format(idx, len(unique_links), link))
                print('  Headline:  {!r}'.format(headline[:80]))
                if publication:
                    print('  Source:    {!r}'.format(publication))

                result       = None
                resolved_link = ''
                web_headline  = ''

                news_windows_before = count_news_windows()
                subprocess.run(['open', '-a', 'Safari', link], check=False)
                time.sleep(OPEN_WAIT_SECS)

                print('  Front app: {}'.format(get_front_app() or '(unknown)'))

                safari_url   = get_safari_url()
                safari_title = get_safari_title()
                page_text    = get_safari_page_text()
                web_headline = strip_title_prefix(safari_title) if safari_title else ''
                print('  Safari URL:   {}'.format(safari_url[:100] if safari_url else '(none)'))
                if web_headline:
                    print('  Web headline: {}'.format(web_headline[:80]))

                if is_apple_news_only(page_text + ' ' + safari_title):
                    print('  -> MISSING (Apple News only / interstitial page)')
                    close_safari_window()
                    result = {'status': STATUS_MISSING, 'resolved_link': '', 'web_headline': ''}

                if result is None:
                    safari_hostname = (urlparse(safari_url).hostname or '').lower()
                    if safari_hostname.endswith('apple.news'):
                        clicked = click_safari_open_button()
                        if clicked:
                            print('  Opened via "Open" button on apple.news page')
                        close_safari_window()
                        if not clicked:
                            open_in_news(link)
                    else:
                        resolved_link = safari_url
                        if resolved_link:
                            print('  Resolved:  {}'.format(resolved_link[:100]))
                        close_safari_window()
                        open_in_news(link)

                    time.sleep(NEWS_LOAD_SECS)
                    news_windows_after = count_news_windows()
                    print('  News windows: {} -> {}'.format(news_windows_before, news_windows_after))

                    if news_windows_after <= news_windows_before:
                        print('  No new News window — leaving unverified')
                        result = {'status': STATUS_UNVERIFIED, 'resolved_link': resolved_link,
                                  'web_headline': web_headline}
                    elif has_sections_button():
                        print('  -> MISSING (channel page — Sections button found)')
                        close_news_front_window()
                        result = {'status': STATUS_MISSING, 'resolved_link': '', 'web_headline': ''}
                    else:
                        texts = get_news_article_texts()
                        best_sim, best_text = best_matching_text(headline, texts)
                        if web_headline:
                            wsim, wtext = best_matching_text(web_headline, texts)
                            if wsim > best_sim:
                                best_sim, best_text = wsim, wtext
                        print('  Texts found: {} | Best: {!r} (sim={:.2f})'.format(
                            len(texts), (best_text or '(nothing)')[:60], best_sim))

                        # Extract actual publication from News.app window title (y=10).
                        new_pub = ''
                        for y, t in texts:
                            if y <= 20:
                                new_pub = extract_pub_from_title(t)
                                if new_pub:
                                    print('  News pub: {!r}'.format(new_pub))
                                    break

                        # Publication mismatch: the link redirected to a different source.
                        # Overrides headline similarity — wrong source is always a bad link.
                        pub_mismatch = False
                        if new_pub and publication and publication not in ('Apple News Plus',):
                            psim = similarity(publication, new_pub)
                            if psim < 0.4:
                                pub_mismatch = True
                                print('  Publication mismatch: expected {!r}, got {!r} (sim={:.2f})'.format(
                                    publication, new_pub, psim))

                        if pub_mismatch:
                            print('  -> MISSING (publication mismatch)')
                            result = {'status': STATUS_MISSING, 'resolved_link': '', 'web_headline': ''}
                        elif best_sim >= args.threshold:
                            print('  -> VERIFIED')
                            result = {'status': STATUS_VERIFIED, 'resolved_link': resolved_link,
                                      'web_headline': web_headline, 'publication': new_pub}
                        elif is_paywall_screen(texts):
                            print('  -> VERIFIED (paywall/plus article)')
                            result = {'status': STATUS_VERIFIED, 'resolved_link': resolved_link,
                                      'web_headline': web_headline, 'publication': new_pub}
                        elif not texts:
                            print('  -> leaving unverified (nothing readable in News.app)')
                            result = {'status': STATUS_UNVERIFIED, 'resolved_link': resolved_link,
                                      'web_headline': web_headline}
                        else:
                            print('  -> MISSING (sim {:.2f} < {:.2f})'.format(best_sim, args.threshold))
                            result = {'status': STATUS_MISSING, 'resolved_link': '', 'web_headline': ''}

                        close_news_front_window()

                if args.confirm:
                    backed_up = save_result(link, result, backed_up)
                else:
                    print('  [dry-run, not saved]')

                adaptive_sleep(idx, len(unique_links), end_time)

        except KeyboardInterrupt:
            print('\nInterrupted.')
            interrupted = True

        if not end_time or interrupted:
            break

    _, final_rows = load_csv(CSV_PATH)
    print()
    print_status_counts(final_rows)


if __name__ == '__main__':
    main()
