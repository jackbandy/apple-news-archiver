# Apple News Scraper

![](Demo.gif)

This repository provides code and data used in the following paper:

Bandy, Jack and Nicholas Diakopoulos. "**Auditing News Curation Systems: A Case Study Examining Algorithmic and Editorial Logic in Apple News.**" *To Appear in* Proceedings of the Fourteenth International AAAI Conference on Web and Social Media (ICWSM 2020).


## Installation and Setup Instructions

#### Install Appium
Install Appium and the XCUITest driver via npm:
```
npm install -g appium
appium driver install xcuitest
```

And the Python client and dependencies:
```
python3 -m venv .venv
.venv/bin/pip install Appium-Python-Client selenium
```

#### Install apple-news-scraper
After cloning this repository onto your computer,
1. List available simulators:
```
xcrun simctl list devices
```
2. Choose a booted (or available) simulator, e.g. `iPhone 17 Pro (XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)`
3. Copy the demo config and fill in your device info:
```
cp config_demo.py config_real.py
```
Edit `config_real.py`:
```python
DEVICES = [
    ('iPhone 17 Pro', '18.0', 'YOUR-SIMULATOR-UDID-HERE'),
]
```
Also set `APP_PATH` to the full path of your simulator's `News.app` bundle:
```
find ~/Library/Developer/CoreSimulator -name "News.app" 2>/dev/null
```


## Execution
Boot the simulator and open the News app:
```
xcrun simctl boot <UDID>
open -a Simulator
xcrun simctl launch <UDID> com.apple.news
```

Start Appium in a separate terminal:
```
appium
```

Then run the scraper:
```
.venv/bin/python get_stories.py
```

To run repeatedly, use cron. Run `crontab -e` and add:
```
*/20 * * * * cd /path/to/apple-news-scraper && .venv/bin/python get_stories.py >> logs/cron.log 2>&1
```
Make sure `logs/` exists first: `mkdir -p logs`

> **Note:** The scraper writes collected stories to `docs/data/stories.csv`.
> Commit and push that file to update the live web dashboard.
