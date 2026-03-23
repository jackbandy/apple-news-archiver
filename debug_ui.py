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

from config import device_name_and_os, device_os, udid, APP_PATH

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
