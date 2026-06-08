# Apple News Scraper

![](Demo.gif)

This repository contains code and data for collecting Apple News Top Stories and
Trending Stories from an iOS Simulator.

A live web dashboard for browsing and filtering the collected data is served from
the `docs/` folder via GitHub Pages.

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
.venv/bin/pip install -r requirements.txt
```

### Configure the scraper

The scraper reads from `config_real.py`. Copy the demo config as a starting point:

```
cp config_demo.py config_real.py
```

`config_real.py` is gitignored, so your local settings are never committed.

1. List available simulators (you'll need to be on macOS with Xcode):

```
xcrun simctl list devices
```

2. Edit `config_real.py` with your simulator name, iOS version, and UDID:

```python
DEVICES = [
    ('iPhone 17 Pro Max', '18.0', 'YOUR-SIMULATOR-UDID-HERE'),
]
```

3. Set `APP_PATH` in `config_real.py` to the full path of the simulator's
   `News.app` bundle. To find it, run:

```
find ~/Library/Developer/CoreSimulator -name "News.app" 2>/dev/null
```

**Multiple devices:** If you list more than one entry in `DEVICES`, the scraper
rotates through them in a random order each cycle.


## Run Data Collection

Start Appium in a separate terminal:

```
appium
```

Then run the scraper:

```
mkdir -p logs
.venv/bin/python get_stories.py
```

The scraper exits with status `0` after a successful collection or when another
scraper instance already holds the run lock. It exits nonzero when Appium cannot
connect, collection produces no stories, a requested Top Stories view is
unavailable, or data cannot be persisted. Partial runs are saved with warnings.

To run the scraper repeatedly, I recommend cron. Run `crontab -e` and add:

```
*/20 * * * * cd /path/to/apple-news-scraper && .venv/bin/python get_stories.py >> logs/cron.log 2>&1
```


## Data

Stories are appended to `docs/data/stories.csv`. Each row is one story observed
during one collection run. Columns:

| Column | Description |
|--------|-------------|
| `link` | `apple.news` short URL |
| `rank` | Position within its section for that run |
| `section` | `top`, `trending`, or `reader_favorites` |
| `run_time` | Timestamp the collection run started |
| `pub_time` | Publication timestamp parsed from the story card (when available) |
| `publication` | Publisher name (e.g. *The New York Times*) |
| `author` | Byline author (when available) |
| `headline` | Headline as shown in the Apple News feed |
| `article_headline` | Full article headline fetched by opening the story |
| `link_status` | `U` = unverified, `V` = verified, `M` = missing/removed |
| `resolved_link` | Final redirect URL (e.g. `nytimes.com/…`) resolved by `verify_links_desktop.py` |
| `web_headline` | Page title from the resolved URL |

Raw per-run JSON snapshots are written to `data_output/` before the CSV is updated.

To check or repair duplicate observations in the canonical CSV:

```
.venv/bin/python scripts/deduplicate_stories.py --check
.venv/bin/python scripts/deduplicate_stories.py
```
