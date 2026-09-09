#!/usr/bin/env python3
"""
Unit tests for the pure pose-graph math in pipeline/loop_closure.py -- no
video needed. These check the round-trip and inverse-composition properties
the loop-closure solver depends on.

Run: python3 tests/unit/test_pose_graph.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pipeline"))
from loop_closure import affine_to_params, params_to_affine, invert_params, compose


def test_params_roundtrip_through_affine():
    theta, scale, t = 0.3, 1.05, (12.0, -4.0)
    M = params_to_affine(theta, scale, t)
    theta2, scale2, t2 = affine_to_params(M)
    assert abs(theta - theta2) < 1e-6
    assert abs(scale - scale2) < 1e-6
    assert abs(t[0] - t2[0]) < 1e-6 and abs(t[1] - t2[1]) < 1e-6


def test_invert_undoes_compose():
    theta, scale, t = 0.1, 1.02, (5.0, 3.0)
    inv_theta, inv_scale, inv_t = invert_params(theta, scale, t)
    r_theta, r_scale, r_t = compose(theta, scale, t, inv_theta, inv_scale, inv_t)
    assert abs(r_theta) < 1e-6, "composing a transform with its own inverse should give ~0 rotation"
    assert abs(r_scale - 1.0) < 1e-6, "...and ~1.0 scale"
    assert abs(r_t[0]) < 1e-6 and abs(r_t[1]) < 1e-6, "...and ~0 translation"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"ALL {len(tests)} UNIT TESTS PASSED (test_pose_graph)")
