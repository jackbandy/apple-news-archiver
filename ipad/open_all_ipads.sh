#!/bin/bash
# Boot all iPad simulators defined in ipad_config_real.py

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Extract UDIDs from the config (third element of each DEVICES tuple)
UDIDS=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from ipad_config_real import DEVICES
for name, os_ver, udid in DEVICES:
    print(udid, name)
")

echo "Booting simulators..."
while IFS= read -r line; do
    udid=$(echo "$line" | awk '{print $1}')
    name=$(echo "$line" | cut -d' ' -f2-)
    xcrun simctl boot "$udid" 2>/dev/null && echo "  Booted: $name" || echo "  Already booted or failed: $name"
done <<< "$UDIDS"

echo "Opening Simulator.app..."
open -a Simulator

echo "Done."
