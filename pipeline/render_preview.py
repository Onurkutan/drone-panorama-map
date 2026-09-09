#!/usr/bin/env python3
"""
Offline preview: warps the real video frames with the same per-sample
transforms the browser uses, composites them into the mosaic canvas with
OpenCV using the same edge-feathering model as viewer/template.html, and
saves a PNG. Useful for checking the mosaic looks right without a browser.

Usage: render_preview.py <video> <stream_data.json> <out.png> [downscale] [margin_frac]
"""
import cv2
import numpy as np
import json
import sys

FEATHER_MARGIN_FRAC = 0.02  # keep in sync with viewer/template.html's FEATHER_MARGIN_FRAC

def build_feather_mask(w, h, margin_frac=FEATHER_MARGIN_FRAC):
    mx, my = w * margin_frac, h * margin_frac
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    fx = np.clip(np.minimum(xs / mx, (w - 1 - xs) / mx), 0, 1)
    fy = np.clip(np.minimum(ys / my, (h - 1 - ys) / my), 0, 1)
    return np.outer(fy, fx).astype(np.float32)

def main(video_path, mosaic_data_path, out_png, downscale=1.0, margin_frac=FEATHER_MARGIN_FRAC):
    d = json.load(open(mosaic_data_path))
    samples = d["samples"]
    mw, mh = d["mosaic_width"], d["mosaic_height"]
    if downscale != 1.0:
        mw, mh = int(mw * downscale), int(mh * downscale)

    canvas = np.zeros((mh, mw, 3), dtype=np.float32)
    covered = np.zeros((mh, mw), dtype=bool)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    wanted = [(round(s["t"] * fps), s["m"]) for s in samples]
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
        if frame_idx == target_idx:
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
    cv2.imwrite(out_png, out_img)
    print(f"drew {n_drawn}/{len(wanted)} frames, saved {out_png} ({mw}x{mh})", file=sys.stderr)

if __name__ == "__main__":
    downscale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    margin_frac = float(sys.argv[5]) if len(sys.argv) > 5 else FEATHER_MARGIN_FRAC
    main(sys.argv[1], sys.argv[2], sys.argv[3], downscale, margin_frac)
