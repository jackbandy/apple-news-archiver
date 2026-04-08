# TODO

Updated 2026-04-08.

---

## 1. Security / Config (before going public)

- [ ] Verify `config_real.py` has never been committed in git history (`git log --all --full-history -- config_real.py`); it contains real device UDID and hardcoded paths. If it has, scrub with `git filter-repo`.
- [ ] Rename `config-demo.py` → `config_demo.py` to match what `config.py` actually imports
- [ ] Add `.claude/` to `.gitignore` — both root and `docs/.claude/` contain personal workspace settings

## 2. Data / File Cleanup

- [ ] Remove backup files from repo and add to `.gitignore`:
  - `data_output/stories.csv.bak`, `stories.csv.verify_bak`, `stories-old.csv`
  - Add `*.bak` and `*.verify_bak` patterns to `.gitignore`
- [ ] Move `data_from_paper/` (126 CSVs, ~9.8MB) out of repo — publish as a GitHub Release asset or Zenodo deposit and link from README
- [ ] Compress or externally host `Demo.gif` (7MB)

## 3. Backfill: Unified Script

Current state: 6 scripts in `backfill/` with overlapping responsibilities and different tech stacks:

| Script | What it does | Tech | Status |
|--------|-------------|------|--------|
| `backfill_links.py` | Fill missing `link` via iOS simulator search | Appium | **Abandoned** (search unavailable in iOS 26.4 sim) |
| `backfill_links_desktop.py` | Fill missing `link` via macOS News.app search | AppleScript + CoreGraphics | **In progress** (stuck on 3-dot menu detection) |
| `fill_trending_sources.py` | Fill missing `publication` for trending rows | `requests` + HTML meta parsing | **Works**, writes to sidecar JSON only |
| `backfill_trending_sources.py` | Fill missing `publication`/`author` for any row | `urllib` + HTMLParser meta parsing | **Works**, writes back to CSV |
| `verify_backfill_links.py` | Verify backfilled links match headlines | Appium (opens link, reads title) | **Works** |
| `verify_links_desktop.py` | Verify/resolve links via Safari + News.app | AppleScript + `open` command | **Works**, long-running daemon mode |

**Plan — combine into one `backfill/backfill.py` with subcommands:**

```
python3 backfill/backfill.py fill-links       # search News.app for missing links (desktop approach)
python3 backfill/backfill.py fill-metadata     # fetch publication/author from apple.news HTML meta tags
python3 backfill/backfill.py verify            # open each unverified link, compare title, mark V/M
python3 backfill/backfill.py status            # print summary of missing links, unverified rows, etc.
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

## 4. Website Launch (`docs/`)

The dashboard is ~85% ready. Remaining work:

- [ ] Implement the Coverage tab (spec in `notes/coverage-tab-plan.md`) — grid of (run_time × section) showing collection success/failure
- [ ] Test the site with the full `stories.csv` dataset (10K+ rows) — check load time, filtering performance
- [ ] Add a footer or "About" section linking to the ICWSM paper and repo
- [ ] Enable GitHub Pages on the repo (Settings → Pages → source: `docs/`)

## 5. Documentation

- [ ] Update `README.md`:
  - Document the config system (`config.py` / `config_demo.py` pattern)
  - Mention the live web dashboard in `docs/`
  - Describe the backfill tooling
  - Fix the cron interval (says every 5 minutes, actual is hourly)
  - Add a "Data" section describing `stories.csv` schema and output format
- [ ] Clean up `notes/` — consolidate into a `DEVELOPMENT.md` or delete stale notes before going public

## 6. Code / Dependencies

- [ ] Add `requests` to `requirements.txt` (used by `fill_trending_sources.py`)
- [ ] Implement story label capture (see `notes/scraper-label-fix.md`) — read 3 text elements per cell instead of 1, add `label` column to CSV

## 7. Git Housekeeping

- [ ] Delete stale branches: `data-collection`, `demo-maintenance`, `website-update-2026` (local + remote)
- [ ] Consider squashing the 100+ "Auto commit with data" commits before going public
