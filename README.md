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
3. Open `get_stories.py` and fill in your device info at the top:
```python
# user-defined variables
device_name_and_os = 'iPhone 17 Pro'
device_os = '18.0'
udid = 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX'
```
4. Change the output folder if desired:
```python
output_folder = 'data_output'
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
*/5 * * * * cd /Users/jack/dev/apple-news-scraper && .venv/bin/python get_stories.py >> logs/cron.log 2>&1
```
Make sure `logs/` exists first: `mkdir -p logs`
