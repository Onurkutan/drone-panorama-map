#!/usr/bin/env python3
"""
Offline preview: warps the real video frames with the same per-sample
transforms the browser uses, composites them into the mosaic canvas with
OpenCV using the same edge-feathering model as viewer/template.html, and
saves a PNG. Useful for checking the mosaic looks right without a browser.

The result is sparser than what the browser shows: the viewer composites
every played frame (~50/s, interpolating between samples), while this script
only draws the sampled frames listed in data.json (~2/s by default). Expect
visible gaps between footprints, not a defect in the transforms.

Usage: render_preview.py <video> <stream_data.json> <out.png> [downscale] [margin_frac]
"""
import argparse
import cv2
import numpy as np
import json
import math
import sys

FEATHER_MARGIN_FRAC = 0.02  # keep in sync with viewer/template.html's FEATHER_MARGIN_FRAC

def sane_fps(raw_fps, video_path):
    """OpenCV reports 0 (and occasionally NaN/inf) for containers it can't read
    the rate from; `raw or 30.0` misses NaN, and a bad fps silently shifts every
    sample timestamp. Kept in the same shape in extract_trajectory/detect_objects."""
    fps = float(raw_fps or 0.0)
    if not math.isfinite(fps) or fps <= 0:
        print(f"warning: unusable fps ({raw_fps!r}) from {video_path}, falling back to 30.0", file=sys.stderr)
        return 30.0
    return fps

def build_feather_mask(w, h, margin_frac=FEATHER_MARGIN_FRAC):
    # a sub-pixel margin makes both ramps divide by ~0 -> NaN mask -> black frame
    mx, my = max(1.0, w * margin_frac), max(1.0, h * margin_frac)
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    fx = np.clip(np.minimum(xs / mx, (w - 1 - xs) / mx), 0, 1)
    fy = np.clip(np.minimum(ys / my, (h - 1 - ys) / my), 0, 1)
    return np.outer(fy, fx).astype(np.float32)

def main(video_path, mosaic_data_path, out_png, downscale=1.0, margin_frac=FEATHER_MARGIN_FRAC):
    with open(mosaic_data_path, encoding="utf-8") as f:
        d = json.load(f)
    samples = d["samples"]
    mw, mh = d["mosaic_width"], d["mosaic_height"]
    if downscale != 1.0:
        mw, mh = int(mw * downscale), int(mh * downscale)

    canvas = np.zeros((mh, mw, 3), dtype=np.float32)
    covered = np.zeros((mh, mw), dtype=bool)

    cap = cv2.VideoCapture(video_path)
    # without this the script happily writes an all-background PNG
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")
    fps = sane_fps(cap.get(cv2.CAP_PROP_FPS), video_path)
    # two samples can round to the same frame index; keep the first m for each
    # and sort, so the decode loop never waits on an index it already passed
    seen = set()
    wanted = []
    for s in samples:
        idx = round(s["t"] * fps)
        if idx in seen:
            continue
        seen.add(idx)
        wanted.append((idx, s["m"]))
    wanted.sort(key=lambda x: x[0])

    frame_idx = 0
    wi = 0
    n_drawn = 0
    feather_mask = None
    while wi < len(wanted):
        target_idx, m = wanted[wi]
        ret = cap.grab()
        if not ret:
            break
        if frame_idx >= target_idx:  # >= so a stale target can't run the decode to EOF
            ret, frame = cap.retrieve()
            if ret:
                if feather_mask is None:
                    fh, fw = frame.shape[:2]
                    feather_mask = build_feather_mask(fw, fh, margin_frac)
                a, b, c, dd, e, f = m
                M = np.array([[a, c, e * downscale], [b, dd, f * downscale]], dtype=np.float64)
                if downscale != 1.0:
                    M[0, 0] *= downscale; M[0, 1] *= downscale
                    M[1, 0] *= downscale; M[1, 1] *= downscale
                warped = cv2.warpAffine(frame, M, (mw, mh), flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
                alpha = cv2.warpAffine(feather_mask, M, (mw, mh), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                a3 = alpha[:, :, None]
                canvas = canvas * (1 - a3) + warped.astype(np.float32) * a3
                covered |= (alpha > 0.02)
                n_drawn += 1
            wi += 1
        frame_idx += 1

    cap.release()
    out_img = np.clip(canvas, 0, 255).astype(np.uint8)
    out_img[~covered] = 24
    # imwrite returns False (no exception) on a bad path or unknown extension
    if not cv2.imwrite(out_png, out_img):
        raise SystemExit(f"cannot write {out_png}")
    print(f"drew {n_drawn}/{len(wanted)} frames, saved {out_png} ({mw}x{mh})", file=sys.stderr)

if __name__ == "__main__":
    # argparse instead of raw sys.argv indexing: running this with no arguments
    # used to be an IndexError instead of a usage message
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_path")
    ap.add_argument("mosaic_data_path", help="the stream's data.json")
    ap.add_argument("out_png")
    ap.add_argument("downscale", nargs="?", type=float, default=1.0,
                    help="shrink the mosaic canvas by this factor (default: 1.0)")
    ap.add_argument("margin_frac", nargs="?", type=float, default=FEATHER_MARGIN_FRAC,
                    help=f"edge-feather width as a fraction of the frame (default: {FEATHER_MARGIN_FRAC})")
    args = ap.parse_args()
    main(args.video_path, args.mosaic_data_path, args.out_png, args.downscale, args.margin_frac)
