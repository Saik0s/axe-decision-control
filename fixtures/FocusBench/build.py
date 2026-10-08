#!/usr/bin/env python3
"""Build an ad hoc signed iOS Simulator fixture using the active Xcode SDK.

Run with: uv run --no-project fixtures/FocusBench/build.py --output <directory>
This only builds FocusBench.app; it does not install or launch it.
"""

from __future__ import annotations

import argparse
import platform
import plistlib
import subprocess
from pathlib import Path

BUNDLE_ID = "dev.axecontrol.focusbench"
MINIMUM_IOS = "17.0"
PlistValue = str | list[str] | list[int] | dict[str, bool]


def xcrun_value(*arguments: str) -> str:
    result = subprocess.run(
        ["xcrun", *arguments], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def build(output: Path) -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("FocusBench requires macOS and Xcode command line tools.")
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise RuntimeError("Unsupported simulator host architecture.")

    sdk = xcrun_value("--sdk", "iphonesimulator", "--show-sdk-path")
    sdk_version = xcrun_value("--sdk", "iphonesimulator", "--show-sdk-version")
    source = Path(__file__).resolve().with_name("FocusBench.swift")
    output = output.expanduser().resolve()
    app = output / "FocusBench.app"
    app.mkdir(parents=True, exist_ok=True)
    target = f"{architecture}-apple-ios{MINIMUM_IOS}-simulator"

    subprocess.run(
        [
            "xcrun", "--sdk", "iphonesimulator", "swiftc",
            "-parse-as-library", "-swift-version", "6",
            "-strict-concurrency=complete", "-warnings-as-errors",
            "-target", target, "-sdk", sdk,
            "-module-cache-path", str(output / "module-cache"),
            "-Xlinker", "-syslibroot", "-Xlinker", sdk,
            str(source), "-o", str(app / "FocusBench"),
            "-framework", "SwiftUI",
        ],
        check=True,
    )

    info: dict[str, PlistValue] = {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "FocusBench",
        "CFBundleName": "FocusBench",
        "CFBundleDisplayName": "FocusBench",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
        "DTSDKName": f"iphonesimulator{sdk_version}",
        "MinimumOSVersion": MINIMUM_IOS,
        "UIDeviceFamily": [1, 2],
        "UILaunchScreen": {},
        "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False},
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight",
        ],
    }
    with (app / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)

    # Finder metadata on generated bundles can otherwise make ad hoc signing fail.
    subprocess.run(["xattr", "-cr", str(app)], check=True)
    subprocess.run(
        ["codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
        check=True,
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)], check=True
    )
    print(f"Built {app}\nBundle: {BUNDLE_ID}\nTarget: {target}\nSDK: {sdk}")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Directory for FocusBench.app and the compiler module cache.",
    )
    arguments = parser.parse_args()
    build(arguments.output)


if __name__ == "__main__":
    main()
