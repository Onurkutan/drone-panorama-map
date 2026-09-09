#!/usr/bin/env python3
"""
Vehicle detection on the drone video.

Scans the video frame by frame, in time order, and never looks ahead --
each sampled frame is processed with only past frames already handled.
Detections are tagged with t_reveal, the timestamp of the frame that first
found them, so the viewer can reveal them in sync with playback instead of
showing everything at once.

The model takes a fixed 640x640 input, so each frame is cut into
overlapping tiles first; per-tile results are merged with NMS, then folded
into a running cross-frame detection list (same physical object seen again
= update, not a new entry).

Detection only runs every --detect-every-sec seconds, not on every frame,
and only keeps VisDrone class 3 (car) by default -- the other vehicle
classes (van/truck/bus/motor) misfire far more often on this model, so
they're off unless --classes overrides it.

Usage:
    python3 pipeline/detect_objects.py <video> <model.onnx> <data.json> <out.json>
        [--detect-every-sec 2.0] [--tile 640] [--overlap 160]
        [--conf 0.25] [--iou 0.45] [--merge-iou 0.35]
        [--classes 3] [--max-seconds N]
"""
import argparse
import json
import math
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

VISDRONE_NAMES = {
    0: "pedestrian", 1: "people", 2: "bicycle", 3: "car", 4: "van",
    5: "truck", 6: "tricycle", 7: "awning-tricycle", 8: "bus", 9: "motor",
}
VEHICLE_CLASSES = [3, 4, 5, 6, 7, 8, 9]  # all vehicle classes, usable via --classes
DEFAULT_CLASSES = [3]  # car only


def letterbox_tile(img, x0, y0, tile):
    """Cuts a tile*tile window out of img at (x0,y0), zero-padding outside the image bounds."""
    h, w = img.shape[:2]
    out = np.zeros((tile, tile, 3), dtype=img.dtype)
    x1, y1 = min(x0 + tile, w), min(y0 + tile, h)
    sx0, sy0 = max(x0, 0), max(y0, 0)
    if sx0 >= x1 or sy0 >= y1:
        return out
    out[sy0 - y0:y1 - y0, sx0 - x0:x1 - x0] = img[sy0:y1, sx0:x1]
    return out


