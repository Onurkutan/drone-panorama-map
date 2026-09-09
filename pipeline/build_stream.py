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


def load_manifest(path):
    """Reads and validates streams/manifest.json. Called before stage 1 so a
    corrupt manifest fails now instead of after minutes of pipeline work."""
    if not os.path.isfile(path):
        return {"streams": []}
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read {path}: {e}")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("streams"), list):
        raise SystemExit(f"{path} is not a valid manifest -- expected a top-level 'streams' list")
    for i, entry in enumerate(manifest["streams"]):
        if not isinstance(entry, dict) or not entry.get("id"):
            raise SystemExit(f"{path}: streams[{i}] has no usable 'id' field")
    return manifest


def relative_to_root(path, project_root):
    """index.html loads videos/data by path relative to the project root, so
    anything outside it (or on another Windows drive) can't be reached from
    the page -- warn and fall back to an absolute path rather than emit a
    silently broken '..' link."""
    try:
        rel = os.path.relpath(path, project_root)
    except ValueError:
        rel = None
    if rel is None or rel == ".." or rel.startswith(".." + os.sep):
        print(f"warning: {path} is outside the project root {project_root} -- index.html may not "
              f"be able to reach it; storing the absolute path instead", file=sys.stderr)
        return path.replace(os.sep, "/")
    return rel.replace(os.sep, "/")


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

    # validate the manifest up front -- discovering it's corrupt after the
    # three slow stages have run wastes the whole run
    manifest_path = os.path.join(project_root, streams_dirname, "manifest.json")
    manifest = load_manifest(manifest_path)

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
    entry = {
        "id": stream_id,
        "label": label or stream_id,
        "video": relative_to_root(video_path, project_root),
        "data": relative_to_root(data_path, project_root),
    }
    manifest["streams"] = [s for s in manifest["streams"] if s["id"] != stream_id] + [entry]
    # encoding is explicit: package.py reads this back as UTF-8, so a non-ASCII
    # --label written in the machine's default codepage breaks packaging
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
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
