# config.py — loads real config if present, otherwise falls back to demo values.
# When DEVICES is defined, rotates to the next device each run.

import os

try:
    from config_real import *
except ImportError:
    from config_demo import *
    print(
        "\nERROR: No config-real.py found.\n"
        "Copy config-demo.py to config-real.py and fill in your device UDID,\n"
        "device name, OS version, and News.app path before running.\n"
    )
    exit(1)

# --- Device rotation ---
# If DEVICES is defined (list of (name, os, udid) tuples), rotate through them.
# Each cycle through all devices uses a random order.  The shuffled queue is
# persisted in _ROTATION_FILE as a JSON list of indices.

import json
import random

_ROTATION_FILE = os.path.join(os.path.dirname(__file__), '.device_rotation')

def _rotate_device():
    global device_name_and_os, device_os, udid

    try:
        devices = DEVICES
    except NameError:
        return  # single-device config, nothing to rotate

    if len(devices) <= 1:
        return

    # Load remaining queue from state file
    queue = []
    if os.path.exists(_ROTATION_FILE):
        try:
            with open(_ROTATION_FILE) as f:
                queue = json.load(f)
        except (ValueError, OSError):
            queue = []

    # If queue is empty or invalid, start a new shuffled cycle
    if not queue or not all(isinstance(i, int) and 0 <= i < len(devices) for i in queue):
        queue = list(range(len(devices)))
        random.shuffle(queue)

    # Pop the next device
    pick = queue.pop(0)

    # Save remaining queue (empty list means next run starts a fresh shuffle)
    try:
        with open(_ROTATION_FILE, 'w') as f:
            json.dump(queue, f)
    except OSError:
        pass

    device_name_and_os, device_os, udid = devices[pick]


_rotate_device()
