'''
backfill_trending_sources.py

Fills empty `publication` (and `author`) fields in stories.csv for trending
rows collected before get_article_headline() was wired up.

For each unique apple.news link with an empty publication:
  1. Fetch the apple.news page (it does not redirect; meta is served directly).
  2. Parse <meta name="Author"> → publication (apple.news uses this for the
     publisher name, e.g. "Reuters", "People", "Real Simple").
  3. Optionally parse article:author / og:article:author → author.
  4. Write resolved values back into every matching row.

Only rows where publication == '' are touched. Rows with existing values
are never overwritten.
'''

import csv
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

CSV_PATH = 'docs/data/stories.csv'
RATE_LIMIT_SECS = 0.5


class MetaParser(HTMLParser):
    '''Collect publication and author from apple.news <meta> tags.

    apple.news uses <meta name="Author"> for the publisher name (e.g.
    "Reuters"), not og:site_name which is absent. article:author /
    og:article:author carry the byline author when present.
    '''

    def __init__(self):
        super().__init__()
        self.publication = ''
        self.author = ''

    def handle_starttag(self, tag, attrs):
        if tag != 'meta':
            return
        attr = dict(attrs)
        name = attr.get('name', '')
        prop = attr.get('property', '')
        content = attr.get('content', '').strip()
        if name == 'Author' and not self.publication:
            self.publication = content
        if prop in ('article:author', 'og:article:author') and not self.author:
            self.author = content


def fetch_meta(url):
    '''Fetch apple.news page and parse publication/author from meta tags.

    Returns (publication, author); either may be '' on failure or absence.
    '''
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; backfill-script/1.0)'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Read up to 64 KB — enough for <head> content.
            raw = resp.read(65536)
            charset = resp.headers.get_content_charset() or 'utf-8'
            html = raw.decode(charset, errors='replace')
    except Exception as exc:
        print(f'  WARNING: fetch failed for {url}: {exc}')
        return '', ''

    parser = MetaParser()
    try:
        parser.feed(html)
    except Exception as exc:
        print(f'  WARNING: parse failed for {url}: {exc}')
        return '', ''

    return parser.publication, parser.author


def main():
    # 1. Read CSV
    with open(CSV_PATH, newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # 2. Collect unique links with empty publication
    links_to_fetch = {
        row['link']
        for row in rows
        if row['link'] and not row['publication']
    }
    print(f'Unique links to fetch: {len(links_to_fetch)}')

    # 3. Fetch meta for each unique link
    resolved = {}  # link -> (publication, author)
    for i, link in enumerate(sorted(links_to_fetch), 1):
        print(f'[{i}/{len(links_to_fetch)}] {link}')
        pub, author = fetch_meta(link)
        if pub or author:
            print(f'  -> publication={pub!r}  author={author!r}')
        else:
            print(f'  -> no metadata found')
        resolved[link] = (pub, author)
        time.sleep(RATE_LIMIT_SECS)

    # 4. Write resolved values back into matching rows
    updated = 0
    for row in rows:
        link = row['link']
        if not link or row['publication']:
            continue
        pub, author = resolved.get(link, ('', ''))
        if pub:
            row['publication'] = pub
            updated += 1
        if author and not row['author']:
            row['author'] = author

    print(f'\nUpdated {updated} rows with resolved publication.')

    # 5. Overwrite CSV in place
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print('Done.')


if __name__ == '__main__':
    main()
