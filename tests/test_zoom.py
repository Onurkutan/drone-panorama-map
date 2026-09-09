#!/usr/bin/env python3
"""
Exercises mouse-wheel / button zoom: wheel zoom changes the zoom level and
keeps the point under the cursor fixed, the toolbar buttons work, follow
still targets the right spot at non-1x zoom, and a marker placed at a known
screen point lands at the same mosaic-pixel coordinate regardless of zoom.
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
        page.evaluate("follow = false; document.getElementById('mosaicWrap').scrollLeft = 0; document.getElementById('mosaicWrap').scrollTop = 0;")
        page.click("#videoToggleBtn")  # hide the PIP so it can't intercept clicks
        page.wait_for_timeout(100)

        # 1) zoom buttons change the reported zoom level
        z0 = page.evaluate("zoom")
        page.click("#zoomInBtn")
        z1 = page.evaluate("zoom")
        assert z1 > z0
        assert page.evaluate("document.getElementById('zoomLabel').textContent") == f"{round(z1 * 100)}%"

        page.click("#zoomOutBtn")
        page.click("#zoomOutBtn")
        z2 = page.evaluate("zoom")
        assert z2 < z1

        # 2) reset goes back to exactly 100%
        page.click("#zoomResetBtn")
        assert page.evaluate("zoom") == 1
        assert page.evaluate("document.getElementById('zoomLabel').textContent") == "100%"

        # 3) wheel zoom is anchored under the cursor
        wrap = page.locator("#mosaicWrap")
        wbox = wrap.bounding_box()
        cx, cy = wbox["x"] + wbox["width"] * 0.5, wbox["y"] + wbox["height"] * 0.5
        z_before = page.evaluate("zoom")
        content_before = page.evaluate(
            "([cx, cy]) => { const w = document.getElementById('mosaicWrap'); const r = w.getBoundingClientRect(); "
            "return [w.scrollLeft + (cx - r.left), w.scrollTop + (cy - r.top)]; }", [cx, cy])
        mosaic_before = [content_before[0] / z_before, content_before[1] / z_before]
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -400)  # negative deltaY = zoom in
        page.wait_for_timeout(100)
        z3 = page.evaluate("zoom")
        assert z3 > z_before
        content_after = page.evaluate(
            "([cx, cy]) => { const w = document.getElementById('mosaicWrap'); const r = w.getBoundingClientRect(); "
            "return [w.scrollLeft + (cx - r.left), w.scrollTop + (cy - r.top)]; }", [cx, cy])
        mosaic_after = [content_after[0] / z3, content_after[1] / z3]
        dx = abs(mosaic_after[0] - mosaic_before[0])
        dy = abs(mosaic_after[1] - mosaic_before[1])
        assert dx < 2 and dy < 2

        # 4) a marker placed at a known screen point lands at the same
        # mosaic-pixel coordinate at 100% zoom vs. zoomed in
        page.click("#zoomResetBtn")
        canvas = page.locator("#tacticalCanvas")
        box = canvas.bounding_box()
        screen_x, screen_y = box["x"] + 222, box["y"] + 133
        page.click('[data-tool="marker"]')
        page.mouse.click(screen_x, screen_y)
        pt_at_100 = page.evaluate("tacticalItems[tacticalItems.length - 1]")
        mosaic_x_100, mosaic_y_100 = pt_at_100["x"], pt_at_100["y"]

        page.click("#zoomInBtn")
        page.click("#zoomInBtn")
        box2 = canvas.bounding_box()
        ratio = page.evaluate(
            "() => { const c = document.getElementById('tacticalCanvas'); const r = c.getBoundingClientRect(); return r.width / c.width; }")
        target_screen_x = box2["x"] + mosaic_x_100 * ratio
        target_screen_y = box2["y"] + mosaic_y_100 * ratio
        page.mouse.click(target_screen_x, target_screen_y)
        pt_at_zoom = page.evaluate("tacticalItems[tacticalItems.length - 1]")
        ddx = abs(pt_at_zoom["x"] - mosaic_x_100)
        ddy = abs(pt_at_zoom["y"] - mosaic_y_100)
        assert ddx < 2 and ddy < 2

        # 5) follow converges toward the zoom-scaled drone position
        def gap():
            return page.evaluate("""
                () => {
                    const s = interpAt(vid.currentTime);
                    const wrap = document.getElementById('mosaicWrap');
                    const targetLeft = s.center[0] * zoom - wrap.clientWidth / 2;
                    const targetTop = s.center[1] * zoom - wrap.clientHeight / 2;
                    return Math.hypot(wrap.scrollLeft - targetLeft, wrap.scrollTop - targetTop);
                }
            """)
        page.evaluate("follow = true;")
        page.wait_for_timeout(50)
        gap_before = gap()
        page.wait_for_timeout(500)
        gap_after = gap()
        assert gap_after < gap_before

        # cleanup
        page.click('[data-tool="select"]')
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
        print("ALL ZOOM TESTS PASSED, no page errors")

if __name__ == "__main__":
    main(sys.argv[1])


import pytest


@pytest.mark.browser
def test_zoom(html_path):
    main(html_path)
