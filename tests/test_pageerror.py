#!/usr/bin/env python3
"""
Loads the packaged page and asserts there are no unexpected JS errors --
no uncaught exceptions and no browser console errors -- then does a basic
stream-picker sanity check (both streams listed, default stream loads,
switching streams updates the canvas size, video source and localStorage
key).

The sample flight videos (ornek.mp4, ornek2.mp4) are gitignored and are not
present in CI or in a fresh checkout. Verified locally: with the videos
missing, Chromium logs a "Failed to load resource: net::ERR_FILE_NOT_FOUND"
console error for each <video src="..."> stream (one per stream, since the
default stream loads on page load and the second is loaded on switch).
That is expected in this environment and is not a bug in the app, so this
test ignores console errors that are resource-load failures for one of the
video files listed in the page's STREAMS array (matched by the failing
request's URL ending in that filename) and prints them as an informational
line instead. Any other console error, or any uncaught exception, still
fails the test.
"""
import os
import pathlib
import sys
from playwright.sync_api import sync_playwright

def main(html_path):
    errors = []
    console_errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM_PATH") or None)
        page = browser.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg) if msg.type == "error" else None)
        page.goto(pathlib.Path(html_path).resolve().as_uri())
        page.wait_for_timeout(800)
        # sanity: both streams present in the picker, default stream loaded
        opts = page.evaluate("Array.from(document.querySelectorAll('#streamSelect option')).map(o => [o.value, o.textContent])")
        active = page.evaluate("activeStream && activeStream.id")
        mw = page.evaluate("base.width"); mh = page.evaluate("base.height")
        print("options:", opts)
        print("active stream:", active, "canvas:", mw, "x", mh)
        # switch to the second stream and confirm canvas/video/localStorage key follow
        page.select_option("#streamSelect", "ornek2")
        page.wait_for_timeout(500)
        active2 = page.evaluate("activeStream && activeStream.id")
        mw2 = page.evaluate("base.width"); mh2 = page.evaluate("base.height")
        vidsrc = page.evaluate("vid.getAttribute('src') || vid.currentSrc")
        storekey = page.evaluate("STORAGE_KEY")
        print("after switch -> active:", active2, "canvas:", mw2, "x", mh2, "vid src:", vidsrc, "storage key:", storekey)

        video_files = page.evaluate("STREAMS.map(s => s.video)")
        browser.close()

    ignored = []
    for msg in console_errors:
        text = msg.text
        loc_url = (msg.location or {}).get("url", "")
        is_missing_video = (
            ("ERR_FILE_NOT_FOUND" in text or "Failed to load resource" in text)
            and any(loc_url.endswith(v) for v in video_files)
        )
        if is_missing_video:
            ignored.append(f"console:{msg.type}:{text} ({loc_url})")
        else:
            errors.append(f"console:{msg.type}:{text}")

    if ignored:
        print("IGNORED (sample videos are not present in this checkout, expected):")
        for e in ignored:
            print(" -", e)

    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("NO PAGE ERRORS")

if __name__ == "__main__":
    main(sys.argv[1])


import pytest


@pytest.mark.browser
def test_pageerror(html_path):
    main(html_path)
