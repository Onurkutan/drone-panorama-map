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

**Browser tests** (`tests/*.py`, Playwright against the packaged
`index.html`):
- `check_pageerror.py` — page loads without console/JS errors, basic
  stream switch sanity check.
- `test_tactical.py` — markers, lines, areas, freehand, text, measure,
  select/drag, delete, grid toggle, persistence.
- `test_zoom.py` — wheel/button zoom, cursor anchoring, follow mode.
- `test_stream_switch.py` — canvas/video/zoom reset on stream switch, and
  that each stream's markers stay isolated.
- `test_detections.py` — detection reveal timing, toggle, remove/restore,
  isolation from tactical markers.

Run everything:

```bash
python3 scripts/package.py
python3 tests/run_all.py index.html
```

## What isn't covered

- Actual video playback and rendering — this sandbox can't decode the
  video codec used here, so `revealDetectionsUpTo()`/`interpAt()` are
  called directly in tests instead of relying on real playback.
- The odometry/loop-closure pipeline (`extract_trajectory.py`,
  `build_mosaic_transforms.py`) doesn't have automated regression tests
  yet — correctness is checked by re-running the sample videos and
  comparing the numbers by hand.
- No CI — tests are run manually.
- Visual/pixel-level correctness (does the mosaic actually look right) —
  still needs a manual check by opening `index.html` in a real browser.
