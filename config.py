# config.py — loads real config if present, otherwise falls back to demo values
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
