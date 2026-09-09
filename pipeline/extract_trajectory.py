#!/usr/bin/env python3
"""
Stage 1: visual odometry.

Estimates frame-to-frame camera motion from the video itself (ORB feature
matching + affine fit), no GPS needed. Outputs a raw per-sample trajectory
(cumulative transform to a running "world" pixel space, plus each frame's
corners/center in world space). Drift accumulates over a long flight and
gets corrected by loop_closure.py next -- see build_stream.py for the chain.

Usage: extract_trajectory.py <video> <out_raw_trajectory.json> [max_seconds]
"""
import cv2
import numpy as np
import json
import sys
import os
import time

def main(video_path, out_json, work_width=640, sample_every_sec=0.5, max_seconds=None):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = work_width / src_w
    work_h = int(src_h * scale)
    print(f"fps={fps:.2f} frames={total_frames} src={src_w}x{src_h} work={work_width}x{work_h}", file=sys.stderr)

    step = max(1, round(fps * sample_every_sec))

    orb = cv2.ORB_create(nfeatures=1500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    cum_T = np.eye(3, dtype=np.float64)

    prev_kp = None
    prev_des = None

    samples = []
    frame_idx = 0
    t0 = time.time()
    failed_chain = 0

    corners_src = np.array([[0, 0], [work_width, 0], [work_width, work_h], [0, work_h]], dtype=np.float64)

    while True:
        if max_seconds is not None and frame_idx / fps > max_seconds:
            break
        ret = cap.grab()
        if not ret:
            break
        if frame_idx % step != 0:
            frame_idx += 1
            continue
        ret, frame = cap.retrieve()
        if not ret:
            break

        small = cv2.resize(frame, (work_width, work_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        kp, des = orb.detectAndCompute(gray, None)

        if prev_des is not None and des is not None and len(kp) > 10 and len(prev_kp) > 10:
            matches = bf.knnMatch(prev_des, des, k=2)
            good = []
            for m_n in matches:
                if len(m_n) == 2:
                    m, n = m_n
                    if m.distance < 0.75 * n.distance:
                        good.append(m)
            if len(good) >= 8:
                src_pts = np.float32([prev_kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                dst_pts = np.float32([kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                M, inliers = cv2.estimateAffinePartial2D(dst_pts, src_pts, method=cv2.RANSAC,
                                                           ransacReprojThreshold=3.0)
                if M is not None and inliers is not None and inliers.sum() >= 8:
                    T_step = np.eye(3, dtype=np.float64)
                    T_step[:2, :] = M
                    cum_T = cum_T @ T_step
                else:
                    failed_chain += 1
            else:
                failed_chain += 1

        pts = np.hstack([corners_src, np.ones((4, 1))]).T
        world_pts = (cum_T @ pts).T
        world_pts = world_pts[:, :2] / world_pts[:, 2:3]
        center = world_pts.mean(axis=0)

        t = frame_idx / fps
        samples.append({
            "t": round(t, 3),
            "frame_idx": frame_idx,
            "corners": world_pts.round(2).tolist(),
            "center": center.round(2).tolist(),
            "T": cum_T.round(6).tolist(),
        })

        prev_kp, prev_des = kp, des
        frame_idx += 1

    cap.release()
    elapsed = time.time() - t0
    print(f"samples={len(samples)} failed_chain_steps={failed_chain} elapsed={elapsed:.1f}s", file=sys.stderr)

    with open(out_json, "w") as f:
        json.dump({
            "video": os.path.basename(video_path),
            "fps": fps,
            "work_width": work_width,
            "work_height": work_h,
            "src_width": src_w,
            "src_height": src_h,
            "sample_every_sec": sample_every_sec,
            "samples": samples,
        }, f)
    print(f"wrote {out_json}", file=sys.stderr)


if __name__ == "__main__":
    video = sys.argv[1]
    out = sys.argv[2]
    max_s = float(sys.argv[3]) if len(sys.argv) > 3 else None
    main(video, out, max_seconds=max_s)
