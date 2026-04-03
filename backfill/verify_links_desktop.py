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
    python3 verify_links_desktop.py              # dry-run
    python3 verify_links_desktop.py --confirm    # write changes to CSV
    python3 verify_links_desktop.py --limit N    # process at most N unique links
    python3 verify_links_desktop.py --init       # add/populate new columns and exit
    python3 verify_links_desktop.py --threshold X  # similarity cutoff (default 0.45)
    python3 verify_links_desktop.py --debug-news   # dump News.app window tree and exit
'''

import csv
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
CSV_PATH = os.path.join(HERE, '..', 'data_output', 'stories.csv')
BACKUP_PATH = CSV_PATH + '.verify_bak'

MATCH_THRESHOLD = 0.45
OPEN_WAIT_SECS  = 6.0   # wait after `open -a Safari` for redirect to settle
NEWS_LOAD_SECS  = 4.0   # wait after Share → Open in News / open -a News

STATUS_MISSING    = 'M'
STATUS_UNVERIFIED = 'U'
STATUS_VERIFIED   = 'V'

# Page-text phrases that appear on Apple's "open in the app" interstitial.
APPLE_NEWS_ONLY_MARKERS = [
    'only available in apple news',
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
    '''
    Remove the Apple News profile prefix from a Safari page title.
    Safari shows titles as "PROFILE — Article Headline", e.g. "UIC — Some Story".
    Strips everything up to and including the first em dash separator.
    '''
    for sep in (' \u2014 ', ' \u2013 ', ' - '):   # em dash, en dash, hyphen
        idx = title.find(sep)
        if idx != -1:
            prefix = title[:idx]
            # Only strip if the prefix looks like a short profile name (< 30 chars,
            # no sentence punctuation), not a real mid-title separator.
            if len(prefix) < 30 and '.' not in prefix and ',' not in prefix:
                return title[idx + len(sep):]
    return title


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
    '''
    Verify that the running process has Accessibility (assistive access) permission
    by trying an operation that actually requires it: reading a window count from
    a running process via System Events.
    Returns True if access is granted, False otherwise.
    '''
    # Finder is always running — use it as the accessibility probe
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
    '''
    Follow the apple.news redirect chain with curl and return the final URL.
    Returns '' if it stays on an apple domain or resolution fails.
    '''
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
    '''
    Return the current URL from Safari using multiple fallback methods.
    apple.news redirects can leave the tab in various states (full article URL,
    apple-news:// redirect that blanks the tab, or an interstitial page).
    Requires Terminal to have Automation access to Safari in System Settings.
    '''
    candidates = []

    # Method 1: URL of document 1
    out, _, code = run_applescript('''
tell application "Safari"
    if (count of documents) > 0 then
        return URL of document 1
    end if
    return ""
end tell''', timeout=10)
    if code == 0 and out.strip():
        candidates.append(out.strip())

    # Method 2: URL of current tab
    out2, _, code2 = run_applescript('''
tell application "Safari"
    if (count of windows) > 0 then
        if (count of tabs of front window) > 0 then
            return URL of current tab of front window
        end if
    end if
    return ""
end tell''', timeout=10)
    if code2 == 0 and out2.strip():
        candidates.append(out2.strip())

    # Method 3: JavaScript href (survives some redirect states)
    out3, _, code3 = run_applescript('''
tell application "Safari"
    if (count of windows) > 0 then
        try
            return (do JavaScript "window.location.href" in current tab of front window)
        end try
    end if
    return ""
end tell''', timeout=10)
    if code3 == 0 and out3.strip():
        candidates.append(out3.strip())

    for url in candidates:
        if url and url not in ('about:blank', 'undefined', ''):
            return url
    return ''


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


def is_apple_news_only(url, page_text):
    hostname = (urlparse(url).hostname or '').lower()
    if hostname.endswith('apple.news') or hostname in ('apple.com', 'news.apple.com'):
        return True
    pt_lower = page_text.lower()
    return any(m in pt_lower for m in APPLE_NEWS_ONLY_MARKERS)


def open_in_news_from_safari(original_link):
    '''
    Open the current Safari page in News.app.
    First tries File > Share > Open in News in Safari.
    Always falls back to opening the original apple.news link directly in News.app.
    Returns True if either path appeared to succeed.
    '''
    out, _, code = run_applescript('''
tell application "System Events"
    tell process "Safari"
        tell menu bar 1
            tell menu bar item "File"
                tell menu "File"
                    tell menu item "Share"
                        tell menu "Share"
                            if exists menu item "Open in News" then
                                click menu item "Open in News"
                                return "clicked"
                            end if
                        end tell
                    end tell
                end tell
            end tell
        end tell
    end tell
end tell''', timeout=15)

    if code == 0 and out == 'clicked':
        print('  Opened via File > Share > Open in News')
        return True

    # Fallback: open the original apple.news link directly in News.app
    result = subprocess.run(
        ['open', '-a', 'News', original_link],
        capture_output=True,
    )
    if result.returncode == 0:
        print('  Opened via open -a News (share menu unavailable)')
        return True

    return False


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
    '''
    Return (y, text) pairs from the front News.app window.

    Reads:
      1. The title of every open News window (AXTitle).
      2. Descriptions and values of UI elements 2 levels deep from window 1.
      3. Static text elements from window 1 (direct children only).

    Going 2 levels deep is slower than a flat search but necessary because
    the article title is often buried inside a toolbar group or scroll view.
    '''
    texts = []
    seen = set()

    def add(y, t):
        t = (t or '').strip()
        if t and t not in seen and len(t) >= 5:
            seen.add(t)
            texts.append((y, t))

    # 1. Titles of all windows — the front window (index 1) gets priority via y=10
    out, _, code = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to ""
        repeat with i from 1 to count of windows
            try
                set t to title of window i
                if t is not "" then
                    set output to output & (i * 10) & "|" & t & linefeed
                end if
            end try
        end repeat
        return output
    end tell
end tell''', timeout=15)
    if code == 0:
        for line in out.splitlines():
            if '|' in line:
                try:
                    y_str, text = line.split('|', 1)
                    add(int(y_str.strip()), text.strip())
                except (ValueError, IndexError):
                    pass

    # 2. Two-level element walk on window 1 — descriptions and values
    out2, _, code2 = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to ""
        try
            set w to window 1
            repeat with el in every UI element of w
                try
                    set d to description of el
                    set pos to position of el
                    set py to item 2 of pos
                    if d is not "" then
                        set output to output & py & "|" & d & linefeed
                    end if
                    try
                        set v to value of el
                        if v is not "" and v is not d then
                            set output to output & py & "|" & v & linefeed
                        end if
                    end try
                    repeat with el2 in every UI element of el
                        try
                            set d2 to description of el2
                            set pos2 to position of el2
                            set py2 to item 2 of pos2
                            if d2 is not "" then
                                set output to output & py2 & "|" & d2 & linefeed
                            end if
                            try
                                set v2 to value of el2
                                if v2 is not "" and v2 is not d2 then
                                    set output to output & py2 & "|" & v2 & linefeed
                                end if
                            end try
                        end try
                    end repeat
                end try
            end repeat
        end try
        return output
    end tell
