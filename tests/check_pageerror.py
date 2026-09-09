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
        browser.close()
    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("NO PAGE ERRORS")

if __name__ == "__main__":
    main(sys.argv[1])
