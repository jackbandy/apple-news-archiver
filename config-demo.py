# config-demo.py — template for public use
# Copy this to config-real.py and fill in your values.

# Simulator device settings (update via: xcrun simctl list devices)
device_name_and_os = 'iPhone 17 Pro Max'
device_os = '18.0'
udid = 'YOUR-SIMULATOR-UDID-HERE'

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
MAX_TOP_STORIES = 10
