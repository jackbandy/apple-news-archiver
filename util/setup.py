import os
import re
import json
import time
import socket
import subprocess
from shutil import rmtree
from glob import glob


# WebDriverAgent serves its HTTP control interface on this port while an
# XCUITest/XCTest automation session is alive.
WDA_PORT = 8100


# Path where Xcode caches WDA DerivedData from source builds.
_WDA_DERIVED_DATA_PATTERN = os.path.expanduser(
    '~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*'
)

# Appium ships a prebuilt WDA bundle alongside the xcuitest-driver package.
# Its xctestrun files live at this path relative to the driver installation.
# e.g. WebDriverAgentRunner_iphonesimulator26.4-arm64.xctestrun
_APPIUM_PREBUILT_GLOB = os.path.expanduser(
    '~/.appium/node_modules/appium-xcuitest-driver/node_modules/Build/Products/*.xctestrun'
)

# Appium embeds the target SDK in the xctestrun filename, e.g.:
#   WebDriverAgentRunner_iphonesimulator26.4-arm64.xctestrun
# We parse this to detect iOS SDK version mismatches before connecting.
# Check both Appium's prebuilt location and any local DerivedData builds.
def _all_xctestrun_files():
    return glob(_APPIUM_PREBUILT_GLOB) + glob(
        os.path.join(_WDA_DERIVED_DATA_PATTERN, 'Build/Products/*.xctestrun')
    )


def wda_needs_reinstall(target_udid):
    '''Return True if Appium should reinstall WDA before the next session.

    Detection logic:
      1. Collect xctestrun files from Appium's prebuilt bundle directory and
         from Xcode DerivedData (if a local source build exists).
         If none exist anywhere, WDA has never been set up → needs reinstall.
      2. Ask the simulator what iOS version it is running (xcrun simctl).
      3. Compare that version to the SDK versions embedded in the xctestrun
         filenames (e.g. "iphonesimulator26.4" → "26.4").
         If none match, the cached bundle targets a different runtime → needs
         reinstall.

    When this function returns True, callers should set the Appium capability
    useNewWDA=True so Appium reinstalls its prebuilt bundle on the simulator.
    Do NOT set usePrebuiltWDA=False — building WDA from source requires the
    WebDriverAgentRunner scheme to resolve simulator destinations, which may
    fail on beta Xcode versions; the prebuilt bundle is more reliable.

    On any error (simctl unavailable, unexpected filename format, etc.)
    returns False so as not to trigger an unnecessary reinstall.
    '''
    xctestrun_files = _all_xctestrun_files()
    if not xctestrun_files:
        print("wda_needs_reinstall: no xctestrun files found in Appium bundle or DerivedData")
        return True

    # Ask the simulator for its current runtime version.
    try:
        result = subprocess.run(
            ['xcrun', 'simctl', 'list', 'devices', '--json'],
            capture_output=True, text=True, check=True,
        )
        devices_json = json.loads(result.stdout)
    except Exception as e:
        print("wda_needs_reinstall: could not query simctl ({}) — skipping check".format(e))
        return False

    # Find the runtime key for our target UDID.
    # Runtime keys look like "com.apple.CoreSimulator.SimRuntime.iOS-26-3".
    sim_version = None
    for runtime_key, device_list in devices_json.get('devices', {}).items():
        for device in device_list:
            if device.get('udid') == target_udid:
                m = re.search(r'iOS-(\d+)-(\d+)', runtime_key)
                if m:
                    sim_version = '{}.{}'.format(m.group(1), m.group(2))
                break
        if sim_version:
            break

    if not sim_version:
        print("wda_needs_reinstall: could not find simulator {} in simctl output — skipping check".format(target_udid))
        return False

    # Check whether any xctestrun was compiled for the current SDK.
    # Filename format: WebDriverAgentRunner_iphonesimulator<SDK>-<arch>.xctestrun
    for path in xctestrun_files:
        basename = os.path.basename(path)
        if 'iphonesimulator{}'.format(sim_version) in basename:
            return False  # a matching bundle exists

    # All found xctestrun files target a different SDK.
    built_versions = [os.path.basename(p) for p in xctestrun_files]
    print("wda_needs_reinstall: simulator is iOS {} but WDA bundles are for: {}".format(
        sim_version, built_versions))
    return True


# Keep the old name as an alias so existing callers (backfill scripts) still work.
wda_needs_rebuild = wda_needs_reinstall


def clear_wda_derived_data():
    '''Delete WDA DerivedData source-build directories.

    Safe to call even if no DerivedData exists (glob returns empty list).
    This only removes locally built (from-source) artifacts in
    ~/Library/Developer/Xcode/DerivedData/; it does NOT touch Appium's
    prebuilt WDA bundle under ~/.appium/.
    '''
    for path in glob(_WDA_DERIVED_DATA_PATTERN):
        try:
            rmtree(path)
            print("clear_wda_derived_data: removed {}".format(path))
        except Exception as e:
            print("clear_wda_derived_data: could not remove {} ({})".format(path, e))


def wait_for_wda_teardown(port=WDA_PORT, host='127.0.0.1', timeout=30):
    '''Block until WebDriverAgent stops accepting connections on `port`.

    A live WDA session keeps an XCTest automation session (XCTAutomationSession)
    open inside the simulator. Starting a new XCUITest session while a previous
    one is still tearing down races SpringBoard's accessibility-automation
    init and can crash SpringBoard. Callers wait here so only one automation
    session is being set up or torn down at a time.

    Returns True once the port is refused (teardown complete), or False if it is
    still open after `timeout` seconds (caller may proceed anyway).
    '''
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            sock.connect((host, port))
        except OSError:
            # Connection refused/unreachable → no live WDA session.
            sock.close()
            return True
        else:
            # Port still open → previous session not yet torn down.
            sock.close()
            time.sleep(1)
    print("wait_for_wda_teardown: WDA still listening on {}:{} after {}s".format(
        host, port, timeout))
    return False


def relaunch_simulator(udid):
    '''Shut the simulator down to clear SpringBoard's accessibility/automation state.

    Shutting down tears down XCTAutomationSession state that accumulates across
    runs and can crash SpringBoard on the next session. Appium will boot a fresh
    simulator when the next session starts, so we don't re-boot here — re-booting
    would leave a dangling open window when device rotation picks a different UDID
    next run. All failures are non-fatal.
    '''
    subprocess.run(['xcrun', 'simctl', 'shutdown', udid],
                   check=False, capture_output=True)


def wipe_app_data_folder(path):
    for f in os.listdir(path):
        full = '{}/{}'.format(path, f)
        if os.path.isfile(full):
            os.remove(full)
        else:
            rmtree(full)
