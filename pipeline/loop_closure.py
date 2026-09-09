#!/usr/bin/env python3
"""
Pose-graph drift correction for the visual-odometry chain. Detects when the
drone revisits already-covered ground (out-and-back, closed loop) and uses
those revisits to correct accumulated drift. If the video never revisits
itself, no loop closures are found and the trajectory is passed through
unchanged.

Loop closure candidates are verified with both forward and backward feature
matching (must agree), checked for a plausible inlier ratio and scale, then
solved with a robust least-squares fit. A final sanity check compares
corrected per-step speed against the raw trajectory; if the correction
implies an impossible speed spike, it's rejected and the uncorrected
trajectory ships instead.
"""
import cv2
import numpy as np
import json
import sys
from scipy.optimize import least_squares

ORB_FEATURES = 2500

def extract_node_frames(video_path, frame_indices, work_w, work_h):
    cap = cv2.VideoCapture(video_path)
    wanted = sorted(set(frame_indices))
    wi = 0
    idx = 0
    out = {}
    while wi < len(wanted):
        target = wanted[wi]
        ret = cap.grab()
        if not ret:
            break
        if idx == target:
            ret, frame = cap.retrieve()
            if ret:
                small = cv2.resize(frame, (work_w, work_h), interpolation=cv2.INTER_AREA)
                out[target] = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            wi += 1
        idx += 1
    cap.release()
    return out

