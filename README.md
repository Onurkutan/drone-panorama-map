# Drone Panorama Map

[![tests](https://github.com/Onurkutan/drone-panorama-map/actions/workflows/tests.yml/badge.svg)](https://github.com/Onurkutan/drone-panorama-map/actions/workflows/tests.yml)

> Built during my 2026 summer internship. This repository is the public
> version of the delivered project; further improvements land as small
> follow-up commits.

A single-file, offline browser app that builds a panorama/mosaic map from
drone video. No real GPS or map integration is used — the map is built
purely from the video itself using visual odometry (ORB feature matching +
affine transform estimation).

On top of the map there's an ATAK-style markup layer (marker, line, area,
freehand, text, distance measurement) and a toggleable vehicle-detection
layer powered by a VisDrone-trained YOLO model.

Note: since there's no real GPS/UTM/MGRS data, the grid on the map is just
a local pixel-based reference (map-book-style A1/B2 cells), and the
measuring tool reports distance in pixels, not meters.

## Quick start

Open `index.html` in any browser — no server or internet needed. Use the
"Stream" picker in the top-left to pick a sample flight.

### Sample videos

The two sample flight videos are too large for the repository
(`ornek.mp4` 407 MB, `ornek2.mp4` 173 MB; 3840×2160 @ 60 fps). Download
them from the [Releases page](https://github.com/Onurkutan/drone-panorama-map/releases) and put them next to
`index.html` before opening it. Without the videos the app still loads,
but nothing plays and the mosaic stays empty.

Commands below use `python3`; on Windows use `python` instead.

## Folder structure

```
drone mapping/
├── index.html                 <- the app: one file, open in a browser
├── ornek.mp4, ornek2.mp4       <- sample flight videos (not in the repo, see "Sample videos")
├── streams/
│   ├── manifest.json            <- list of streams (id, label, video path, data path)
│   └── <stream_id>/
│       ├── trajectory_raw.json    <- raw visual-odometry output
│       ├── trajectory_refined.json<- drift-corrected via loop closure
│       ├── data.json              <- data embedded into the mosaic canvas
│       └── detections.json        <- (optional) vehicle detection results
├── pipeline/                   <- Python tools, run once when adding a video
│   ├── extract_trajectory.py     <- stage 1: visual odometry
│   ├── loop_closure.py           <- stage 2: pose-graph drift correction
│   ├── build_mosaic_transforms.py<- stage 3: mosaic-canvas transforms
│   ├── build_stream.py           <- runs all 3 stages
│   ├── render_preview.py         <- renders the mosaic as a PNG, no browser
│   └── detect_objects.py         <- (optional) vehicle detection -> detections.json
├── models/
│   ├── best.onnx                  <- YOLOv8n model (ONNX)
│   └── best.pt                    <- same model, PyTorch source (not used at runtime, not in the repo)
├── viewer/
│   └── template.html           <- app source template
├── scripts/
│   └── package.py               <- builds index.html from the template + stream data
├── tests/
│   ├── run_all.py                 <- runs all tests, prints a summary
│   ├── conftest.py                <- pytest fixtures (packages a throwaway index.html)
│   ├── unit/                      <- pure-function tests, no browser needed
│   │   ├── test_detection_geometry.py
│   │   ├── test_pose_graph.py
│   │   ├── test_package.py
│   │   └── test_causal_order.py
│   ├── test_pageerror.py
│   ├── test_tactical.py
│   ├── test_zoom.py
│   ├── test_stream_switch.py
│   └── test_detections.py
├── TESTING_STRATEGY.md
├── pytest.ini
├── requirements.txt
└── requirements-dev.txt
```

## Why is there Python if only one HTML file ships?

The Python files under `pipeline/` and `scripts/` are build-time tools.
Each one runs once and produces a small JSON data package
(`streams/<id>/data.json`), which `scripts/package.py` embeds into
`viewer/template.html` to produce `index.html`.

Once `index.html` is built, Python isn't needed anymore — the app is plain
JavaScript/Canvas, no server or install required.

## Adding a new video

```bash
pip install -r requirements.txt   # once

# 1) put the video in the project root
# 2) run the pipeline
python3 pipeline/build_stream.py newflight.mp4 newflight --label "New Flight"

# 3) rebuild index.html with all streams
python3 scripts/package.py
```

Step 2 can take a few minutes on longer videos.

## Object detection (vehicles)

`models/best.onnx` is a YOLOv8n model trained on VisDrone (classes:
pedestrian, people, bicycle, car, van, truck, tricycle, awning-tricycle,
bus, motor). `pipeline/detect_objects.py` runs it against the raw video,
one sampled frame at a time, in time order.

By default only the `car` class is kept — the other vehicle classes had a
lot more false positives on the sample flights, since the model was
trained on far fewer examples of them. Pass `--classes 3,4,5,6,7,8,9` to
bring the other classes back if needed.

The same vehicle seen in multiple frames is merged into one detection
using its mosaic-pixel position, instead of being counted repeatedly. Each
detection is stamped with `t_reveal`, the timestamp it was first spotted.

Results are written to `streams/<id>/detections.json` and embedded into
`index.html`. In the browser, a detection box only appears once playback
reaches its `t_reveal` — same as how the mosaic itself only draws footage
that's already played. The "🚗 Detected vehicles" button toggles the layer
and shows a `(revealed/total)` count.

The 🗑️ "Remove false detections" button lets you click a box to remove it
(remembered per stream, undo with "↺ Restore removed").

Generate detections for a new stream:

```bash
python3 pipeline/detect_objects.py <video> models/best.onnx streams/<id>/data.json streams/<id>/detections.json \
    --detect-every-sec 2.0 --conf 0.30
python3 scripts/package.py
```

`--detect-every-sec` controls how often detection runs. Lower it for finer
detail at the cost of longer run time.

The model isn't perfect — occasional duplicate detections of the same car
can slip through even after merging. That's what the remove-mode button is
for. There's no detection for roads or buildings, and non-`car` vehicle
classes are off by default for accuracy reasons (see above).

## Running the tests

```bash
pip install -r requirements-dev.txt
python3 -m playwright install chromium   # once, if needed
pytest                                    # unit + browser tests
pytest -m "not browser"                   # unit tests only, no browser/Chromium needed
pytest -m browser                         # browser tests only
```

The browser tests package their own throwaway `index.html` via a pytest
fixture (`tests/conftest.py`), so they never touch the repo's own
`index.html` and don't need the sample videos (`ornek.mp4`/`ornek2.mp4`) to
be present -- they exercise everything except actual video playback (see
`TESTING_STRATEGY.md`). If Chromium isn't installed, `browser`-marked tests
are skipped automatically with a clear reason instead of erroring.

If Chromium lives somewhere other than Playwright's default install path
(e.g. a sandboxed CI image), point at it with `PW_CHROMIUM_PATH`:

```bash
PW_CHROMIUM_PATH=/opt/pw-browsers/chromium pytest -m browser
```

You can still run any file directly, the same way `tests/run_all.py` does:

```bash
python3 scripts/package.py               # rebuild index.html first
python3 tests/run_all.py index.html      # legacy runner: everything against one built index.html

python3 tests/unit/test_detection_geometry.py
python3 tests/unit/test_pose_graph.py
python3 tests/unit/test_package.py
python3 tests/unit/test_causal_order.py

python3 tests/test_pageerror.py index.html
python3 tests/test_tactical.py index.html
python3 tests/test_zoom.py index.html
python3 tests/test_stream_switch.py index.html
python3 tests/test_detections.py index.html
```

See `TESTING_STRATEGY.md` for what each test covers.

## Known limitations

- No real GPS/UTM/MGRS referencing — grid is local/pixel-based only.
- Vehicle detection is limited to `car` by default; occasional duplicates
  can still occur.
- Non-`car` vehicle classes and pedestrians are off by default; re-enable
  with `--classes` if needed.
- No detection for roads or buildings.

## License

The code in this repository (viewer, pipeline, scripts, tests) is released
under the MIT License — see `LICENSE`.

`models/best.onnx` is a third-party model and is not covered by that
license: a YOLOv8n fine-tuned on VisDrone by mshamrai
(https://huggingface.co/mshamrai/yolov8n-visdrone), tagged `openrail` on
its model card. It was trained with Ultralytics YOLOv8, which Ultralytics
distributes under AGPL-3.0; whether that reaches downstream weights is an
unsettled question, so check both the model card and Ultralytics' terms
before reusing the weights outside this project.