end tell''', timeout=25)
    if code2 == 0:
        for line in out2.splitlines():
            if '|' in line:
                try:
                    y_str, text = line.split('|', 1)
                    add(int(y_str.strip()), text.strip())
                except (ValueError, IndexError):
                    pass

    # 3. Static text elements from window 1 (catches any text the above missed)
    out3, _, code3 = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to ""
        try
            repeat with t in every static text of window 1
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
end tell''', timeout=15)
    if code3 == 0:
        for line in out3.splitlines():
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


def print_status_counts(rows):
    counts = {}
    for row in rows:
        s = row.get('link_status', '')
        counts[s] = counts.get(s, 0) + 1
    labels = {'M': 'missing', 'U': 'unverified', 'V': 'verified'}
    for s in sorted(counts):
        print('  {} ({}): {}'.format(s, labels.get(s, s), counts[s]))


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

    # Collect unverified links
    link_to_indices = {}
    for i, row in enumerate(rows):
        if row.get('link_status') == STATUS_UNVERIFIED:
            link = (row.get('link') or '').strip()
            if link:
                link_to_indices.setdefault(link, []).append(i)

    unique_links = list(link_to_indices.items())
    random.shuffle(unique_links)
    print('Unverified links: {}'.format(len(unique_links)))

    if not unique_links:
        print('Nothing to verify.')
        return

    if args.limit > 0:
        unique_links = unique_links[:args.limit]
        print('Limiting to {} links this batch'.format(len(unique_links)))

    print('Mode: {}'.format('WRITE' if args.confirm else 'DRY-RUN'))
    print()

    results = {}  # link -> {'status': V|M|U, 'resolved_link': str}

    try:
        for idx, (link, row_indices) in enumerate(unique_links, 1):
            headline = max(
                (best_headline(rows[i]) for i in row_indices),
                key=len,
            )
            publication = (rows[row_indices[0]].get('publication') or '').strip()

            print('[{}/{}] {}'.format(idx, len(unique_links), link))
            print('  Headline:  {!r}'.format(headline[:80]))
            if publication:
                print('  Source:    {!r}'.format(publication))
            print('  Affects {} row(s)'.format(len(row_indices)))

            # Count windows before opening so we can detect new ones
            news_windows_before = count_news_windows()

            # Force Safari to open the link (apple.news interstitial loads there)
            subprocess.run(['open', '-a', 'Safari', link], check=False)
            time.sleep(OPEN_WAIT_SECS)

            front_app = get_front_app()
            print('  Front app: {}'.format(front_app or '(unknown)'))

            # --- Detect "Apple News only" interstitial in Safari ---
            safari_url   = get_safari_url()
            safari_title = get_safari_title()
            page_text    = get_safari_page_text()
            web_headline = strip_title_prefix(safari_title) if safari_title else ''
            print('  Safari URL:   {}'.format(safari_url[:100] if safari_url else '(none)'))
            if web_headline:
                print('  Web headline: {}'.format(web_headline[:80]))

            # Also pass the page title into the "Apple News only" check —
            # the title survives the apple-news:// redirect even when the URL doesn't.
            if is_apple_news_only(safari_url, page_text + ' ' + safari_title):
                print('  -> MISSING (Apple News only / interstitial page)')
                results[link] = {'status': STATUS_MISSING, 'resolved_link': '',
                                 'web_headline': ''}
                continue

            # --- Determine resolved_link ---
            # Prefer the Safari URL (full article page); fall back to curl.
            if safari_url and not (urlparse(safari_url).hostname or '').endswith('apple.news'):
                resolved_link = safari_url
            else:
                resolved_link = resolve_url_with_curl(link)
            if resolved_link:
                print('  Resolved:  {}'.format(resolved_link[:100]))

            # --- Open in News.app (share menu or direct fallback) ---
            open_in_news_from_safari(link)
            time.sleep(NEWS_LOAD_SECS)

            # Check whether a new News.app window actually opened
            news_windows_after = count_news_windows()
            print('  News windows: {} -> {}'.format(
                news_windows_before, news_windows_after))

            if news_windows_after <= news_windows_before:
                print('  No new News window detected — leaving unverified')
                results[link] = {'status': STATUS_UNVERIFIED,
                                 'resolved_link': resolved_link,
                                 'web_headline': web_headline}
                continue

            # Check for channel page (Sections button) before reading full text
            if has_sections_button():
                print('  -> MISSING (channel page — Sections button found)')
                results[link] = {'status': STATUS_MISSING, 'resolved_link': '',
                                 'web_headline': ''}
                close_news_front_window()
                continue

            texts = get_news_article_texts()
            best_sim, best_text = best_matching_text(headline, texts)

            print('  Texts found: {}'.format(len(texts)))
            print('  Best match: {!r} (sim={:.2f})'.format(
                (best_text or '(nothing)')[:80], best_sim))

            if best_sim >= args.threshold:
                print('  -> VERIFIED')
                results[link] = {'status': STATUS_VERIFIED,
                                 'resolved_link': resolved_link,
                                 'web_headline': web_headline}
            elif is_paywall_screen(texts):
                print('  -> VERIFIED (paywall/plus article)')
                results[link] = {'status': STATUS_VERIFIED,
                                 'resolved_link': resolved_link,
                                 'web_headline': web_headline}
            elif not texts:
                print('  -> leaving unverified (News.app showed nothing readable)')
                results[link] = {'status': STATUS_UNVERIFIED,
                                 'resolved_link': resolved_link,
                                 'web_headline': web_headline}
            else:
                print('  -> MISSING (sim {:.2f} < {:.2f})'.format(
                    best_sim, args.threshold))
                results[link] = {'status': STATUS_MISSING, 'resolved_link': '',
                                 'web_headline': ''}

            close_news_front_window()

    except KeyboardInterrupt:
        print('\nInterrupted.')

    verified_count   = sum(1 for r in results.values() if r['status'] == STATUS_VERIFIED)
    missing_count    = sum(1 for r in results.values() if r['status'] == STATUS_MISSING)
    unverified_count = sum(1 for r in results.values() if r['status'] == STATUS_UNVERIFIED)
    print('\nResults: {} verified, {} removed, {} still unverified'.format(
        verified_count, missing_count, unverified_count))

    if not results:
        return

    if not args.confirm:
        print('Dry-run complete. Re-run with --confirm to apply changes.')
        return

    print('Backing up {} -> {}'.format(CSV_PATH, BACKUP_PATH))
    shutil.copy2(CSV_PATH, BACKUP_PATH)

    updated = 0
    for link, result in results.items():
        new_status    = result['status']
        resolved_link = result['resolved_link']
        web_headline  = result.get('web_headline', '')
        for i in link_to_indices.get(link, []):
            rows[i]['link_status']   = new_status
            rows[i]['resolved_link'] = resolved_link
            if web_headline:
                rows[i]['web_headline'] = web_headline
            if new_status == STATUS_MISSING:
                rows[i]['link'] = ''
            updated += 1

    save_csv(CSV_PATH, fieldnames, rows)
    print('Done. Updated {} rows.'.format(updated))
    print()
    print_status_counts(rows)


if __name__ == '__main__':
    main()