def run_tiled_inference(img_bgr, sess, tile=640, overlap=160, conf_thresh=0.25, log=False):
    h, w = img_bgr.shape[:2]
    stride = tile - overlap
    xs = list(range(0, max(w - tile, 0) + 1, stride)) or [0]
    ys = list(range(0, max(h - tile, 0) + 1, stride)) or [0]
    if xs[-1] + tile < w:
        xs.append(w - tile)
    if ys[-1] + tile < h:
        ys.append(h - tile)

    input_name = sess.get_inputs()[0].name
    all_boxes, all_scores, all_classes = [], [], []

    n_tiles = len(xs) * len(ys)
    done = 0
    for y0 in ys:
        for x0 in xs:
            tile_img = letterbox_tile(img_bgr, x0, y0, tile)
            rgb = cv2.cvtColor(tile_img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            chw = np.transpose(rgb, (2, 0, 1))[None, ...]
            out = sess.run(None, {input_name: chw})[0]  # [1, 14, 8400]
            pred = out[0].T  # [8400, 14]: cx,cy,w,h, 10 class scores
            boxes_xywh = pred[:, :4]
            class_scores = pred[:, 4:]
            cls_ids = np.argmax(class_scores, axis=1)
            confs = class_scores[np.arange(len(cls_ids)), cls_ids]
            keep = confs >= conf_thresh
            if keep.any():
                bx = boxes_xywh[keep]
                cx, cy, bw, bh = bx[:, 0], bx[:, 1], bx[:, 2], bx[:, 3]
                # center-based (cx,cy,w,h) -> top-left + tile offset, still frame-local
                x1 = cx - bw / 2 + x0
                y1 = cy - bh / 2 + y0
                for i in range(len(cx)):
                    all_boxes.append([float(x1[i]), float(y1[i]), float(bw[i]), float(bh[i])])
                    all_scores.append(float(confs[keep][i]))
                    all_classes.append(int(cls_ids[keep][i]))
            done += 1
            if log:
                print(f"    tile {done}/{n_tiles} ({x0},{y0}) -> {int(keep.sum()) if keep.any() else 0} candidate(s)", file=sys.stderr)

    return all_boxes, all_scores, all_classes


def nms_per_class(boxes, scores, classes, iou_thresh=0.45):
    """cv2.dnn.NMSBoxes is class-agnostic, so run it per class instead
    (otherwise a car box could suppress an overlapping van box)."""
    keep_idx = []
    boxes_arr = np.array(boxes)
    scores_arr = np.array(scores)
    classes_arr = np.array(classes)
    for c in set(classes):
        idx = np.where(classes_arr == c)[0]
        if len(idx) == 0:
            continue
        b = boxes_arr[idx].tolist()
        s = scores_arr[idx].tolist()
        keep = cv2.dnn.NMSBoxes(b, s, score_threshold=0.0, nms_threshold=iou_thresh)
        if len(keep):
            keep = np.array(keep).flatten()
            keep_idx.extend(idx[keep].tolist())
    return keep_idx


def iou_xywh(a, b):
    ax1, ay1, aw, ah = a; bx1, by1, bw, bh = b
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0


def cross_class_dedup(boxes, scores, classes, keep_idx, iou_thresh=0.6):
    """Per-class NMS can still leave the same object detected twice under two
    different class guesses. Second pass across class boundaries: highest
    confidence first, drop anything overlapping an already-accepted box."""
    order = sorted(keep_idx, key=lambda i: -scores[i])
    accepted = []
    for i in order:
        if all(iou_xywh(boxes[i], boxes[j]) < iou_thresh for j in accepted):
            accepted.append(i)
    return accepted


def box_to_mosaic(x1, y1, w, h, m):
    """Maps a frame-local box into mosaic-pixel space using the sample's
    affine transform m=[a,b,c,d,e,f] (same transform the viewer uses to
    paint the frame). Transforms all four corners, not just top-left, so
    rotation from the drone's yaw doesn't throw off the box size."""
    a, b, c, d, e, f = m
    corners = [(x1, y1), (x1 + w, y1), (x1, y1 + h), (x1 + w, y1 + h)]
    mx = [a * u + c * v + e for u, v in corners]
    my = [b * u + d * v + f for u, v in corners]
    x0m, y0m = min(mx), min(my)
    return x0m, y0m, max(mx) - x0m, max(my) - y0m


def center_dist(a, b):
    ca = (a[0] + a[2] / 2, a[1] + a[3] / 2)
    cb = (b[0] + b[2] / 2, b[1] + b[3] / 2)
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def merge_detection(accumulated, box, class_id, class_name, conf, t, iou_thresh=0.3, dist_frac=0.6, min_dist_px=15.0):
    """Folds a new box into the running list if it's a re-sighting of an
    existing detection (keeps the higher-confidence box, keeps the
    original t_reveal), otherwise appends it as a new detection.

    "Same object" = IoU above iou_thresh OR centers close (within
    dist_frac * the larger box's size, floored at min_dist_px). IoU alone
    misses re-sightings where the box shrinks a lot (tile-boundary crop,
    motion blur); the distance check with a flat floor catches those."""
    for acc in accumulated:
        acc_box = (acc["x"], acc["y"], acc["w"], acc["h"])
        same = iou_xywh(acc_box, box) >= iou_thresh
        if not same:
            radius = max(dist_frac * max(acc_box[2], acc_box[3], box[2], box[3]), min_dist_px)
            same = center_dist(acc_box, box) <= radius
        if same:
            if conf > acc["conf"]:
                acc["x"], acc["y"], acc["w"], acc["h"] = (round(v, 1) for v in box)
                acc["class_id"], acc["class"], acc["conf"] = class_id, class_name, round(conf, 3)
            return
    x, y, w, h = box
    accumulated.append({
        "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1),
        "class_id": class_id, "class": class_name, "conf": round(conf, 3),
        "t_reveal": round(t, 2),
    })


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_path")
    ap.add_argument("model_onnx")
    ap.add_argument("data_json", help="stream's data.json from build_mosaic_transforms.py")
    ap.add_argument("out_json")
    ap.add_argument("--detect-every-sec", type=float, default=2.0,
                     help="run the detector roughly this often (seconds)")
    ap.add_argument("--tile", type=int, default=640)
    ap.add_argument("--overlap", type=int, default=160)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--merge-iou", type=float, default=0.3,
                     help="IoU threshold above which a sighting merges into an existing detection")
    ap.add_argument("--merge-dist-frac", type=float, default=0.6,
                     help="also merge if centers are within this fraction of box size")
    ap.add_argument("--merge-min-dist", type=float, default=15.0,
                     help="flat floor (px) under merge-dist-frac's radius")
    ap.add_argument("--min-box-dim", type=float, default=10.0,
                     help="reject candidate boxes smaller than this (mosaic px)")
    ap.add_argument("--classes", default=",".join(str(c) for c in DEFAULT_CLASSES),
                     help="comma-separated VisDrone class ids to keep (default: 3 = car)")
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after this many seconds of video")
    ap.add_argument("--verbose-tiles", action="store_true", help="log every tile's candidate count")
    args = ap.parse_args()

    keep_classes = set(int(c) for c in args.classes.split(","))

    data = json.load(open(args.data_json, encoding="utf-8"))
    samples = data["samples"]
    step_t = (samples[1]["t"] - samples[0]["t"]) if len(samples) > 1 else 0.5
    stride = max(1, round(args.detect_every_sec / step_t))
    selected = samples[::stride]
    if args.max_seconds is not None:
        selected = [s for s in selected if s["t"] <= args.max_seconds]
    print(f"{len(samples)} mosaic samples available ({step_t:.2f}s apart); running the detector on "
          f"every {stride}th one -> {len(selected)} frame(s), ~{args.detect_every_sec}s apart.", file=sys.stderr)

    cap = cv2.VideoCapture(args.video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    sess = ort.InferenceSession(args.model_onnx, providers=["CPUExecutionProvider"])

    accumulated = []
    frame_idx = 0
    target_i = 0
    t0 = time.time()
    while target_i < len(selected):
        target = selected[target_i]
        target_frame_idx = round(target["t"] * fps)
        ret = cap.grab()
        if not ret:
            break
        if frame_idx < target_frame_idx:
            frame_idx += 1
            continue
        ret, frame = cap.retrieve()
        if not ret:
            break

        boxes, scores, classes = run_tiled_inference(frame, sess, args.tile, args.overlap, args.conf, log=args.verbose_tiles)
        keep = nms_per_class(boxes, scores, classes, args.iou)
        keep = cross_class_dedup(boxes, scores, classes, keep)
        n_new = 0
        for i in keep:
            c = classes[i]
            if c not in keep_classes:
                continue
            mosaic_box = box_to_mosaic(*boxes[i], target["m"])
            if min(mosaic_box[2], mosaic_box[3]) < args.min_box_dim:
                continue  # too small to be real at this scale
            before = len(accumulated)
            merge_detection(accumulated, mosaic_box, c, VISDRONE_NAMES.get(c, str(c)), scores[i], target["t"],
                             args.merge_iou, args.merge_dist_frac, args.merge_min_dist)
            if len(accumulated) > before:
                n_new += 1

        elapsed = time.time() - t0
        print(f"[{target_i + 1}/{len(selected)}] t={target['t']:6.1f}s  "
              f"+{n_new} new  (running total: {len(accumulated)})  ({elapsed:.1f}s elapsed)", file=sys.stderr)

        frame_idx += 1
        target_i += 1
    cap.release()

    accumulated.sort(key=lambda d: d["t_reveal"])
    for i, d in enumerate(accumulated):
        d["id"] = f"det-{i:04d}"

    by_class = {}
    for d in accumulated:
        by_class[d["class"]] = by_class.get(d["class"], 0) + 1
    print("by class:", by_class, file=sys.stderr)

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump({
            "mosaic_width": data["mosaic_width"], "mosaic_height": data["mosaic_height"],
            "model": args.model_onnx, "conf_thresh": args.conf,
            "detect_every_sec": args.detect_every_sec,
            "detections": accumulated,
        }, f, ensure_ascii=False, indent=2)
    print(f"wrote {args.out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
