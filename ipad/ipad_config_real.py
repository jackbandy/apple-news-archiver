DEVICES = [
    ('iPad Pro 13-inch (M5)',  '26.4', 'FF9083CB-A60A-49BB-B11B-83B4C513FF03'),
    ('iPad Pro 11-inch (M5)',  '26.4', '3BAC2550-2E81-45DD-BAA4-F4B5AD87762D'),
('iPad Air 13-inch (M4)', '26.4', '752178B2-3C35-40FA-977F-3484C4708B46'),
    ('iPad Air 11-inch (M4)', '26.4', '5E305E79-D3B2-46EB-B3B0-20568E728086'),
    ('iPad (A16)',             '26.4', '7FC4D4BE-FBC3-4B5A-A2A9-4FD9366939BD'),
]

# Active device — set by rotation logic
device_name_and_os = DEVICES[0][0]
device_os = DEVICES[0][1]
udid = DEVICES[0][2]

APP_PATH = '/Library/Developer/CoreSimulator/Volumes/iOS_23E244/Library/Developer/CoreSimulator/Profiles/Runtimes/iOS 26.4.simruntime/Contents/Resources/RuntimeRoot/Applications/News.app'

output_folder = 'data_output_ipad'
output_file = 'data_output_ipad/stories.csv'

HEADLESS_SIMULATOR = False

MAX_RUN_SECONDS = 900

# Layout / collection tuning (landscape, 3-column feed).
MIN_STORY_CELL_HEIGHT = 100  # ignore chrome/promo cells shorter than a story card
CONTENT_X_MIN = 300          # content area starts at x=320; sidebar is x=0-280
MAX_PASSES = 12              # max scroll passes through the feed
