#!/usr/bin/env python3
"""
Exercises the multi-stream picker: switching streams reconfigures the mosaic
canvas size, video source, and zoom/pan/follow state, and each stream's
tactical markers stay in their own localStorage bucket.
"""
import sys
from playwright.sync_api import sync_playwright

def main(html_path):
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = browser.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.goto(f"file://{html_path}")
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

        browser.close()

    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("ALL STREAM-SWITCH TESTS PASSED, no page errors")

if __name__ == "__main__":
    main(sys.argv[1])
