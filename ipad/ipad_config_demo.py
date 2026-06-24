# ipad_config_demo.py — template for iPad scraper config
# Copy this to ipad_config_real.py and fill in your values.

# iPad simulators to rotate through.
# Format: (name, os_version, udid)
# Find UDIDs with: xcrun simctl list devices | grep -i ipad
DEVICES = [
    ('iPad Pro 13-inch (M5)',  '26.4', 'YOUR-UDID-HERE'),
    ('iPad Pro 11-inch (M5)',  '26.4', 'YOUR-UDID-HERE'),
    ('iPad mini (A17 Pro)',    '26.4', 'YOUR-UDID-HERE'),
    ('iPad Air 13-inch (M4)', '26.4', 'YOUR-UDID-HERE'),
    ('iPad Air 11-inch (M4)', '26.4', 'YOUR-UDID-HERE'),
    ('iPad (A16)',             '26.4', 'YOUR-UDID-HERE'),
]

# Active device — set by rotation logic
device_name_and_os = DEVICES[0][0]
device_os = DEVICES[0][1]
udid = DEVICES[0][2]

# Full path to the News.app bundle inside the simulator runtime.
# Find yours with: find ~/Library/Developer/CoreSimulator -name "News.app" 2>/dev/null
APP_PATH = '/path/to/your/simulator/News.app'

output_folder = 'data_output_ipad'
output_file = 'data_output_ipad/stories.csv'

# Run the simulator without a visible window
HEADLESS_SIMULATOR = True

# Maximum wall-clock seconds a single run may take before it is killed (0 = no limit)
MAX_RUN_SECONDS = 900

# Layout / collection tuning (landscape, 3-column feed).
MIN_STORY_CELL_HEIGHT = 100  # ignore chrome/promo cells shorter than a story card
CONTENT_X_MIN = 300          # content area starts at x=320; sidebar is x=0-280
MAX_PASSES = 12              # max scroll passes through the feed
