#!/usr/bin/env python3
"""
Builds the video-pixel -> mosaic-canvas affine transform per sample, from
the visual-odometry chain (traj_*.json). Feeds a browser-side canvas
stitcher: each video frame is warped by its transform and drawn onto a
persistent canvas as the video plays, building a panorama purely from the
drone's own footage, no GPS.

Every sample draws the same way. Seams and ghosting are handled by edge
feathering in the drawing code (template.html): each frame is opaque in
the center and fades to transparent near its edges, so newer frames still
fully replace old content in the middle while only the edge blends softly.

Note on mosaic_scale: it is relative to the 640-px-wide work space the
trajectory was estimated in, not to the source video. The effective
video-pixel -> mosaic-pixel scale is mosaic_scale * work_width / src_width,
so the 2.0 default is really ~0.333 on a 4K source (2.0 * 640 / 3840).
"""
import argparse
import json
import numpy as np
import sys

def main(traj_path, out_path, mosaic_scale=2.0, padding=20):
    with open(traj_path, encoding="utf-8") as f:
        d = json.load(f)
    samples = d["samples"]
    # min()/max() over an empty corner list is an opaque ValueError otherwise
    if not samples:
        raise SystemExit(f"{traj_path} has no samples -- nothing to build a mosaic from")
    work_w, work_h = d["work_width"], d["work_height"]
    src_w, src_h = d["src_width"], d["src_height"]
    ws = work_w / src_w  # video-pixel -> work-pixel scale

    xs, ys = [], []
    for s in samples:
        for c in s["corners"]:
            xs.append(c[0]); ys.append(c[1])
    minX, maxX = min(xs), max(xs)
    minY, maxY = min(ys), max(ys)

    ms = mosaic_scale
    mosaic_w = int((maxX - minX) * ms) + 2 * padding
    mosaic_h = int((maxY - minY) * ms) + 2 * padding

    # ScaleTrans: world-pixel -> mosaic canvas pixel
    ScaleTrans = np.array([
        [ms, 0, -minX * ms + padding],
        [0, ms, -minY * ms + padding],
        [0, 0, 1],
    ])
    ScaleVideo = np.array([[ws, 0, 0], [0, ws, 0], [0, 0, 1]])

    out_samples = []
    for i, s in enumerate(samples):
        T_work = np.array(s["T"])  # work-pixel -> world-pixel
        M = ScaleTrans @ T_work @ ScaleVideo  # video-pixel -> mosaic-canvas
        # canvas setTransform(a,b,c,d,e,f): x'=a*x+c*y+e, y'=b*x+d*y+f
        a, c, e = M[0, 0], M[0, 1], M[0, 2]
        b, dd, f = M[1, 0], M[1, 1], M[1, 2]
        # also store center point in mosaic space (for the overlay marker)
        center_world = np.array(s["center"] + [1.0])
        center_mosaic = ScaleTrans @ center_world
        out_samples.append({
            "t": s["t"],
            "m": [round(v, 4) for v in [a, b, c, dd, e, f]],
            "center": [round(center_mosaic[0], 1), round(center_mosaic[1], 1)],
        })

    out = {
        "video": d["video"],
        "src_width": src_w, "src_height": src_h,
        "mosaic_width": mosaic_w, "mosaic_height": mosaic_h,
        "samples": out_samples,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
        f.write("\n")
    print(f"mosaic canvas: {mosaic_w} x {mosaic_h} px  ({len(out_samples)} samples)", file=sys.stderr)
    print(f"wrote {out_path}", file=sys.stderr)

if __name__ == "__main__":
    # argparse instead of raw sys.argv indexing: running this with no arguments
    # used to be an IndexError instead of a usage message
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("traj_path", help="trajectory_refined.json from loop_closure.py")
    ap.add_argument("out_path", help="where to write the stream's data.json")
    args = ap.parse_args()
    main(args.traj_path, args.out_path)
