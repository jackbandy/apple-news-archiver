# Scraper fix: capture story labels as a dedicated field

## Problem
Some top stories have a label (e.g. `DEVELOPING`, `Video`) that Apple News displays between the publication name and headline. The current scraper reads the cell as a single text blob, so the label ends up mangled into either the `publication` or `headline` field.

Two observed patterns in the data:
- `publication = "Video"`, `headline = "CBS News, actual headline"` — label replaced the pub field
- `publication = "ABC News"`, `headline = "DEVELOPING, actual headline"` — label prepended to headline

## Fix
- In `get_stories.py`, when reading a story cell, look for **three distinct XCUITest text elements** stacked vertically instead of one
  - Element 1 → publication
  - Element 2 → label (e.g. `DEVELOPING`, `Video`, `BREAKING`)
  - Element 3 → headline
- If only two elements are present, the label is absent — treat as normal
- Write the label to a new `label` column in the CSV (empty string if none)

## Also: trending stories are missing publications
- Trending cells don't include a publication name in the scraped text — only `headline, time ago, author`
- Either Apple News doesn't show a publication in the trending cell layout, or the scraper is reading the wrong element
- Options to fix:
  - Read an additional XCUITest text element in the trending cell that may contain the publication
  - Fetch `og:site_name` from the article URL after copying the share link
- Low priority since many trending stories come from blogs/aggregators where publication and author blur together anyway

## Notes
- The current CSV schema is `link, rank, section, run_time, pub_time, publication, headline, article_headline`
- New schema would add `label` after `publication`
- Existing rows without the column will need a default empty value (handled by the CSV parser's fallback)
- The frontend whitelist workaround in `data.js` (`extractStoryLabel`) can be removed once historical data is backfilled
