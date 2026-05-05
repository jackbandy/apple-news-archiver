'''
backfill_links_desktop.py

Uses the macOS News app (System Events + CoreGraphics mouse control) to
search for each story headline and copy the apple.news link via the
three-dot context menu on the first story in the "Stories" section.
Channels & Topics results are skipped.

Prerequisites:
  System Settings → Privacy & Security → Accessibility → enable Terminal

Usage:
    python3 backfill_links_desktop.py             # dry-run
    python3 backfill_links_desktop.py --confirm   # write changes
    python3 backfill_links_desktop.py --limit 5   # test on 5 headlines first
    python3 backfill_links_desktop.py --debug-ui  # dump search result tree
'''

import csv
import re
import sys
import time
import shutil
import difflib
import argparse
import subprocess
import ctypes
import ctypes.util

CSV_PATH = 'docs/data/stories.csv'
BACKUP_PATH = CSV_PATH + '.bak'

MATCH_THRESHOLD = 0.50
BETWEEN_SEARCH_SECS = 2.0
SKIP_HEADLINES = {'', 'apple news plus', 'apple news today'}


# ---------------------------------------------------------------------------
# CoreGraphics mouse control (no extra installs required on macOS)
# ---------------------------------------------------------------------------

_cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
_cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CFRelease.argtypes = [ctypes.c_void_p]

# Virtual key codes (Carbon HIToolbox)
kVK_Return    = 0x24
kVK_Escape    = 0x35
kVK_DownArrow = 0x7D

kCGHIDEventTap      = 0
kCGEventMouseMoved  = 5
kCGEventLeftMouseDown  = 1
kCGEventLeftMouseUp    = 2
kCGEventRightMouseDown = 3
kCGEventRightMouseUp   = 4
kCGMouseButtonLeft  = 0
kCGMouseButtonRight = 1


class _CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


def _post_mouse(event_type, x, y, button=kCGMouseButtonLeft):
    pt = _CGPoint(x, y)
    ev = _cg.CGEventCreateMouseEvent(None, event_type, pt, button)
    _cg.CGEventPost(kCGHIDEventTap, ev)
    _cg.CFRelease(ev)


def mouse_move(x, y):
    _post_mouse(kCGEventMouseMoved, x, y)
    time.sleep(0.05)


def mouse_click(x, y):
    _post_mouse(kCGEventLeftMouseDown, x, y)
    time.sleep(0.05)
    _post_mouse(kCGEventLeftMouseUp, x, y)
    time.sleep(0.1)


def mouse_right_click(x, y):
    _post_mouse(kCGEventRightMouseDown, x, y, kCGMouseButtonRight)
    time.sleep(0.05)
    _post_mouse(kCGEventRightMouseUp, x, y, kCGMouseButtonRight)
    time.sleep(0.2)


def key_press(keycode):
    '''Post a key-down + key-up via CoreGraphics (does not steal app focus).'''
    for down in (True, False):
        ev = _cg.CGEventCreateKeyboardEvent(None, keycode, down)
        _cg.CGEventPost(kCGHIDEventTap, ev)
        _cg.CFRelease(ev)
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# osascript helpers
# ---------------------------------------------------------------------------

def run_applescript(script, timeout=20):
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def check_accessibility():
    _, err, code = run_applescript('''
tell application "System Events"
    set frontApp to name of first process whose frontmost is true
end tell''')
    return not (code != 0 and 'assistive access' in err.lower())


def pbpaste():
    return subprocess.run(['pbpaste'], capture_output=True, text=True).stdout.strip()


def pbclear():
    subprocess.run(['pbcopy'], input='__CLEAR__', text=True)


# ---------------------------------------------------------------------------
# News.app interaction
# ---------------------------------------------------------------------------

# Path to the deeply-nested group that holds both the sidebar items and
# the main content. Discovered via accessibility tree exploration.
_BASE_PATH = ('group 1 of group 3 of group 1 of group 1 of group 1 of '
              'group 1 of group 1 of group 1 of group 1 of window 1')


def _get_news_window_origin():
    '''Return (x, y) of the News.app window top-left corner.'''
    out, _, _ = run_applescript('''
tell application "System Events"
    tell process "News"
        set p to position of window 1
        return (item 1 of p) & "," & (item 2 of p)
    end tell
end tell''')
    parts = out.split(',')
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 361, 34  # fallback from exploration


