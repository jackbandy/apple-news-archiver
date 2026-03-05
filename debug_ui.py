'''
debug_ui.py

Dumps the current accessibility tree from the running Appium session.
Run this while the Apple News app is open to inspect available elements.
Usage: .venv/bin/python debug_ui.py
'''

from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
import xml.dom.minidom

device_name_and_os = 'iPhone 17 Pro Max' 
device_os = '26.3' 
#udid = '735D7E9B-CA6A-49C0-A326-2C1DDD624F33'  # update via: xcrun simctl list devices 
udid = '0C82F604-5F47-44A3-AAD3-601F101C38F6' 

APP_PATH = ('/Library/Developer/CoreSimulator/Volumes/iOS_23D8133/Library/Developer/CoreSimulator/Profiles/Runtimes/iOS 26.3.simruntime/Contents/Resources/RuntimeRoot/Applications/News.app')

options = XCUITestOptions()
options.app = APP_PATH
options.device_name = device_name_and_os
options.udid = udid
options.platform_version = device_os
options.no_reset = True

driver = webdriver.Remote(command_executor='http://localhost:4723', options=options)

print("\n=== PAGE SOURCE (pretty-printed) ===\n")
raw = driver.page_source
try:
    pretty = xml.dom.minidom.parseString(raw).toprettyxml(indent="  ")
    print(pretty[:20000])  # first 20k chars
except Exception:
    print(raw[:20000])

print("\n=== ALL ELEMENT TYPES PRESENT ===")
import re
types = sorted(set(re.findall(r'type="([^"]+)"', raw)))
for t in types:
    print(" ", t)

print("\n=== ELEMENTS WITH 'story' or 'news' IN LABEL/NAME (case-insensitive) ===")
for match in re.finditer(r'<[^>]*(label|name|value)="([^"]*(?:story|stories|news|top|trending)[^"]*)"[^>]*>', raw, re.IGNORECASE):
    print(" ", match.group(0)[:200])

driver.quit()
