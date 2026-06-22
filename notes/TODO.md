# TODO

Updated 2026-06-15. Reviewed by an LLM coding tool (Claude Code) on 2026-06-15, with some stale items resolved and some open decisions surfaced below.

---

## Decisions Needed

These block the dependent work below

- [ ] **D1 — Canonical CSV path.** Two CSVs exist: `docs/data/stories.csv` (the
  `config_demo.py` default; read directly by the dashboard) and
  `data_output/stories.csv` (what the current `config_real.py` appears to write,
  per the working tree). Decide which is the single source of truth:
  - **Option A:** scraper writes straight into `docs/data/stories.csv` — simplest, but couples each collection run to the published site contents.
  - **Option B:** scraper writes to `data_output/stories.csv` and a separate step copies/publishes it into `docs/data/` — decouples collection from the site.
  - Whichever wins, point scraper + backfill + verifier + dashboard at it and delete the other. (Blocks P0 "canonical data outputs".)
- [ ] **D2 — Public section set.** Which sections are "public"? The scraper can
  emit `top`, `trending`, `reader_favorites`, `popular`, and region sections
  (`chicago`, `illinois`, `illinois_politics`); the dashboard only knows the
  first three. Pick the supported set, then:
  - Make it config-driven (e.g. dashboard reads available sections from the data) or hard-code the agreed list in both places.
  - **D2a — Region headers:** keep them behind config (e.g. `EXTRA_SECTION_HEADERS` in `config_real.py`) or drop the hardcoded "Chicago"/"Illinois"/"Illinois Politics" from `get_stories.py` entirely. (Blocks the two P1 "section support" / "region headers" items.)

---

## P0 (Blockers Before Advertising / Going Public)

- [x] ~~Fix repo naming/link drift in the dashboard~~ — intentional: dashboard keeps the `apple-news-archiver` naming even though the repo is `apple-news-scraper`. No change needed.
- [ ] Clarify canonical data outputs: both `data_output/stories.csv` and `docs/data/stories.csv` are in the repo. Pick one canonical CSV path and make everything point at it (scraper, backfill, verifier, dashboard). **→ blocked on decision D1.**
- [x] Update `README.md`:
  - Document the config system (`config.py` / `config_demo.py` pattern)
  - Mention the live web dashboard in `docs/`
  - Describe the backfill tooling
  - Fix the cron interval (README already shows `*/20`, matching the real 20-min cadence; the "every 5 minutes / hourly" note was stale)
  - Add a "Data" section describing `stories.csv` schema and output format

## P1 (Correctness / Data Quality)

- [ ] Align section support across scraper + dashboard: **→ blocked on decision D2.**
  - `get_stories.py` can emit `popular`, `chicago`, `illinois`, `illinois_politics`, but the dashboard filter dropdown (`docs/index.html`), stats (`docs/js/data.js`), and coverage (`docs/js/coverage.js`) only account for `top`, `trending`, `reader_favorites`.
  - Decide the “public” section set and make it config-driven (or remove region-specific sections entirely).
- [ ] Remove / gate region-specific headers: `get_stories.py` hardcodes "Chicago"/"Illinois"/"Illinois Politics". For public use, move these to config (e.g. `EXTRA_SECTION_HEADERS`) or drop them. **→ blocked on decision D2a.**
- [ ] Implement story label capture (see `notes/scraper-label-fix.md`) — read 3 text elements per cell instead of 1, add `label` column to CSV

## P2 (Simplification / Consolidation)

Backfill tooling currently has overlapping responsibilities and tech stacks:

| Script | What it does | Tech | Status |
|--------|-------------|------|--------|
| `backfill_links.py` | Fill missing `link` via iOS simulator search | Appium | **Abandoned** (search unavailable in iOS 26.4 sim) |
| `backfill_links_desktop.py` | Fill missing `link` via macOS News.app search | AppleScript + CoreGraphics | **In progress** (stuck on 3-dot menu detection) |
| `fill_trending_sources.py` | Fill missing `publication` for trending rows | `requests` + HTML meta parsing | **Works**, writes to sidecar JSON only |
| `backfill_trending_sources.py` | Fill missing `publication`/`author` for any row | `urllib` + HTMLParser meta parsing | **Works**, writes back to CSV |
| `verify_backfill_links.py` | Verify backfilled links match headlines | Appium (opens link, reads title) | **Works** |
| `verify_links_desktop.py` | Verify/resolve links via Safari + News.app | AppleScript + `open` command | **Works**, long-running daemon mode |