def _get_story_elements():
    '''
    After a search is active, return a list of dicts describing result
    elements that are likely stories (not channels):
      {x, y, w, h, desc, has_image, child_count}

    Stories: AXGenericElement with 2+ children (headline text, metadata)
             but NO nested image (channels have a logo image).
    The "Stories" section is separated from "Channels & Topics" by an
    AXHeading. We collect elements only AFTER the first non-channel heading
    (or just take those without images if no heading is found).
    '''
    out, err, code = run_applescript('''
tell application "System Events"
    tell process "News"
        set base to ''' + _BASE_PATH + '''
        set output to ""
        set inStories to false
        repeat with el in every UI element of base
            set r to role of el
            -- Headings mark section boundaries
            if r is "AXHeading" then
                set d to description of el
                -- "Stories" heading (or any non-channel heading) starts story results
                if d does not contain "Channel" and d does not contain "Topic" then
                    set inStories to true
                end if
            end if
            if r is "AXGenericElement" then
                set pos to position of el
                set sz to size of el
                set d to description of el
                set px to item 1 of pos
                set py to item 2 of pos
                set pw to item 1 of sz
                set ph to item 2 of sz
                -- Check for image child (channel indicator)
                set hasImg to "0"
                try
                    set imgs to every image of el
                    if (count of imgs) > 0 then set hasImg to "1"
                end try
                -- Count children
                set nKids to count of every UI element of el
                set output to output & px & "," & py & "," & pw & "," & ph & "," & d & "|" & hasImg & "|" & nKids & "|" & inStories & linefeed
            end if
        end repeat
        return output
    end tell
end tell''', timeout=25)

    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            coords_rest = line.split(',', 4)
            if len(coords_rest) < 5:
                continue
            x, y, w, h = int(coords_rest[0]), int(coords_rest[1]), int(coords_rest[2]), int(coords_rest[3])
            rest = coords_rest[4]
            parts = rest.split('|')
            if len(parts) < 4:
                continue
            desc = parts[0]
            has_image = parts[1] == '1'
            child_count = int(parts[2])
            in_stories = parts[3].strip() == 'true'
            results.append({
                'x': x, 'y': y, 'w': w, 'h': h,
                'desc': desc,
                'has_image': has_image,
                'child_count': child_count,
                'in_stories': in_stories,
            })
        except (ValueError, IndexError):
            continue
    return results


def _hover_and_find_dotdot_button(sx, sy):
    '''
    Hover at (sx, sy) in screen coordinates, wait for the "..." button to
    appear, then return its screen (x, y) center. Returns None if not found.
    '''
    mouse_move(sx, sy)
    time.sleep(0.6)

    out, _, _ = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to ""
        set base to ''' + _BASE_PATH + '''
        repeat with el in every UI element of base
            if role of el is "AXGenericElement" then
                repeat with btn in every button of el
                    set d to description of btn
                    if d contains "More" or d contains "more" or d = "…" or d = "..." then
                        set pos to position of btn
                        set sz to size of btn
                        set cx to (item 1 of pos) + (item 1 of sz) / 2
                        set cy to (item 2 of pos) + (item 2 of sz) / 2
                        set output to (cx as integer) & "," & (cy as integer)
                        exit repeat
                    end if
                end repeat
                if output is not "" then exit repeat
            end if
        end repeat
        return output
    end tell
