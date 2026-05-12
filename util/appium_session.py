"""
util/appium_session.py

Shared Appium + XCUITest session helpers.

Goal: keep all the fiddly XCUITest/WDA startup capabilities in one place so
`get_stories.py`, `util/debug_ui.py`, and any Appium-based backfill tooling
behave consistently across Xcode/iOS runtime changes.
"""

import os

from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions


def build_xcuitest_options(
    *,
    app_path,
    device_name,
    udid,
    platform_version,
    rebuild_wda=False,
    no_reset=True,
):
    """
    Construct XCUITestOptions with the repo's standard WDA bootstrapping.

    `rebuild_wda=True` sets `useNewWDA` so Appium reinstalls the prebuilt WDA
    bundle on the simulator.
    """
    options = XCUITestOptions()
    options.app = app_path
    options.device_name = device_name
    options.udid = udid
    options.platform_version = platform_version
    options.no_reset = no_reset

    # Keep behavior consistent with get_stories.py: enable Location Services/GPS.
    options.set_capability("locationServicesEnabled", True)
    options.set_capability("gpsEnabled", True)

    # Prefer Appium's prebuilt WDA bundle via xctestrun to avoid Xcode scheme/
    # destination resolution issues on newer runtimes/betas.
    wda_products = os.path.expanduser(
        "~/.appium/node_modules/appium-xcuitest-driver/node_modules/Build/Products"
    )
    options.set_capability("bootstrapPath", wda_products)
    options.set_capability("useXctestrunFile", True)

    # Give Appium reasonable time to bring up WDA.
    options.set_capability("wdaStartupRetries", 3)
    options.set_capability("wdaStartupRetryInterval", 5000)
    options.set_capability("wdaLaunchTimeout", 120000)  # 2 min
    options.set_capability("wdaConnectionTimeout", 120000)  # 2 min

    if rebuild_wda:
        options.set_capability("useNewWDA", True)

    return options


def _is_wda_connection_refused_error(exc):
    msg = str(exc)
    return (
        "127.0.0.1:8100" in msg
        and ("ECONNREFUSED" in msg or "WebDriverAgent session" in msg)
    )


def start_driver(
    *,
    app_path,
    device_name,
    udid,
    platform_version,
    rebuild_wda=False,
    command_executor="http://localhost:4723",
    retry_on_wda_refusal=True,
    clear_wda_derived_data_fn=None,
):
    """
    Start an Appium driver with the repo's standard options.

    If we see the common WDA connection-refused error, we optionally retry once
    with `rebuild_wda=True` so Appium reinstalls WDA on the simulator.
    """
    options = build_xcuitest_options(
        app_path=app_path,
        device_name=device_name,
        udid=udid,
        platform_version=platform_version,
        rebuild_wda=rebuild_wda,
    )
    try:
        return webdriver.Remote(command_executor=command_executor, options=options)
    except Exception as exc:
        if retry_on_wda_refusal and (not rebuild_wda) and _is_wda_connection_refused_error(exc):
            if clear_wda_derived_data_fn:
                try:
                    clear_wda_derived_data_fn()
                except Exception:
                    pass
            return start_driver(
                app_path=app_path,
                device_name=device_name,
                udid=udid,
                platform_version=platform_version,
                rebuild_wda=True,
                command_executor=command_executor,
                retry_on_wda_refusal=False,
                clear_wda_derived_data_fn=clear_wda_derived_data_fn,
            )
        raise
