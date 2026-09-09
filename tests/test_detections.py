#!/usr/bin/env python3
"""
Tests the vehicle detection layer: nothing shows until playback reaches it,
the toggle hides/shows revealed boxes, the "remove false detections" mode
works and persists per stream, and none of it touches tacticalItems.

Video playback can't run headless here, so revealDetectionsUpTo(t) is
called directly instead of relying on real playback (same approach
test_zoom.py uses for interpAt()).
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
        page.wait_for_timeout(600)

        for sid in ("ornek", "ornek2"):
            page.evaluate(
                "(id) => { try { localStorage.removeItem('drone_removed_detections_v1_' + id); } catch(e){} }", sid)
        page.reload()
        page.wait_for_timeout(600)

        # 1) detections loaded, matching the embedded data
        n_active = page.evaluate("activeDetections.length")
        n_stream = page.evaluate("STREAMS.find(s => s.id === activeStream.id).detections.length")
        assert n_active == n_stream and n_active > 0

        # 2) nothing revealed on a fresh, paused load
        assert page.evaluate("revealedDetIds.size") == 0
        assert page.evaluate("detRevealPtr") == 0
        pixels_before = page.evaluate(
            "() => { const c = document.getElementById('detectionsCanvas'); const ctx = c.getContext('2d'); "
            "return ctx.getImageData(0, 0, c.width, c.height).data.some(v => v !== 0); }")
        assert not pixels_before
        assert page.evaluate("document.getElementById('detCountLabel').textContent") == f"(0/{n_active})"

        # 3) revealDetectionsUpTo(large t) reveals everything
        page.evaluate("revealDetectionsUpTo(1e9)")
        assert page.evaluate("revealedDetIds.size") == n_active
        pixels_after = page.evaluate(
            "() => { const c = document.getElementById('detectionsCanvas'); const ctx = c.getContext('2d'); "
            "return ctx.getImageData(0, 0, c.width, c.height).data.some(v => v !== 0); }")
        assert pixels_after
        assert page.evaluate("document.getElementById('detCountLabel').textContent") == f"({n_active}/{n_active})"

        # 4) partial reveal at an earlier t
        page.evaluate("loadStream(activeStream.id)")
        assert page.evaluate("revealedDetIds.size") == 0
        first_t_reveal = page.evaluate("Math.min(...activeDetections.map(d => d.t_reveal))")
        page.evaluate("(t) => revealDetectionsUpTo(t)", first_t_reveal)
        n_partial = page.evaluate("revealedDetIds.size")
        assert 0 < n_partial <= n_active

        # 5) detections stay separate from tacticalItems
        assert page.evaluate("tacticalItems.length") == 0

        # 6) toggle hides/shows revealed boxes without touching revealedDetIds
        page.evaluate("revealDetectionsUpTo(1e9)")
        assert page.evaluate("showDetections") is True
        page.click("#detToggleBtn")
        assert page.evaluate("showDetections") is False
        pixels_hidden = page.evaluate(
            "() => { const c = document.getElementById('detectionsCanvas'); const ctx = c.getContext('2d'); "
            "return ctx.getImageData(0, 0, c.width, c.height).data.some(v => v !== 0); }")
        assert not pixels_hidden
        assert "Off" in page.evaluate("document.getElementById('detToggleBtn').textContent")
        page.click("#detToggleBtn")
        assert page.evaluate("showDetections") is True

        # 7) remove-mode: click a revealed box, confirm removal + persistence
        first_det = page.evaluate("activeDetections[0]")
        det_id = first_det["id"]
        cx, cy = first_det["x"] + first_det["w"] / 2, first_det["y"] + first_det["h"] / 2
        page.click("#detEditBtn")
        assert page.evaluate("detEditMode") is True
        assert "On" in page.evaluate("document.getElementById('detEditBtn').textContent")

        canvas = page.locator("#tacticalCanvas")
        box = canvas.bounding_box()
        ratio = page.evaluate(
            "() => { const c = document.getElementById('tacticalCanvas'); const r = c.getBoundingClientRect(); return r.width / c.width; }")
        page.mouse.click(box["x"] + cx * ratio, box["y"] + cy * ratio)

        assert page.evaluate("(id) => removedDetIds.has(id)", det_id)
        assert page.evaluate("removedDetIds.size") == 1
        assert "1" in page.evaluate("document.getElementById('detRestoreBtn').textContent")

        # clicking in edit mode must not touch tacticalItems
        assert page.evaluate("tacticalItems.length") == 0
        assert page.evaluate("selectedId") is None

        # removal persists across a stream reload
        page.evaluate("loadStream(activeStream.id)")
        assert page.evaluate("removedDetIds.size") == 1
        page.evaluate("revealDetectionsUpTo(1e9)")
        assert not page.evaluate("(id) => revealedDetIds.has(id)", det_id)
        assert page.evaluate("document.getElementById('detCountLabel').textContent") == f"({n_active - 1}/{n_active - 1})"

        # loadStream() resets edit mode off
        assert page.evaluate("detEditMode") is False
        assert "Off" in page.evaluate("document.getElementById('detEditBtn').textContent")
        page.click("#detRestoreBtn")
        assert page.evaluate("removedDetIds.size") == 0

        # 8) switching streams loads that stream's own detections
        opts = page.evaluate("STREAMS.map(s => s.id)")
        if len(opts) >= 2:
            page.select_option("#streamSelect", opts[1])
            page.wait_for_timeout(200)
            second_dets = page.evaluate("activeDetections.length")
            second_expected = page.evaluate(
                "(id) => STREAMS.find(s => s.id === id).detections.length", opts[1])
            assert second_dets == second_expected
            assert page.evaluate("revealedDetIds.size") == 0
            assert page.evaluate("removedDetIds.size") == 0
            assert page.evaluate("tacticalItems.length") == 0

        for sid in ("ornek", "ornek2"):
            page.evaluate(
                "(id) => { try { localStorage.removeItem('drone_removed_detections_v1_' + id); } catch(e){} }", sid)

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
        print("ALL DETECTION-LAYER TESTS PASSED, no page errors")

if __name__ == "__main__":
    main(sys.argv[1])


import pytest


@pytest.mark.browser
def test_detections(html_path):
    main(html_path)
