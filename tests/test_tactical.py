#!/usr/bin/env python3
"""
Exercises the tactical drawing layer (markers, lines, areas, freehand, text,
measure, select/drag, delete, grid toggle, localStorage persistence) via
Playwright mouse events.
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
        # freeze the auto-follow scroll so clicks land at stable coordinates
        page.evaluate("follow = false; document.getElementById('mosaicWrap').scrollLeft = 0; document.getElementById('mosaicWrap').scrollTop = 0;")
        page.wait_for_timeout(100)

        # video PIP: drag, minimize, hide
        pip = page.locator("#videoPip")
        pip_box_before = pip.bounding_box()
        header_box = page.locator("#videoPipHeader").bounding_box()
        page.mouse.move(header_box["x"] + 60, header_box["y"] + 10)
        page.mouse.down()
        page.mouse.move(header_box["x"] + 260, header_box["y"] + 110, steps=5)
        page.mouse.up()
        pip_box_after = pip.bounding_box()
        assert (pip_box_after["x"], pip_box_after["y"]) != (pip_box_before["x"], pip_box_before["y"])

        page.click("#pipMinBtn")
        assert page.evaluate("document.getElementById('videoPip').classList.contains('minimized')")
        page.click("#pipMinBtn")
        assert not page.evaluate("document.getElementById('videoPip').classList.contains('minimized')")

        # hide the PIP so it doesn't intercept clicks meant for the canvas
        page.click("#videoToggleBtn")
        assert page.evaluate("document.getElementById('videoPip').classList.contains('hidden')")

        canvas = page.locator("#tacticalCanvas")
        box = canvas.bounding_box()
        x0, y0 = box["x"], box["y"]

        def click_at(dx, dy):
            page.mouse.click(x0 + dx, y0 + dy)

        # 1) place a marker
        page.click('[data-tool="marker"]')
        click_at(100, 100)
        n = page.evaluate("tacticalItems.length")
        assert n == 1
        assert page.evaluate("tacticalItems[0].type") == "marker"
        assert page.evaluate("tacticalItems[0].aff") == "friendly"

        # 2) switch affiliation, place a hostile marker
        page.click('[data-aff="hostile"]')
        click_at(150, 100)
        assert page.evaluate("tacticalItems[1].aff") == "hostile"

        # 3) draw a line
        page.click('[data-tool="line"]')
        click_at(50, 200)
        click_at(120, 220)
        page.mouse.dblclick(x0 + 180, y0 + 240)
        line_items = page.evaluate("tacticalItems.filter(i=>i.type==='line').length")
        assert line_items == 1
        line_pts = page.evaluate("tacticalItems.find(i=>i.type==='line').points.length")
        assert line_pts >= 3

        # 4) draw an area
        page.click('[data-tool="area"]')
        click_at(300, 300)
        click_at(360, 300)
        click_at(330, 360)
        page.mouse.dblclick(x0 + 300, y0 + 340)
        area_items = page.evaluate("tacticalItems.filter(i=>i.type==='area').length")
        assert area_items == 1

        # 5) freehand draw
        page.click('[data-tool="freehand"]')
        page.mouse.move(x0 + 400, y0 + 400)
        page.mouse.down()
        page.mouse.move(x0 + 410, y0 + 410)
        page.mouse.move(x0 + 420, y0 + 405)
        page.mouse.move(x0 + 430, y0 + 415)
        page.mouse.up()
        fh_items = page.evaluate("tacticalItems.filter(i=>i.type==='freehand').length")
        assert fh_items == 1

        # 6) text label
        page.click('[data-tool="text"]')
        page.once("dialog", lambda d: d.accept("Test Label"))
        click_at(500, 100)
        page.wait_for_timeout(200)
        txt_items = page.evaluate("tacticalItems.filter(i=>i.type==='text').length")
        assert txt_items == 1
        assert page.evaluate("tacticalItems.find(i=>i.type==='text').text") == "Test Label"

        # 7) measure tool
        page.click('[data-tool="measure"]')
        click_at(0, 500)
        click_at(300, 500)
        meas_items = page.evaluate("tacticalItems.filter(i=>i.type==='measure').length")
        assert meas_items == 1

        total_before_delete = page.evaluate("tacticalItems.length")

        # 8) select + delete
        page.click('[data-tool="select"]')
        click_at(100, 100)
        sel = page.evaluate("selectedId")
        assert sel is not None
        page.click("#deleteBtn")
        total_after_delete = page.evaluate("tacticalItems.length")
        assert total_after_delete == total_before_delete - 1

        # 9) drag test
        before_pos = page.evaluate("tacticalItems.find(i=>i.type==='marker').x")
        page.mouse.move(x0 + 150, y0 + 100)
        page.mouse.down()
        page.mouse.move(x0 + 250, y0 + 150, steps=5)
        page.mouse.up()
        after_pos = page.evaluate("tacticalItems.find(i=>i.type==='marker').x")
        assert after_pos != before_pos

        # 9.5) middle-click drag pans the map, doesn't touch tactical items
        can_scroll = page.evaluate(
            "document.getElementById('mosaicWrap').scrollWidth > document.getElementById('mosaicWrap').clientWidth "
            "|| document.getElementById('mosaicWrap').scrollHeight > document.getElementById('mosaicWrap').clientHeight")
        if can_scroll:
            scroll_before = page.evaluate(
                "[document.getElementById('mosaicWrap').scrollLeft, document.getElementById('mosaicWrap').scrollTop]")
            items_before_pan = page.evaluate("tacticalItems.length")
            map_box = page.locator("#mapArea").bounding_box()
            cx, cy = map_box["x"] + map_box["width"] / 2, map_box["y"] + map_box["height"] / 2
            page.mouse.move(cx, cy)
            page.mouse.down(button="middle")
            page.mouse.move(cx - 150, cy - 100, steps=5)
            page.mouse.up(button="middle")
            scroll_after = page.evaluate(
                "[document.getElementById('mosaicWrap').scrollLeft, document.getElementById('mosaicWrap').scrollTop]")
            assert scroll_after != scroll_before
            items_after_pan = page.evaluate("tacticalItems.length")
            assert items_after_pan == items_before_pan
        else:
            print("(mosaic smaller than viewport -- skipping pan test, nothing to scroll)")

        # 10) grid toggle
        page.click("#gridBtn")
        page.click("#gridBtn")

        # 11) persistence across reload
        count_before_reload = page.evaluate("tacticalItems.length")
        page.reload()
        page.wait_for_timeout(500)
        count_after_reload = page.evaluate("tacticalItems.length")
        assert count_after_reload == count_before_reload

        # 12) clear all
        page.once("dialog", lambda d: d.accept())
        page.click("#clearAllBtn")
        page.wait_for_timeout(200)
        assert page.evaluate("tacticalItems.length") == 0

        browser.close()

    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("ALL TACTICAL LAYER TESTS PASSED, no page errors")

if __name__ == "__main__":
    main(sys.argv[1])
