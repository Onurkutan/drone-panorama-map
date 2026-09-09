#!/usr/bin/env python3
"""
Exercises the multi-stream picker: switching streams reconfigures the mosaic
canvas size, video source, and zoom/pan/follow state, and each stream's
tactical markers stay in their own localStorage bucket.
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
        page.wait_for_timeout(500)

        for sid in ("ornek", "ornek2"):
            page.evaluate(
                "(id) => { try { localStorage.removeItem('drone_tactical_v1_' + id); } catch(e){} }", sid)
        page.reload()
        page.wait_for_timeout(500)

        # 1) picker lists every stream, first one loads by default
        opts = page.evaluate("Array.from(document.querySelectorAll('#streamSelect option')).map(o => o.value)")
        assert len(opts) >= 2
        first_id = opts[0]
        assert page.evaluate("activeStream.id") == first_id

        stream_dims = {}
        for sid in opts:
            stream_dims[sid] = page.evaluate(
                "(id) => { const s = STREAMS.find(x => x.id === id); return [s.mosaic_width, s.mosaic_height]; }", sid)
        assert len(set(map(tuple, stream_dims.values()))) > 1

        # 2) place a marker on the first stream
        page.evaluate(
            "follow = false; document.getElementById('mosaicWrap').scrollLeft = 0; "
            "document.getElementById('mosaicWrap').scrollTop = 0;")
        page.wait_for_timeout(100)
        page.click('[data-tool="marker"]')
        canvas = page.locator("#tacticalCanvas")
        box = canvas.bounding_box()
        page.mouse.click(box["x"] + 80, box["y"] + 80)
        n_first = page.evaluate("tacticalItems.length")
        assert n_first == 1

        # 3) switch to the second stream via the dropdown
        second_id = opts[1]
        page.select_option("#streamSelect", second_id)
        page.wait_for_timeout(100)
        page.evaluate(
            "follow = false; document.getElementById('mosaicWrap').scrollLeft = 0; "
            "document.getElementById('mosaicWrap').scrollTop = 0;")
        page.wait_for_timeout(100)

        assert page.evaluate("activeStream.id") == second_id
        w, h = page.evaluate("[base.width, base.height]")
        assert [w, h] == list(stream_dims[second_id])
        vid_src = page.evaluate("vid.getAttribute('src')")
        expected_video = page.evaluate("(id) => STREAMS.find(x => x.id === id).video", second_id)
        assert vid_src == expected_video
        assert page.evaluate("zoom") == 1
        n_second = page.evaluate("tacticalItems.length")
        assert n_second == 0

        # 4) place a different marker on the second stream, then switch back
        box2 = canvas.bounding_box()
        page.mouse.click(box2["x"] + 120, box2["y"] + 60)
        n_second_after = page.evaluate("tacticalItems.length")
        assert n_second_after == 1

        page.select_option("#streamSelect", first_id)
        page.wait_for_timeout(300)
        assert page.evaluate("activeStream.id") == first_id
        n_first_again = page.evaluate("tacticalItems.length")
        assert n_first_again == 1

        # cleanup
        page.once("dialog", lambda d: d.accept())
        page.click("#clearAllBtn")
        page.select_option("#streamSelect", second_id)
        page.wait_for_timeout(200)
        page.once("dialog", lambda d: d.accept())
        page.click("#clearAllBtn")

        video_files = page.evaluate("STREAMS.map(s => s.video)")
        browser.close()

    # The sample flight videos are gitignored and not present in CI or a
    # fresh checkout, so Chromium logs a resource-load console error for
    # each missing <video src="...">. That is expected here (see
    # test_pageerror.py for the verified details) -- ignore only those,
    # matched against the video filenames from STREAMS, and fail on
    # anything else.
    for msg in console_errors:
        text = msg.text
        loc_url = (msg.location or {}).get("url", "")
        is_missing_video = (
            ("ERR_FILE_NOT_FOUND" in text or "Failed to load resource" in text)
            and any(loc_url.endswith(v) for v in video_files)
        )
        if is_missing_video:
            print(f"IGNORED (sample video not present in this checkout): console:{msg.type}:{text} ({loc_url})")
        else:
            errors.append(f"console:{msg.type}:{text}")

    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("ALL STREAM-SWITCH TESTS PASSED, no page errors")

if __name__ == "__main__":
    main(sys.argv[1])


import pytest


@pytest.mark.browser
def test_stream_switch(html_path):
    main(html_path)