end tell''', timeout=15)

    if out and ',' in out:
        try:
            bx, by = out.split(',', 1)
            return int(bx.strip()), int(by.strip())
        except ValueError:
            pass
    return None


def _nav_menu_copy_link(down_count):
    '''Navigate an open context menu to "Copy Link" using CoreGraphics key
    events (no AppleScript = no focus steal = menu stays open).
    down_count: how many Down-arrow presses before pressing Return.
    Clears clipboard first; returns the link string or None.
    '''
    pbclear()
    for _ in range(down_count):
        key_press(kVK_DownArrow)
        time.sleep(0.08)
    key_press(kVK_Return)
    time.sleep(0.4)
    clip = pbpaste()
    if clip and '__CLEAR__' not in clip and 'apple.news' in clip:
        idx = clip.find('https://apple.news')
        return clip[idx:].split()[0]
    return None


def search_and_copy_link(headline):
    '''
    Full flow: activate News, type headline into search, find first story
    result (skip channels), hover to reveal "..." button, click it, select
    "Copy Link". Returns apple.news URL or None.
    '''
    # Activate and type search query (truncate to avoid over-specific queries)
    query = headline[:65]
    escaped = query.replace('\\', '\\\\').replace('"', '\\"')

    # Click the sidebar Search item (UI element 4 of base) — Cmd+F opens the
    # inline sidebar search instead, which doesn't show story results.
    # After typing, press Return to submit; without it the app shows topic grid.
    search_script = (
        'tell application "News" to activate\n'
        'delay 0.5\n'
        'tell application "System Events"\n'
        '    tell process "News"\n'
        '        set base to ' + _BASE_PATH + '\n'
        '        click UI element 4 of base\n'
        '        delay 0.8\n'
        '        keystroke "a" using command down\n'
        '        delay 0.1\n'
        '        keystroke "{}"\n'.format(escaped) +
        '        delay 0.2\n'
        '        keystroke return\n'
        '        delay 3.5\n'
        '    end tell\n'
        'end tell\n'
    )
    _, err, code = run_applescript(search_script, timeout=25)
    if code != 0:
        print('  Search script error: {}'.format(err))
        return None

    # The story content pane is not reachable via the accessibility tree from
    # _BASE_PATH (it only exposes sidebar items). Instead, right-click at
    # estimated screen positions in the content area (right of the ~260px
    # sidebar) and look for "Copy Link" in the resulting context menu.
    wx, wy = _get_news_window_origin()
    content_x = wx + 500  # ~center of content pane

    # After right-clicking, navigate the context menu with CoreGraphics key
    # events — AppleScript steals focus and dismisses the menu, so we cannot
    # use it here. We try a few Down-arrow counts in case the menu layout
    # varies (separator rows count as steps on some macOS versions).
    # Run --debug-menu to take a screenshot and confirm the right count.
    for story_y in [wy + 180, wy + 260, wy + 340]:
        print('  Right-clicking at ({}, {})'.format(content_x, story_y))
        mouse_right_click(content_x, story_y)
        time.sleep(0.5)  # wait for menu to render
        for down_count in [5, 4, 6]:
            link = _nav_menu_copy_link(down_count)
            if link:
                print('  -> found with down_count={}'.format(down_count))
                return link
            # Re-open menu for next attempt (menu was closed by Return)
            mouse_right_click(content_x, story_y)
            time.sleep(0.5)
        # Nothing worked at this y — dismiss and try next y position
        key_press(kVK_Escape)
        time.sleep(0.3)

    return None


def debug_ui():
    '''Navigate to search, type a test query, then dump the accessibility tree.'''
    nav_script = (
        'tell application "News" to activate\n'
        'delay 0.5\n'
        'tell application "System Events"\n'
        '    tell process "News"\n'
        '        set base to ' + _BASE_PATH + '\n'
        '        click UI element 4 of base\n'
        '        delay 0.8\n'
        '        keystroke "a" using command down\n'
        '        delay 0.1\n'
        '        keystroke "apple"\n'
        '        delay 0.2\n'
        '        keystroke return\n'
        '        delay 3.5\n'
        '    end tell\n'
        'end tell\n'
    )
    _, err, code = run_applescript(nav_script, timeout=20)
    if code != 0:
        print('Navigation error:', err)
        return
    out, err, _ = run_applescript('''
tell application "System Events"
    tell process "News"
        set base to ''' + _BASE_PATH + '''
        set output to ""
        repeat with el in every UI element of base
            try
                set r to role of el
                set d to description of el
                set pos to position of el
                set sz to size of el
                set nKids to count of every UI element of el
                set output to output & r & " pos=" & (item 1 of pos) & "," & (item 2 of pos) & " " & (item 1 of sz) & "x" & (item 2 of sz) & " desc=" & d & " kids=" & nKids & linefeed
            end try
        end repeat
        return output
    end tell
