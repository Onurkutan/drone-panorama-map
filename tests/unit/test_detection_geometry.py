#!/usr/bin/env python3
"""
Unit tests for the geometry/merge functions in pipeline/detect_objects.py.
No video, model, or browser needed.

Run: python3 tests/unit/test_detection_geometry.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pipeline"))
from detect_objects import iou_xywh, box_to_mosaic, merge_detection, DEFAULT_CLASSES


def test_iou_identical_boxes_is_one():
    a = (10, 10, 20, 20)
    assert abs(iou_xywh(a, a) - 1.0) < 1e-9


def test_iou_disjoint_boxes_is_zero():
    a, b = (0, 0, 10, 10), (100, 100, 10, 10)
    assert iou_xywh(a, b) == 0.0


def test_box_to_mosaic_identity_transform():
    x, y, w, h = box_to_mosaic(5, 5, 10, 10, (1, 0, 0, 1, 0, 0))
    assert (x, y, w, h) == (5.0, 5.0, 10.0, 10.0)


def test_box_to_mosaic_handles_rotation():
    theta = math.pi / 2
    m = (math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta), 0, 0)
    x, y, w, h = box_to_mosaic(-5, -2, 10, 4, m)
    assert abs(w - 4) < 1e-6 and abs(h - 10) < 1e-6, (w, h)


def test_merge_detection_folds_overlapping_box_into_existing():
    accumulated = []
    merge_detection(accumulated, (100, 100, 20, 20), 3, "car", 0.5, t=1.0)
    merge_detection(accumulated, (102, 101, 20, 20), 3, "car", 0.7, t=1.5)
    assert len(accumulated) == 1
    assert accumulated[0]["conf"] == 0.7
    assert accumulated[0]["t_reveal"] == 1.0


def test_merge_detection_keeps_distant_boxes_separate():
    accumulated = []
    merge_detection(accumulated, (0, 0, 20, 20), 3, "car", 0.5, t=1.0)
    merge_detection(accumulated, (500, 500, 20, 20), 3, "car", 0.5, t=2.0)
    assert len(accumulated) == 2


def test_merge_detection_respects_min_dist_floor_for_shrunken_resighting():
    accumulated = []
    merge_detection(accumulated, (100, 100, 30, 30), 3, "car", 0.6, t=1.0)
    merge_detection(accumulated, (105, 104, 3, 3), 3, "car", 0.4, t=1.5)
    assert len(accumulated) == 1


def test_default_classes_is_car_only():
    assert DEFAULT_CLASSES == [3]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"ALL {len(tests)} UNIT TESTS PASSED (test_detection_geometry)")
