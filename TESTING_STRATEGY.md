# Testing

## What's covered

**Unit tests** (`tests/unit/`, no browser/video/model needed, run in under a
second):
- `test_detection_geometry.py` — IoU, box-to-mosaic transform, and the
  merge/dedup logic in `detect_objects.py`.
- `test_pose_graph.py` — the pose-graph math in `loop_closure.py`
  (affine/params conversion, compose, invert).
- `test_package.py` — `package.py`'s file-assembly logic (with/without
  `detections.json`, missing manifest).
- `test_causal_order.py` — confirms frame selection for detection always
  moves forward in time and never revisits a sample.

**Browser tests** (`tests/test_*.py`, marked `@pytest.mark.browser`,
Playwright against a packaged `index.html`):
- `test_pageerror.py` — page loads without console/JS errors, basic
  stream switch sanity check.
- `test_tactical.py` — markers, lines, areas, freehand, text, measure,
  select/drag, delete, grid toggle, persistence.
- `test_zoom.py` — wheel/button zoom, cursor anchoring, follow mode.
- `test_stream_switch.py` — canvas/video/zoom reset on stream switch, and
  that each stream's markers stay isolated.
- `test_detections.py` — detection reveal timing, toggle, remove/restore,
  isolation from tactical markers.

These run without the sample flight videos: `tests/conftest.py` packages a
throwaway `index.html` per session, and none of the assertions depend on a
video actually decoding (see "What isn't covered" below). The one thing
video-less playback does surface is a browser console error for the
missing `<video src="...">` resource; each browser test recognizes that
specific failure (matched against `STREAMS`' video filenames) and reports
it as an informational line instead of a failure — see the docstring in
`test_pageerror.py` for what was verified.

Run everything:

```bash
pip install -r requirements-dev.txt
pytest                        # unit + browser tests
pytest -m "not browser"       # unit tests only
pytest -m browser             # browser tests only
```

`browser`-marked tests are auto-skipped (not failed) if Playwright or a
launchable Chromium isn't available. Individual files can still be run
directly, e.g. `python3 tests/test_zoom.py index.html` after
`python3 scripts/package.py` — see `README.md`.

## What isn't covered

- Actual video playback and rendering — this sandbox can't decode the
  video codec used here, so `revealDetectionsUpTo()`/`interpAt()` are
  called directly in tests instead of relying on real playback.
- The odometry/loop-closure pipeline (`extract_trajectory.py`,
  `build_mosaic_transforms.py`) doesn't have automated regression tests
  yet — correctness is checked by re-running the sample videos and
  comparing the numbers by hand.
- CI (`.github/workflows/tests.yml`) runs the unit and browser tests on
  every push/PR, and also rebuilds `index.html` to make sure it matches
  `viewer/template.html` — but it doesn't have the sample videos either,
  for the same reason they aren't in the repo (see "Sample videos" in
  `README.md`).
- Visual/pixel-level correctness (does the mosaic actually look right) —
  still needs a manual check by opening `index.html` in a real browser.