end tell''', timeout=20)
    print(out or err)


def debug_menu():
    '''Right-click in the content area then dump all windows and menus so we
    can see exactly what accessibility objects appear for the context menu.
    Assumes News is already showing search results.'''
    wx, wy = _get_news_window_origin()
    cx, cy = wx + 500, wy + 180
    print('Right-clicking at ({}, {}) ...'.format(cx, cy))
    mouse_right_click(cx, cy)
    time.sleep(0.8)
    out, err, _ = run_applescript('''
tell application "System Events"
    tell process "News"
        set output to "=== every menu ===" & linefeed
        set mn to 0
        repeat with m in every menu
            set mn to mn + 1
            set output to output & "menu " & mn & " title=" & (title of m) & linefeed
            try
                repeat with mi in every menu item of m
                    try
                        set output to output & "  item title=" & (title of mi) & linefeed
                    end try
                end repeat
            end try
        end repeat
        set output to output & "=== every window ===" & linefeed
        repeat with w in every window
            try
                set output to output & "win role=" & (role of w) & " subrole=" & (subrole of w) & " title=" & (title of w) & linefeed
            end try
        end repeat
        return output
    end tell
end tell''', timeout=15)
    print(out or err)
    # Screenshot while menu is still open (before AppleScript steal focus)
    # Use CoreGraphics Escape to dismiss — not osascript
    screenshot_path = '/tmp/news_menu_debug.png'
    subprocess.run(['screencapture', '-x', screenshot_path])
    print('Screenshot saved: {}'.format(screenshot_path))
    print('Open it with: open {}'.format(screenshot_path))
    key_press(kVK_Escape)


# ---------------------------------------------------------------------------
# Headline helpers
# ---------------------------------------------------------------------------

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s']", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def best_headline(row):
    h = (row.get('article_headline') or '').strip()
    if h and len(h) > 10:
        return h
    return (row.get('headline') or '').strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--threshold', type=float, default=MATCH_THRESHOLD)
    parser.add_argument('--debug-ui', action='store_true')
    parser.add_argument('--debug-menu', action='store_true')
    args = parser.parse_args()

    if args.debug_ui:
        debug_ui()
        return

    if args.debug_menu:
        debug_menu()
        return

    if not check_accessibility():
        print('ERROR: Terminal needs Accessibility access.')
        print('Grant it: System Settings → Privacy & Security → Accessibility')
        sys.exit(1)

    with open(CSV_PATH, newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print('Rows missing a link: {}/{}'.format(
        sum(1 for r in rows if not r.get('link', '').strip()), len(rows)))

    seen_queries = {}
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

    queries = list(seen_queries.items())
    print('Unique searchable headlines: {}'.format(len(queries)))
    if args.limit > 0:
        queries = queries[:args.limit]
        print('Limiting to {}'.format(args.limit))

    print('\nMode: {}\n'.format('WRITE' if args.confirm else 'DRY-RUN'))

    found_links = {}
    try:
        for idx, (norm_key, (headline, row_indices)) in enumerate(queries, 1):
            print('[{}/{}] {!r}'.format(idx, len(queries), headline[:70]))
            link = search_and_copy_link(headline)
            if link:
                found_links[norm_key] = link
                print('  -> {} ({} rows)'.format(link, len(row_indices)))
            else:
                print('  -> not found')
            time.sleep(BETWEEN_SEARCH_SECS)
    except KeyboardInterrupt:
        print('\nInterrupted.')

    print('\n{}/{} resolved'.format(len(found_links), len(queries)))
    if not found_links:
        print('Nothing to write.')
        return

    total = sum(len(seen_queries[k][1]) for k in found_links)
    print('Would update {} rows.'.format(total))

    if not args.confirm:
        print('Dry-run — pass --confirm to write.')
        return

    print('Backing up {} -> {}'.format(CSV_PATH, BACKUP_PATH))
    shutil.copy2(CSV_PATH, BACKUP_PATH)

    updated = 0
    for norm_key, link in found_links.items():
        _, row_indices = seen_queries[norm_key]
        for i in row_indices:
            if rows[i].get('link', '').strip():
                continue
            rows[i]['link'] = link
            updated += 1

    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print('Done. Updated {} rows.'.format(updated))


if __name__ == '__main__':
    main()
