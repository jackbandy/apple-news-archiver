# Apple News Scraper

![](Demo.gif)

This repository contains code and data for collecting Apple News Top Stories and
Trending Stories from an iOS Simulator.

If you use this repository, please cite:

Bandy, J., & Diakopoulos, N. (2020). [Auditing News Curation Systems: A Case
Study Examining Algorithmic and Editorial Logic in Apple
News](https://doi.org/10.1609/icwsm.v14i1.7277). *Proceedings of
the International AAAI Conference on Web and Social Media, 14*(1), 36-47.
https://doi.org/10.1609/icwsm.v14i1.7277

## Setup

### Install Appium

Install Appium and the XCUITest driver:

```
npm install -g appium
appium driver install xcuitest
```

Create a Python virtual environment and install the Python dependencies:

```
python3 -m venv .venv
.venv/bin/pip install Appium-Python-Client selenium
```

### Configure the scraper

1. List available simulators (you'll need to be on Mac OS with XCode)):

```
xcrun simctl list devices
```

2. Choose a booted (or available) simulator, e.g. `iPhone 17 Pro (XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)`
3. Copy the demo config:

```
cp config_demo.py config_real.py
```

4. Edit `config_real.py` with your simulator name, iOS version, and UDID:

```python
DEVICES = [
    ('iPhone 17 Pro', '18.0', 'YOUR-SIMULATOR-UDID-HERE'),
]
```

5. Set `APP_PATH` in `config_real.py` to the full path of the simulator's
   `News.app` bundle. To find it, run:

```
find ~/Library/Developer/CoreSimulator -name "News.app" 2>/dev/null
```


## Run Data Collection


Start Appium in a separate terminal:

```
appium
```

Then run the scraper:

```
.venv/bin/python get_stories.py
```

To run the scraper repeatedly, I recommend cron. Run `crontab -e` and add (this
collects once every 20 minutes):

```
*/20 * * * * cd /path/to/apple-news-scraper && .venv/bin/python get_stories.py >> logs/cron.log 2>&1
```

## Configuration

`config.py` loads your private `config_real.py` if present, and otherwise falls
back to the committed `config_demo.py` template (and exits with a reminder).
`config_real.py` is gitignored, so your UDIDs and local paths stay out of the
repo. If `DEVICES` lists more than one simulator, each run rotates to the next
one — a shuffled order persisted in `.device_rotation`.

Key knobs:

- `output_file` — main CSV path (the demo points at `docs/data/stories.csv`, which the web dashboard reads).
- `output_folder` — where per-run JSON snapshots are written (`data_output/json/`).
- `COLLECT_TOP_STORIES` — also navigate into the Top Stories view for ranked collection.
- `MAX_*` — per-section caps for the home feed.
- `MAX_RUN_SECONDS` — wall-clock kill switch for a single run (`0` = no limit).

## Data Output

Each run appends rows to the CSV (`output_file`) and writes a per-run snapshot
to `data_output/json/<run_time>.json`.

CSV columns:

| Column | Description |
|--------|-------------|
| `link` | `https://apple.news/…` share link (empty for Apple News+ stories and rows where the link couldn't be copied) |
| `rank` | Position within its section (integer; or `plus` / `audio` for those rows) |
| `section` | `top`, `trending`, `reader_favorites`, `popular`, or a region-specific section |
| `run_time` | Collection timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `pub_time` | Parsed publication time of the story, when available |
| `publication` | Publisher name |
| `author` | Byline |
| `headline` | Headline as shown in the feed cell |
| `article_headline` | Headline read from the opened article view |
| `link_status` | `U` link present, `P` Apple News+ (no link), `M` link missing |
| `resolved_link` | Final resolved URL, filled in by the backfill verifier |
| `web_headline` | Headline fetched from the resolved link, filled in by the backfill verifier |

## Web Dashboard

`docs/` is a static dashboard (the "Apple News Story Explorer") that loads
`docs/data/stories.csv` and lets you browse and filter collected stories. It's
plain HTML/CSS/JS — open `docs/index.html` directly, or serve the folder
(`python3 -m http.server` from `docs/`). It can be published with GitHub Pages
(Settings → Pages → source: `docs/`).

## Backfill Tooling

The `backfill/` directory holds scripts for enriching previously collected
stories — filling in missing `link`s, filling missing `publication` / `author`
metadata, and verifying that collected links resolve to the right article. This
tooling is actively evolving and is slated for consolidation into a single
`backfill.py` with subcommands; see `notes/TODO.md` for current status.
