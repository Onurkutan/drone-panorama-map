#!/usr/bin/env python3
"""
Unit tests for scripts/package.py's file-assembly logic, using a throwaway
temp project directory so this never touches the real streams/ data.

Run: python3 tests/unit/test_package.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from package import build_streams_array


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"))


def test_stream_without_detections_json_gets_empty_list():
    with tempfile.TemporaryDirectory() as root:
        _write(os.path.join(root, "streams", "manifest.json"), {"streams": [
            {"id": "s1", "label": "Stream 1", "video": "s1.mp4", "data": "streams/s1/data.json"}
        ]})
        _write(os.path.join(root, "streams", "s1", "data.json"),
               {"mosaic_width": 100, "mosaic_height": 100, "samples": []})
        streams = build_streams_array(root)
        assert streams[0]["detections"] == []


def test_stream_with_detections_json_merges_it_in():
    with tempfile.TemporaryDirectory() as root:
        _write(os.path.join(root, "streams", "manifest.json"), {"streams": [
            {"id": "s1", "label": "Stream 1", "video": "s1.mp4", "data": "streams/s1/data.json"}
        ]})
        _write(os.path.join(root, "streams", "s1", "data.json"),
               {"mosaic_width": 100, "mosaic_height": 100, "samples": []})
        _write(os.path.join(root, "streams", "s1", "detections.json"),
               {"detections": [{"id": "det-0000", "class": "car"}]})
        streams = build_streams_array(root)
        assert len(streams[0]["detections"]) == 1


def test_missing_manifest_raises_clear_error():
    with tempfile.TemporaryDirectory() as root:
        try:
            build_streams_array(root)
            assert False, "expected a missing manifest.json to raise"
        except SystemExit as e:
            assert "manifest.json" in str(e)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"ALL {len(tests)} UNIT TESTS PASSED (test_package)")
