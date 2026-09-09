#!/usr/bin/env python3
"""
Turns one drone video into a "stream" the viewer can show a mosaic map for.
Chains the three pipeline stages:

    extract_trajectory.py   video.mp4          -> trajectory_raw.json
    loop_closure.py         video.mp4 + raw     -> trajectory_refined.json
    build_mosaic_transforms.py     refined      -> data.json

Then updates streams/manifest.json so the stream shows up in the viewer's
stream picker. The video itself is never modified or copied.

Usage:
    python3 build_stream.py <video_path> <stream_id> [--label "Display Name"]
                             [--max-seconds N] [--project-root DIR]

Example (from the project root):
    python3 pipeline/build_stream.py ornek.mp4 ornek --label "Park flight"
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_trajectory
import loop_closure
import build_mosaic_transforms


def build_stream(video_path, stream_id, label=None, max_seconds=None, project_root=".", streams_dirname="streams"):
    project_root = os.path.abspath(project_root)
    video_path = os.path.abspath(video_path)
    if not os.path.isfile(video_path):
        raise SystemExit(f"video not found: {video_path}")

    stream_dir = os.path.join(project_root, streams_dirname, stream_id)
    os.makedirs(stream_dir, exist_ok=True)

    raw_path = os.path.join(stream_dir, "trajectory_raw.json")
    refined_path = os.path.join(stream_dir, "trajectory_refined.json")
    data_path = os.path.join(stream_dir, "data.json")

    print(f"=== [1/3] visual odometry: {video_path} -> {raw_path}", file=sys.stderr)
    t0 = time.time()
    extract_trajectory.main(video_path, raw_path, max_seconds=max_seconds)
    print(f"    ({time.time()-t0:.1f}s)", file=sys.stderr)

    print(f"=== [2/3] loop-closure drift correction -> {refined_path}", file=sys.stderr)
    t0 = time.time()
    loop_closure.main(video_path, raw_path, refined_path)
    print(f"    ({time.time()-t0:.1f}s)", file=sys.stderr)

    print(f"=== [3/3] mosaic-canvas transforms -> {data_path}", file=sys.stderr)
    t0 = time.time()
    build_mosaic_transforms.main(refined_path, data_path)
    print(f"    ({time.time()-t0:.1f}s)", file=sys.stderr)

    # store paths relative to project root, same place index.html lives
    video_rel = os.path.relpath(video_path, project_root)
    data_rel = os.path.relpath(data_path, project_root)

    manifest_path = os.path.join(project_root, streams_dirname, "manifest.json")
    manifest = {"streams": []}
    if os.path.isfile(manifest_path):
        manifest = json.load(open(manifest_path))

    entry = {
        "id": stream_id,
        "label": label or stream_id,
        "video": video_rel.replace(os.sep, "/"),
        "data": data_rel.replace(os.sep, "/"),
    }
    manifest["streams"] = [s for s in manifest["streams"] if s["id"] != stream_id] + [entry]
    json.dump(manifest, open(manifest_path, "w"), indent=2, ensure_ascii=False)
    print(f"=== updated {manifest_path} ({len(manifest['streams'])} stream(s) total)", file=sys.stderr)
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_path")
    ap.add_argument("stream_id", help="short id, e.g. 'ornek' -- used as the folder name under streams/")
    ap.add_argument("--label", default=None, help="human-readable name shown in the viewer's stream picker")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--project-root", default=".")
    args = ap.parse_args()
    build_stream(args.video_path, args.stream_id, label=args.label,
                 max_seconds=args.max_seconds, project_root=args.project_root)


if __name__ == "__main__":
    main()
