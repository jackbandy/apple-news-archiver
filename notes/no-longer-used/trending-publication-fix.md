# Fix: Extract Publication for Trending Stories

## Problem
All trending stories have an empty `publication` field in the CSV. Apple News trending cards don't include the publication name in the cell's accessibility label — only the headline, "X hours ago", and optionally an author.

## Root Cause
In `get_stories.py` around line 325, trending rows skip `parse_cell_label` entirely:
```python
if section == 'trending':
    headline = label.strip()
```
So publication is always left as `''`.

## Fix
`get_article_headline()` already taps into each article and reads a `XCUIElementTypeScrollView` whose `.name` attribute is `"Publication, Headline"`. It calls `parse_cell_label(name)` but discards the publication:
```python
_, headline, _ = parse_cell_label(name)
```

Steps to fix:
1. Change `get_article_headline` to return `(article_headline, article_pub)` instead of just `article_headline` — capture `pub` from the same `parse_cell_label` call.
2. Update both call sites (~line 359 and ~line 479) to unpack the tuple.
3. For trending stories where `publication == ''`, set `publication = article_pub`.
4. Top stories already have a publication from `parse_cell_label(label)`, so the article-derived pub would only fill gaps — no risk of overwriting.
