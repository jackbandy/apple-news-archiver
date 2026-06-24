# ipad_device_loader.py — loads real iPad config if present, else the demo template.
# Mirrors config.py: rotates through DEVICES (random order each cycle) and
# fills in defaults for optional settings.

import os
import json
import random

try:
    from ipad_config_real import *
except ImportError:
    from ipad_config_demo import *
    print(
        "\nERROR: No ipad_config_real.py found.\n"
        "Copy ipad_config_demo.py to ipad_config_real.py and fill in your iPad\n"
        "UDIDs and News.app path before running.\n"
    )
    exit(1)

# --- Device rotation ---
# Each cycle through all devices uses a random order, persisted as a JSON list
# of indices in _ROTATION_FILE.

_ROTATION_FILE = os.path.join(os.path.dirname(__file__), '.device_rotation_ipad')


def _rotate_device():
    global device_name_and_os, device_os, udid

    try:
        devices = DEVICES
    except NameError:
        return

    if len(devices) <= 1:
        return

    queue = []
    if os.path.exists(_ROTATION_FILE):
        try:
            with open(_ROTATION_FILE) as f:
                queue = json.load(f)
        except (ValueError, OSError):
            queue = []

    if not queue or not all(isinstance(i, int) and 0 <= i < len(devices) for i in queue):
        queue = list(range(len(devices)))
        random.shuffle(queue)

    pick = queue.pop(0)

    try:
        with open(_ROTATION_FILE, 'w') as f:
            json.dump(queue, f)
    except OSError:
        pass

    device_name_and_os, device_os, udid = devices[pick]


_rotate_device()

# Defaults for optional settings absent from older config files.
if 'HEADLESS_SIMULATOR' not in dir():
    HEADLESS_SIMULATOR = False
if 'MIN_STORY_CELL_HEIGHT' not in dir():
    MIN_STORY_CELL_HEIGHT = 100
if 'CONTENT_X_MIN' not in dir():
    CONTENT_X_MIN = 300
if 'MAX_PASSES' not in dir():
    MAX_PASSES = 12
