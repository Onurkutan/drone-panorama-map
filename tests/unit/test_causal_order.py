#!/usr/bin/env python3
"""
Checks that the frame-selection logic in pipeline/detect_objects.py
(mirrored here) always moves forward in time and never revisits a sample --
detection must process the video in order, without looking ahead.

Run: python3 tests/unit/test_causal_order.py
"""
import json
import os

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _check_stream(stream_id, detect_every_sec=2.0):
    data_path = os.path.join(PROJECT_ROOT, "streams", stream_id, "data.json")
    data = json.load(open(data_path))
    samples = data["samples"]
    assert len(samples) >= 2, f"{stream_id}: expected at least 2 samples to test stride selection"

    # mirrors detect_objects.py's own stride selection
    step_t = samples[1]["t"] - samples[0]["t"]
    stride = max(1, round(detect_every_sec / step_t))
    selected = samples[::stride]
    times = [s["t"] for s in selected]

    assert times == sorted(times), f"{stream_id}: expected strictly forward-in-time frame selection"
    assert len(set(times)) == len(times), f"{stream_id}: expected no frame to be visited twice"
    assert times[0] == samples[0]["t"], f"{stream_id}: expected the scan to start at the flight's first sample"


def test_ornek_selection_is_causal():
    _check_stream("ornek")


def test_ornek2_selection_is_causal():
    _check_stream("ornek2")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"ALL {len(tests)} UNIT TESTS PASSED (test_causal_order)")
