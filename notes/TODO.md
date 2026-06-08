# TODO

Updated 2026-06-08.

---

## P0 (Blockers Before Going Public)

- [x] Clarify canonical data outputs: merged `data_output/stories.csv` (May–June) into `docs/data/stories.csv`; fixed `config_real.py` to write to `docs/data/stories.csv`; gitignored `data_output/stories.csv`.

## P1 (Correctness / Data Quality)

- [x] Remove / gate region-specific headers: moved Chicago/Illinois/Illinois Politics to `EXTRA_SECTION_HEADERS` in config (empty by default in `config_demo.py`).
- [ ] Decide section behavior:
  - Should the dashboard dynamically expose every observed section, including historical regional rows and future `popular` rows?
  - Should coverage use dynamic columns, ordered as Top, Trending, Favorites, Popular, then custom sections?
  - Should charts remain limited to Top and Trending?
  - Should `EXTRA_SECTION_HEADERS` include public display labels as well as CSV keys?
- [ ] Decide story-label schema:
  - Add a `label` column after `section`, leaving historical values blank?
  - Preserve all separate Apple News label text, with multiple labels joined by ` | `?
  - Display labels as headline badges, but exclude them from observation identity?
  - Keep CSV readers compatible with both the existing 12-column and new 13-column schemas?

## P2 (Backfill Simplification)

Remaining backfill scripts:

| Script | What it does | Tech | Status |
|--------|-------------|------|--------|
| `backfill_links_desktop.py` | Fill missing `link` via macOS News.app search | AppleScript + CoreGraphics | In progress (3-dot menu detection) |
| `backfill_trending_sources.py` | Fill missing `publication`/`author` via apple.news meta | `urllib` + HTMLParser | Works, writes back to CSV |
| `verify_links_desktop.py` | Verify/resolve links via Safari + News.app | AppleScript + `open` | Works, supports long-running daemon mode |

- [ ] Finish `backfill_links_desktop.py` — complete the 3-dot menu / right-click "Copy Link" approach.

## P3 (Website)

- [ ] Implement the Coverage tab (spec in `notes/coverage-tab-plan.md`)
- [ ] Test the site with the full `stories.csv` dataset (10K+ rows) — check load time, filtering performance
- [ ] Enable GitHub Pages on the repo (Settings → Pages → source: `docs/`)

## P4 (Housekeeping)

- [x] Add `.claude/` and `docs/.claude/` patterns to `.gitignore`
- [x] Add `data_output/stories.csv` and `*.bak`/`*.verify_bak` patterns to `.gitignore`
- [ ] Delete stale branches: `data-collection`, `demo-maintenance`, `website-update-2026`
- [ ] Consider squashing the 100+ "Auto commit with data" commits before going public

## Completed

- [x] Update `README.md`: config system, dashboard mention, `requirements.txt` install, Data section, cron command
- [x] Fix web dashboard CSV parser (RFC 4180-safe)
- [x] Consolidate Appium/WDA session logic into `util/appium_session.py`
- [x] Add `requests` to `requirements.txt`
- [x] Remove abandoned backfill scripts: `backfill_links.py` (Appium, broken on iOS 26.4), `verify_backfill_links.py` (superseded by desktop verifier), `fill_trending_sources.py` (superseded by `backfill_trending_sources.py`)
