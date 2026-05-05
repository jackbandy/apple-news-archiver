# config-demo.py — template for public use
# Copy this to config-real.py and fill in your values.

# Devices to rotate through. Each run picks the next device in order.
# Format: (name, os_version, udid)
# To use a single device, just list one entry.
DEVICES = [
    ('iPhone 17 Pro Max', '18.0', 'YOUR-SIMULATOR-UDID-HERE'),
]

# Active device — set automatically by config.py rotation logic
device_name_and_os = DEVICES[0][0]
device_os = DEVICES[0][1]
udid = DEVICES[0][2]

# Output paths
output_folder = 'data_output'
output_file = 'data_output/stories.csv'

# Set True to navigate into the Top Stories view and collect ranked stories there
COLLECT_TOP_STORIES = False

# Full path to the News.app bundle inside the simulator runtime.
# Find yours by running:
#   find ~/Library/Developer/CoreSimulator -name "News.app" 2>/dev/null
APP_PATH = '/path/to/your/simulator/News.app'

# Layout / collection tuning
MIN_STORY_CELL_HEIGHT = 60
TAB_BAR_HEIGHT = 83   # standard iOS tab bar height in points
SAFE_TAP_MARGIN = 30  # extra buffer above tab bar
MAX_TOP_STORIES = 10  # used by collect_top_stories_view (COLLECT_TOP_STORIES=True mode)

# Per-section caps for collect_home_page
MAX_TOP_HOME = 7          # total top stories including plus and audio rows
MAX_READER_FAVORITES = 4  # reader favorites appearing before the next header
MAX_POPULAR_STORIES = 5   # "Popular in News+" stories
MAX_TRENDING = 4          # trending stories

# Maximum wall-clock seconds a single run may take before it is killed (0 = no limit)
MAX_RUN_SECONDS = 900     # 15 minutes
