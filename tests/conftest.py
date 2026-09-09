"""
Shared pytest fixtures and configuration for the test suite.

- `packaged_html` (session-scoped): builds a throwaway `index.html` (via
  `scripts/package.py`) into a pytest tmp directory, so the browser tests
  never read or overwrite the repository's own `index.html`.
- `html_path`: convenience fixture returning that packaged file's path as
  a str, for the browser tests' `main(html_path)` functions.
- a `browser` marker, plus a collection hook that skips `browser`-marked
  tests (with a clear reason) when Playwright isn't installed or Chromium
  can't actually be launched -- e.g. `python -m playwright install
  chromium` was never run.
"""
import functools
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "browser: Playwright browser test (needs Chromium; auto-skipped if unavailable)",
    )


@functools.lru_cache(maxsize=1)
def _browser_available():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return False, f"playwright is not installed ({exc})"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM_PATH") or None)
            browser.close()
    except Exception as exc:
        return False, f"Chromium could not be launched ({exc})"
    return True, ""


def pytest_collection_modifyitems(config, items):
    browser_items = [item for item in items if item.get_closest_marker("browser")]
    if not browser_items:
        return
    available, reason = _browser_available()
    if available:
        return
    skip_marker = pytest.mark.skip(reason=f"browser tests unavailable: {reason}")
    for item in browser_items:
        item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def packaged_html(tmp_path_factory):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from package import package

    out_dir = tmp_path_factory.mktemp("packaged")
    out_path = out_dir / "index.html"
    return pathlib.Path(package(project_root=str(ROOT), out_path=str(out_path)))


@pytest.fixture(scope="session")
def html_path(packaged_html):
    return str(packaged_html)