Plan: combine into one `backfill/backfill.py` with subcommands:

```bash
python3 backfill/backfill.py fill-links
python3 backfill/backfill.py fill-metadata
python3 backfill/backfill.py verify
python3 backfill/backfill.py status
```

Key consolidation points:

- [ ] Merge `fill_trending_sources.py` and `backfill_trending_sources.py` into one `fill-metadata` command. Both fetch apple.news HTML for `<meta name="Author">`; use the `urllib` approach (no extra dependency) and write directly to CSV (not a sidecar JSON).
- [ ] Port the working desktop link-fill logic from `backfill_links_desktop.py` into the `fill-links` command. Finish the 3-dot menu / right-click approach. Remove the abandoned Appium-based `backfill_links.py`.
- [ ] Port the working verification logic from `verify_links_desktop.py` into the `verify` command. It already handles Safari vs News.app detection, headline comparison, `link_status`/`resolved_link` columns, and long-running daemon mode with lock coordination. Keep these features.
- [ ] Remove `verify_backfill_links.py` (Appium-based verifier) — the desktop verifier (`verify_links_desktop.py`) supersedes it.
- [ ] Add a `status` subcommand that prints a quick summary: total rows, rows missing links, rows with unverified links, rows missing publication.
- [ ] All subcommands share: `--confirm` (default dry-run), `--limit N`, CSV path config.
- [ ] Remove `backfill-log.txt` and `backfill_notes.md` (session artifacts, not needed in repo).
- [ ] Delete `data_output/trending_sources_bandaid.json` after merging its data into the CSV.

## P3 (Website / Packaging)

- [ ] Implement the Coverage tab (spec in `notes/coverage-tab-plan.md`) — grid of (run_time × section) showing collection success/failure
- [ ] Test the site with the full `stories.csv` dataset (10K+ rows) — check load time, filtering performance
- [ ] Add a footer or "About" section linking to the ICWSM paper and repo
- [ ] Enable GitHub Pages on the repo (Settings → Pages → source: `docs/`)

## P4 (Housekeeping / Hygiene)

- [x] Remove backup files from repo and add to `.gitignore`:
  - `data_output/stories.csv.bak`, `stories.csv.verify_bak`, `stories-old.csv`
  - Add `*.bak` and `*.verify_bak` patterns to `.gitignore`
  - (Patterns present in `.gitignore` and files are untracked; the `.bak`/`stories-old.csv` files still sit on disk locally but are ignored.)
- [x] Rename `config-demo.py` → `config_demo.py` to match what `config.py` actually imports (already `config_demo.py`)
- [x] Add `.claude/` to `.gitignore` — both root and `docs/.claude/` contain personal workspace settings (`.claude/` pattern present in `.gitignore`)
- [x] Add `requests` to `requirements.txt` (used by `fill_trending_sources.py`)
- [ ] Clean up `notes/` — consolidate into a `DEVELOPMENT.md` or delete stale notes before going public
- [ ] Delete stale branches: `data-collection`, `demo-maintenance`, `website-update-2026` (local + remote)
- [ ] Consider squashing the 100+ "Auto commit with data" commits before going public

## Completed (Recent)

- [x] Fix the web dashboard CSV parser: `docs/js/csv.js` is not RFC 4180-safe (it toggles on every `"` and does not handle escaped quotes `""` or embedded newlines). `docs/data/stories.csv` already contains quoted headlines, so parsing can silently corrupt rows and break filters/charts.
- [x] Consolidate duplicated Appium/WDA logic:
  - `_build_xcuitest_options()` and the prebuilt-WDA bootstrap path logic live only in `get_stories.py`, while other Appium entrypoints (e.g. `util/debug_ui.py`, older backfill scripts) construct options differently and may fail on the same Xcode/iOS runtime.
  - Similarity helpers (`normalize`, `similarity`, `best_headline`) and some touch helpers are duplicated across `backfill/*.py` and could live in `util/`.
- [x] Dependencies are underspecified: `requirements.txt` only lists `appium-python-client`, but the scraper imports Selenium (`util/gestures.py`) and some backfill scripts import `requests`. Either add missing deps, split into `requirements-scrape.txt` / `requirements-backfill.txt`, or document “pip install …” as the source of truth.

