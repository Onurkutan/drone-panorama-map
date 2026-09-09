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
from detect_objects import (iou_xywh, box_to_mosaic, merge_detection, postprocess_frame,
                            DEFAULT_CLASSES)


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


def test_box_to_mosaic_aabb_inflates_at_45_degrees():
    # pins the documented behaviour: the returned box is the axis-aligned
    # bounding box of the rotated corners, so 45 degrees inflates 40x20 to
    # ~42.43 square. The viewer can only draw axis-aligned rects.
    theta = math.pi / 4
    m = (math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta), 0, 0)
    x, y, w, h = box_to_mosaic(0, 0, 40, 20, m)
    expected = (40 + 20) * math.cos(theta)  # 42.4264...
    assert abs(w - expected) < 1e-3 and abs(h - expected) < 1e-3, (w, h)


def test_postprocess_keeps_car_when_a_stronger_van_guess_overlaps_it():
    # the class filter must run before the cross-class dedup: otherwise the
    # more confident van wins the dedup and is then dropped by the filter,
    # taking the car with it
    boxes = [[100.0, 100.0, 40.0, 20.0], [102.0, 101.0, 40.0, 20.0]]
    scores = [0.6, 0.8]
    classes = [3, 4]  # car, van
    keep = postprocess_frame(boxes, scores, classes, {3})
    assert len(keep) == 1, keep
    assert classes[keep[0]] == 3, "expected the car to survive, got class %d" % classes[keep[0]]


def test_postprocess_dedups_across_classes_when_both_are_wanted():
    boxes = [[100.0, 100.0, 40.0, 20.0], [102.0, 101.0, 40.0, 20.0]]
    scores = [0.6, 0.8]
    classes = [3, 4]  # car, van
    keep = postprocess_frame(boxes, scores, classes, {3, 4})
    assert len(keep) == 1, keep
    assert classes[keep[0]] == 4, "expected the higher-confidence van to win"


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
