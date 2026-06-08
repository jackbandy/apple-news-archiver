# Backfill Publication & Author for Trending Stories

## Problem

Trending story rows in `stories.csv` have empty `publication` and `author` fields.
The live scraper now fills these in via `get_article_headline()`, but ~110 unique
historical trending links were collected before that fix and remain blank.

## Approach

Write `backfill_trending_sources.py` that:

1. Reads `stories.csv`
2. Collects every unique `link` where `publication` is empty
3. For each link, follows the apple.news redirect and reads the article page's
   `<meta>` tags: `og:site_name` → publication, `article:author` or `og:article:author` → author
4. Writes the resolved values back into every matching row (same link may appear
   many times across runs)
5. Overwrites `stories.csv` in place

## Key details

- **Dedup before fetching**: build a `{link: (publication, author)}` lookup from
  unique links first, then do one HTTP request per unique link (not per row)
- **Don't overwrite existing values**: only fill cells that are currently empty
- **Respect missing links**: skip rows where `link` is empty string
- **Rate-limit**: sleep ~0.5s between requests to avoid hammering servers
- **Failures**: if a fetch fails or returns no metadata, leave the row unchanged
  and print a warning; don't abort

## Script outline

```python
import csv, time, urllib.request
from html.parser import HTMLParser

CSV_PATH = 'data_output/stories.csv'

class MetaParser(HTMLParser):
    # collect og:site_name and article:author from <meta> tags
    ...

def fetch_meta(url):
    # follow redirect (apple.news → actual article), parse meta tags
    # return (publication, author) strings, either may be ''
    ...

def main():
    # 1. read CSV
    # 2. find unique links with empty publication
    # 3. fetch meta for each (with rate limit + error handling)
    # 4. rewrite CSV with filled values
    ...
```

## Scope

Only targets rows where `publication == ''`. Does not touch `author` fields on
rows that already have a publication (those were collected correctly and the
author may legitimately be blank).
