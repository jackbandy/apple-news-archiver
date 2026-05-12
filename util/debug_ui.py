'''
debug_ui.py

Dumps the current accessibility tree from the running Appium session.
Run this while the Apple News app is open to inspect available elements.
Usage: .venv/bin/python util/debug_ui.py
'''

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from appium.webdriver.common.appiumby import AppiumBy
import xml.dom.minidom

from config import device_name_and_os, device_os, udid, APP_PATH
from util.appium_session import start_driver

driver = start_driver(
    app_path=APP_PATH,
    device_name=device_name_and_os,
    udid=udid,
    platform_version=device_os,
)

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
