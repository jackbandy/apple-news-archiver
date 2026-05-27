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

To run the scraper repeatedly, I recommend cron. Run `crontab -e` and add:

```
*/20 * * * * cd /path/to/apple-news-scraper && .venv/bin/python get_stories.py >> logs/cron.log 2>&1
```
