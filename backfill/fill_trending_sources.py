#!/usr/bin/env python3
"""
Band-aid script: fill in missing publication sources for trending stories.
Reads data_output/stories.csv, fetches apple.news pages for trending stories
that lack a publication, extracts the source from og:title, and writes
results to data_output/trending_sources_bandaid.json.

Does NOT modify stories.csv or any existing data files.
"""

import csv
import json
import re
import time
from pathlib import Path

import requests

STORIES_CSV = Path('docs/data/stories.csv')
BANDAID_JSON = Path('docs/data/trending_sources_bandaid.json')

HEADERS = {
    'User-Agent': 'Twitterbot/1.0'
}
DELAY_SECONDS = 1.0  # be polite


def extract_publication(html):
    """Extract publication from <meta name="Author"> or fall back to og:title."""
    # Primary: <meta name="Author" content="Fox News" />
    match = re.search(r'<meta\s+name=["\']Author["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Fallback: og:title "Headline — Publication"
    match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.+?)["\']', html)
    if not match:
        match = re.search(r'<meta[^>]+content=["\'](.+?)["\'][^>]+property=["\']og:title["\']', html)
    if match:
        sep = re.search(r'\s[—–\-]\s(.+)$', match.group(1))
        if sep:
            return sep.group(1).strip()
    return None


def fetch_publication(link):
    try:
        r = requests.get(link, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f'  HTTP {r.status_code}: {link}')
            return None
        pub = extract_publication(r.text)
        return pub
    except Exception as e:
        print(f'  Error fetching {link}: {e}')
        return None


def main():
    # Load existing band-aid data so we don't re-fetch
    if BANDAID_JSON.exists():
        with open(BANDAID_JSON) as f:
            bandaid = json.load(f)
        print(f'Loaded {len(bandaid)} existing entries from {BANDAID_JSON}')
    else:
        bandaid = {}

    # Find unique trending stories without publication that have a link
    need_fetch = {}
    with open(STORIES_CSV) as f:
        for row in csv.DictReader(f):
            if row['section'] != 'trending':
                continue
            if row['publication']:
                continue
            link = row['link'].strip()
            if not link:
                continue
            if link in bandaid:
                continue
            need_fetch[link] = row['headline']

    print(f'{len(need_fetch)} trending stories with links need source lookup')

    if not need_fetch:
        print('Nothing to do.')
        return

    updated = 0
    for i, (link, headline) in enumerate(need_fetch.items(), 1):
        print(f'[{i}/{len(need_fetch)}] {link}')
        pub = fetch_publication(link)
        if pub:
            print(f'  -> {pub}')
            bandaid[link] = pub
            updated += 1
        else:
            print(f'  -> (not found)')
            bandaid[link] = None  # record the attempt so we don't retry endlessly
        time.sleep(DELAY_SECONDS)

    with open(BANDAID_JSON, 'w') as f:
        json.dump(bandaid, f, indent=2)

    filled = sum(1 for v in bandaid.values() if v)
    print(f'\nDone. {updated} new entries. {filled}/{len(bandaid)} total resolved.')
    print(f'Written to {BANDAID_JSON}')


if __name__ == '__main__':
    main()