def orb_match(orb, bf, gray_a, gray_b, kp_des_cache, key_a, key_b):
    if key_a not in kp_des_cache:
        kp_des_cache[key_a] = orb.detectAndCompute(gray_a, None)
    if key_b not in kp_des_cache:
        kp_des_cache[key_b] = orb.detectAndCompute(gray_b, None)
    kp_a, des_a = kp_des_cache[key_a]
    kp_b, des_b = kp_des_cache[key_b]
    if des_a is None or des_b is None or len(kp_a) < 10 or len(kp_b) < 10:
        return None
    matches = bf.knnMatch(des_b, des_a, k=2)
    good = []
    for m_n in matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < 0.75 * n.distance:
                good.append(m)
    if len(good) < 15:
        return None
    src = np.float32([kp_b[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_a[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                              confidence=0.995)
    if M is None or inliers is None:
        return None
    n_inl = int(inliers.sum())
    ratio = n_inl / max(1, len(good))
    return M, n_inl, ratio, len(good)

def affine_to_params(M):
    a, c, e = M[0]
    b, d, f = M[1]
    theta = np.arctan2(b, a)
    scale = np.hypot(a, b)
    return theta, scale, np.array([e, f])

def params_to_affine(theta, scale, t):
    ct, st = np.cos(theta), np.sin(theta)
    return np.array([[scale * ct, -scale * st, t[0]], [scale * st, scale * ct, t[1]]])

def invert_params(theta, scale, t):
    inv_scale = 1.0 / scale
    inv_theta = -theta
    R_inv = np.array([[np.cos(inv_theta), -np.sin(inv_theta)], [np.sin(inv_theta), np.cos(inv_theta)]])
    inv_t = -inv_scale * (R_inv @ t)
    return inv_theta, inv_scale, inv_t

def compose(theta_i, s_i, t_i, theta_ij, s_ij, t_ij):
    theta_j = theta_i + theta_ij
    s_j = s_i * s_ij
    R_i = np.array([[np.cos(theta_i), -np.sin(theta_i)], [np.sin(theta_i), np.cos(theta_i)]])
    t_j = s_i * (R_i @ t_ij) + t_i
    return theta_j, s_j, t_j

def find_loop_closures(nodes, frames, frame_idxs, min_gap_s, dist_thresh, top_k,
                        min_inliers=25, min_ratio=0.35, scale_bounds=(0.7, 1.43),
                        consist_angle_deg=8.0, consist_scale_frac=0.15, consist_trans_frac=0.15):
    n = len(nodes)
    centers = np.array([nd["center"] for nd in nodes])
    times = np.array([nd["t"] for nd in nodes])
    cand_per_i = {}
    for i in range(n):
        for j in range(i + 1, n):
            if times[j] - times[i] < min_gap_s:
                continue
            dist = np.linalg.norm(centers[i] - centers[j])
            if dist < dist_thresh:
                cand_per_i.setdefault(i, []).append((dist, j))
    candidates = []
    for i, lst in cand_per_i.items():
        lst.sort()
        for dist, j in lst[:top_k]:
            candidates.append((i, j))

    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    cache = {}

    accepted = []
    n_tried = 0
    for i, j in candidates:
        fi, fj = frame_idxs[i], frame_idxs[j]
        if fi not in frames or fj not in frames:
            continue
        n_tried += 1
        fwd = orb_match(orb, bf, frames[fi], frames[fj], cache, fi, fj)  # maps j -> i
        if fwd is None:
            continue
        M_fwd, n_inl_fwd, ratio_fwd, n_good_fwd = fwd
        if n_inl_fwd < min_inliers or ratio_fwd < min_ratio:
            continue
        theta_f, s_f, t_f = affine_to_params(M_fwd)
        if not (scale_bounds[0] <= s_f <= scale_bounds[1]):
            continue

        bwd = orb_match(orb, bf, frames[fj], frames[fi], cache, fj, fi)  # maps i -> j
        if bwd is None:
            continue
        M_bwd, n_inl_bwd, ratio_bwd, n_good_bwd = bwd
        if n_inl_bwd < min_inliers or ratio_bwd < min_ratio:
            continue
        theta_b, s_b, t_b = affine_to_params(M_bwd)

        # forward and inverse-of-backward should agree (mutual consistency check)
        theta_b_inv, s_b_inv, t_b_inv = invert_params(theta_b, s_b, t_b)
        dtheta = abs(np.degrees(np.arctan2(np.sin(theta_f - theta_b_inv), np.cos(theta_f - theta_b_inv))))
        dscale = abs(s_f - s_b_inv) / s_f
        dtrans = np.linalg.norm(t_f - t_b_inv) / max(1.0, np.linalg.norm(t_f))
        if dtheta > consist_angle_deg or dscale > consist_scale_frac or dtrans > consist_trans_frac:
            continue

        # keep loop-closure edges weighted lower than sequential (odometry)
        # edges, so a bad revisit match can't collapse a whole run of frames
        weight = min(1.2, 0.6 + n_inl_fwd / 150.0)
        accepted.append((i, j, theta_f, s_f, t_f, weight, n_inl_fwd))

    return accepted, n_tried, len(candidates)

def solve_pose_graph(n, edges, trans_norm, rot_norm, scale_norm, x0=None):
    # rot_norm/scale_norm scale the rotation and log-scale residuals to the
    # same range as the translation residuals, so the solver can't cheaply
    # inject spurious rotation just because it's numerically "cheap" next to
    # translation terms.
    def unpack(x):
        P = np.zeros((n, 4))
        P[1:] = x.reshape(n - 1, 4)
        return P

    def residuals(x, edge_list):
        P = unpack(x)
        res = []
        for (i, j, theta_ij, s_ij, t_ij, w) in edge_list:
            theta_i, log_s_i, tx_i, ty_i = P[i]
            theta_j, log_s_j, tx_j, ty_j = P[j]
            s_i = np.exp(log_s_i)
            pred_theta, pred_s, pred_t = compose(theta_i, s_i, np.array([tx_i, ty_i]), theta_ij, s_ij, t_ij)
            dtheta = np.arctan2(np.sin(theta_j - pred_theta), np.cos(theta_j - pred_theta)) / rot_norm
            dlogs = (log_s_j - np.log(pred_s)) / scale_norm
            dt = (np.array([tx_j, ty_j]) - pred_t) / trans_norm
            res.extend([w * dtheta, w * dlogs, w * dt[0], w * dt[1]])
        return np.array(res)

    if x0 is None:
        x0 = np.zeros((n - 1) * 4)
    sol = least_squares(lambda x: residuals(x, edges), x0, method="trf", loss="soft_l1", f_scale=1.0,
                         max_nfev=30000)
    return sol, unpack(sol.x)

def main(video_path, traj_path, out_path, node_step=2, min_gap_s=10.0, top_k=3):
    d = json.load(open(traj_path))
    samples = d["samples"]
    work_w, work_h = d["work_width"], d["work_height"]
    nodes = samples[::node_step]
    n = len(nodes)
    print(f"n nodes = {n}", file=sys.stderr)

    # adaptive distance threshold: ~0.5x typical frame footprint diagonal
    corners0 = np.array(nodes[0]["corners"])
    footprint_diag = np.linalg.norm(corners0[0] - corners0[2])
    dist_thresh = 0.55 * footprint_diag
    print(f"footprint_diag={footprint_diag:.1f} dist_thresh={dist_thresh:.1f}", file=sys.stderr)

    frame_idxs = [s["frame_idx"] for s in nodes]
    frames = extract_node_frames(video_path, frame_idxs, work_w, work_h)

    # sequential edges from existing VO chain
    seq_edges = []
    seq_disps = []
    for k in range(n - 1):
        Ti = np.array(nodes[k]["T"])
        Tj = np.array(nodes[k + 1]["T"])
        rel = np.linalg.inv(Ti) @ Tj
        theta_ij, s_ij, t_ij = affine_to_params(rel[:2, :])
        # sequential edges get a high fixed weight -- frame-to-frame VO is
        # much more reliable than any single loop-closure match
        seq_edges.append((k, k + 1, theta_ij, s_ij, t_ij, 6.0))
        seq_disps.append(np.linalg.norm(t_ij))
    seq_thetas = [e[2] for e in seq_edges]
    seq_logscales = [np.log(e[3]) for e in seq_edges]
    trans_norm = max(1.0, float(np.median(seq_disps)) * 3.0)
    # rotation/scale norms scale with this video's own VO noise, not fixed
    rot_norm = max(np.radians(0.5), float(np.median(np.abs(seq_thetas))) * 4.0)
    scale_norm = max(0.01, float(np.median(np.abs(seq_logscales))) * 4.0)
    print(f"median seq displacement={np.median(seq_disps):.2f}px, trans_norm={trans_norm:.2f}, "
          f"rot_norm={np.degrees(rot_norm):.3f}deg, scale_norm={scale_norm:.4f}", file=sys.stderr)

    loop_edges, n_tried, n_cand = find_loop_closures(nodes, frames, frame_idxs, min_gap_s, dist_thresh, top_k)
    print(f"loop closure candidates={n_cand} tried={n_tried} accepted={len(loop_edges)}", file=sys.stderr)
    loop_edges_full = [(i, j, th, s, t, w) for (i, j, th, s, t, w, ninl) in loop_edges]

    if len(loop_edges_full) == 0:
        print("no loop closures found -> passing trajectory through unchanged", file=sys.stderr)
        json.dump(d, open(out_path, "w"))
        return

    all_edges = seq_edges + loop_edges_full
    sol, P = solve_pose_graph(n, all_edges, trans_norm, rot_norm, scale_norm)
    print(f"solve success={sol.success} cost={sol.cost:.4f}", file=sys.stderr)

    # ---- outlier pruning pass: drop loop edges with high residual, re-solve ----
    def edge_residual(i, j, theta_ij, s_ij, t_ij, P):
        theta_i, log_s_i, tx_i, ty_i = P[i]
        theta_j, log_s_j, tx_j, ty_j = P[j]
        s_i = np.exp(log_s_i)
        pred_theta, pred_s, pred_t = compose(theta_i, s_i, np.array([tx_i, ty_i]), theta_ij, s_ij, t_ij)
        dt = np.linalg.norm(np.array([tx_j, ty_j]) - pred_t)
        return dt

    resids = [edge_residual(i, j, th, s, t, P) for (i, j, th, s, t, w) in loop_edges_full]
    if resids:
        med = np.median(resids)
        keep = [r < max(30.0, 6 * med) for r in resids]
        n_dropped = len(keep) - sum(keep)
        if n_dropped > 0:
            print(f"pruning {n_dropped}/{len(loop_edges_full)} high-residual loop edges, re-solving", file=sys.stderr)
            loop_edges_full = [e for e, k in zip(loop_edges_full, keep) if k]
            all_edges = seq_edges + loop_edges_full
            sol, P = solve_pose_graph(n, all_edges, trans_norm, rot_norm, scale_norm)
            print(f"re-solve success={sol.success} cost={sol.cost:.4f}", file=sys.stderr)

    # ---- refinement pass: tighten loop-closure agreement, warm-started -----
    # The first solve keeps loop-closure edges low-weight so a bad revisit
    # match can't collapse a run of sequential edges, but that leaves good
    # loop edges under-satisfied. Re-solve the same edges with loop-closure
    # trust raised in steps, warm-started from the previous solution each
    # time so the higher trust only needs small local corrections instead of
    # re-discovering the whole layout. Stops early if a step fails to
    # converge; keeps the last successful result.
    if loop_edges_full:
        SEQ_WEIGHT = 6.0
        P_stage, sol_stage = P, sol
        for boost, cap_frac in [(3.0, 0.75), (6.0, 0.9), (10.0, 0.95)]:
            refined_loop_edges = [(i, j, th, s, t, min(SEQ_WEIGHT * cap_frac, w * boost))
                                   for (i, j, th, s, t, w) in loop_edges_full]
            refine_edges = seq_edges + refined_loop_edges
            x0_warm = P_stage[1:].reshape(-1)
            sol_refine, P_refine = solve_pose_graph(n, refine_edges, trans_norm, rot_norm, scale_norm, x0=x0_warm)
            resids_before = [edge_residual(i, j, th, s, t, P_stage) for (i, j, th, s, t, w) in loop_edges_full]
            resids_after = [edge_residual(i, j, th, s, t, P_refine) for (i, j, th, s, t, w) in loop_edges_full]
            print(f"refine(boost={boost}) success={sol_refine.success} cost={sol_refine.cost:.4f} "
                  f"loop-edge residual median: {np.median(resids_before):.2f}px -> {np.median(resids_after):.2f}px "
                  f"max: {np.max(resids_before):.2f}px -> {np.max(resids_after):.2f}px", file=sys.stderr)
            if not sol_refine.success:
                print(f"  refine(boost={boost}) did not converge -> stopping refinement here", file=sys.stderr)
                break
            P_stage, sol_stage = P_refine, sol_refine
        sol, P = sol_stage, P_stage

    node_T = []
    for k in range(n):
        theta, log_s, tx, ty = P[k]
        M = params_to_affine(theta, np.exp(log_s), np.array([tx, ty]))
        T = np.eye(3)
        T[:2, :] = M
        node_T.append(T)

    # ---- rebuild full per-sample corrected T (interpolating between nodes) ----
    node_times = [nd["t"] for nd in nodes]

    def corrected_T_at(raw_T, raw_T_before, raw_T_after, Tc_before, Tc_after, alpha):
        # anchor raw motion locally at each bracketing node before applying
        # its correction, rather than applying the correction directly to a
        # pose far from the origin (which would amplify small per-node
        # rotation differences into large speed spikes)
        local_before = np.linalg.inv(raw_T_before) @ raw_T
        local_after = np.linalg.inv(raw_T_after) @ raw_T
        cand_before = Tc_before @ local_before
        cand_after = Tc_after @ local_after
        theta_b, s_b, t_b = affine_to_params(cand_before[:2])
        theta_a, s_a, t_a = affine_to_params(cand_after[:2])
        dtheta = np.arctan2(np.sin(theta_a - theta_b), np.cos(theta_a - theta_b))
        theta = theta_b + alpha * dtheta
        s = s_b + alpha * (s_a - s_b)
        t = t_b + alpha * (t_a - t_b)
        Tc = np.eye(3)
        Tc[:2] = params_to_affine(theta, s, t)
        return Tc

    # Tc maps LOCAL work-pixel coords -> corrected-world, same as raw "T".
    # corrected corners/center must be computed from the fixed local points,
    # not by re-applying Tc to the already-world raw corners/center.
    local_corners = np.array([[0, 0], [work_w, 0], [work_w, work_h], [0, work_h]], dtype=np.float64)
    local_center_pt = np.array([work_w / 2.0, work_h / 2.0])

    out_samples = []
    for s in samples:
        t_time = s["t"]
        raw_T = np.array(s["T"])
        if t_time <= node_times[0]:
            Tc = node_T[0] @ np.linalg.inv(np.array(nodes[0]["T"])) @ raw_T
        elif t_time >= node_times[-1]:
            Tc = node_T[-1] @ np.linalg.inv(np.array(nodes[-1]["T"])) @ raw_T
        else:
            lo = np.searchsorted(node_times, t_time) - 1
            lo = max(0, min(lo, n - 2))
            hi = lo + 1
            alpha = (t_time - node_times[lo]) / (node_times[hi] - node_times[lo] or 1)
            Tc = corrected_T_at(raw_T, np.array(nodes[lo]["T"]), np.array(nodes[hi]["T"]),
                                 node_T[lo], node_T[hi], alpha)
        pts = np.hstack([local_corners, np.ones((4, 1))]).T
        world_pts = (Tc @ pts).T
        world_pts = world_pts[:, :2] / world_pts[:, 2:3]
        center_pt = (Tc @ np.array([*local_center_pt, 1.0]))
        center_pt = (center_pt[:2] / center_pt[2]).tolist()
        out_samples.append({
            "t": s["t"], "frame_idx": s["frame_idx"],
            "corners": world_pts.round(2).tolist(),
            "center": [round(v, 2) for v in center_pt],
            "T": Tc.round(6).tolist(),
        })

    # ---- sanity check on the actual per-sample trajectory being shipped ----
    raw_speeds = []
    corr_speeds = []
    for k in range(len(samples) - 1):
        c0_raw = np.array(samples[k]["center"])
        c1_raw = np.array(samples[k + 1]["center"])
        raw_speeds.append(np.linalg.norm(c1_raw - c0_raw))
        c0_c = np.array(out_samples[k]["center"])
        c1_c = np.array(out_samples[k + 1]["center"])
        corr_speeds.append(np.linalg.norm(c1_c - c0_c))
    raw_speeds = np.array(raw_speeds)
    corr_speeds = np.array(corr_speeds)
    typical = max(1.0, float(np.median(raw_speeds)))

    def moving_median(a, win):
        if win < 3:
            return a.copy()
        half = win // 2
        out = np.empty_like(a)
        for i in range(len(a)):
            lo = max(0, i - half)
            hi = min(len(a), i + half + 1)
            out[i] = np.median(a[lo:hi])
        return out

    # two checks: a sustained speed-ratio shift can be legitimate (drift
    # redistribution), but a sharp discontinuity (marker teleporting) never is

    # 1) sustained-level check on smoothed speeds
    raw_smooth = moving_median(raw_speeds, 9)
    corr_smooth = moving_median(corr_speeds, 9)
    sustained_ratio = float((corr_smooth / np.maximum(raw_smooth, 0.15 * typical)).max())

    # 2) discontinuity check on raw corrected speeds vs local neighborhood
    corr_local_baseline = np.maximum(moving_median(corr_speeds, 9), 0.15 * max(1.0, float(np.median(corr_speeds))))
    jump_ratio = float((corr_speeds / corr_local_baseline).max())

    print(f"per-sample speed sanity: median raw={np.median(raw_speeds):.2f} median corr={np.median(corr_speeds):.2f} "
          f"sustained_ratio={sustained_ratio:.2f} jump_ratio={jump_ratio:.2f}", file=sys.stderr)

    if sustained_ratio > 6.0 or jump_ratio > 5.0 or not sol.success:
        print("SANITY CHECK FAILED (implausible speed spike / discontinuity) -> rejecting correction, "
              "shipping uncorrected trajectory instead", file=sys.stderr)
        json.dump(d, open(out_path, "w"))
        return

    out = dict(d)
    out["samples"] = out_samples
    out["loop_closures_used"] = len(loop_edges_full)
    json.dump(out, open(out_path, "w"))
    print(f"wrote {out_path} (corrected, {len(loop_edges_full)} loop closures used)", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
