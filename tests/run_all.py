#!/usr/bin/env python3
"""
Runs unit tests, then the Playwright browser tests against a packaged
index.html, and prints a pass/fail summary.

Usage:
    python3 scripts/package.py
    python3 tests/run_all.py index.html
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

UNIT_TESTS = [
    "unit/test_detection_geometry.py",
    "unit/test_pose_graph.py",
    "unit/test_package.py",
    "unit/test_causal_order.py",
]

BROWSER_TESTS = [
    "test_pageerror.py",
    "test_tactical.py",
    "test_zoom.py",
    "test_stream_switch.py",
    "test_detections.py",
]


def main():
    if len(sys.argv) != 2:
        print("usage: python3 tests/run_all.py <path-to-index.html>")
        sys.exit(2)
    html_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(html_path):
        print(f"error: {html_path} does not exist -- run scripts/package.py first")
        sys.exit(2)

    results = []

    print("=" * 60)
    print("UNIT TESTS (no browser, no video)")
    print("=" * 60)
    for rel in UNIT_TESTS:
        path = os.path.join(HERE, rel)
        print(f"\n--- {rel} ---")
        r = subprocess.run([sys.executable, path])
        results.append((rel, r.returncode == 0))

    print("\n" + "=" * 60)
    print("BROWSER TESTS (Playwright, against the packaged index.html)")
    print("=" * 60)
    for rel in BROWSER_TESTS:
        path = os.path.join(HERE, rel)
        print(f"\n--- {rel} ---")
        r = subprocess.run([sys.executable, path, html_path])
        results.append((rel, r.returncode == 0))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"\n{len(failed)} of {len(results)} test file(s) FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print(f"\nALL {len(results)} TEST FILES PASSED")


if __name__ == "__main__":
    main()
