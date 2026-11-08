"""Rigid card pose in the TABLE frame from an overhead quad + aligned depth.

Display only. Never a motion target: the calibration is about +/-2 cm.
"""
import json
from pathlib import Path
import numpy as np

CARD_W, CARD_H = 0.0635, 0.0889  # poker card, metres
_G = np.linspace(.15, .85, 7)
_UV = np.array([(u, v) for u in _G for v in _G])
_W = np.stack([(1 - _UV[:, 0]) * (1 - _UV[:, 1]), _UV[:, 0] * (1 - _UV[:, 1]), _UV[:, 0] * _UV[:, 1], (1 - _UV[:, 0]) * _UV[:, 1]], axis=1)


def load_calibration(path=Path(__file__).with_name('top_camera_calibration.json')):
    T = np.array(json.load(open(path))['T_table_camera'], float)
    return T[:3, :3], T[:3, 3]


def _rays(points, k):
    points = np.asarray(points, float)
    return np.c_[(points[:, 0] - k['ppx']) / k['fx'], (points[:, 1] - k['ppy']) / k['fy'], np.ones(len(points))]


def _fit_plane(p):
    """Robust plane (n, d) with n.p + d = 0, normal toward the camera (n_z < 0)."""
    keep = np.ones(len(p), bool)
    for _ in range(3):
        c = p[keep].mean(0); _, _, vt = np.linalg.svd(p[keep] - c, full_matrices=False); n = vt[-1]
        r = np.abs((p - c) @ n)
        new = r < max(.004, 2.5 * np.median(r[keep]))
        if new.sum() < 8 or (new == keep).all(): break
        keep = new
    if n[2] > 0: n = -n
    return n, -n @ c, float(np.median(r[keep]))


def card_pose(quad, frame, table_plane, R, t):
    """quad: 4x2 image corners (ordered_quad order). table_plane: (a,b,c,d) camera frame or None.

    Returns {'corners': 4x3 table-frame corners of a true-size card, 'center', 'normal', 'height_mm', 'lifted'}.
    """
    k = frame['intrinsics']; depth = frame['depth_z16']; scale = frame['depth_scale_m']
    quad = np.asarray(quad, float)
    xy = np.rint(_W @ quad).astype(int)
    xy[:, 0] = np.clip(xy[:, 0], 0, k['width'] - 1); xy[:, 1] = np.clip(xy[:, 1], 0, k['height'] - 1)
    z = depth[xy[:, 1], xy[:, 0]].astype(float) * scale
    good = (z > .2) & (z < 2)
    plane = None; lifted = False
    if good.sum() >= 12:
        p = _rays(xy[good], k) * z[good, None]
        n, d, resid = _fit_plane(p)
        if table_plane is not None:
            tn = np.asarray(table_plane[:3]); h = float(np.median(p @ tn + table_plane[3]))
            # Only a card clearly off the felt gets its own plane; flat-fit noise near edges must not tilt it.
            lifted = h > .010
        else:
            lifted = True
        if lifted and resid < .006: plane = (n, d)
    table = (np.asarray(table_plane[:3]), table_plane[3] + .0003) if table_plane is not None else None
    if plane is None: plane = table
    if plane is None: return None
    rays = _rays(quad, k)
    for candidate in (plane, table):
        if candidate is None: return None
        n, d = candidate; denom = rays @ n
        if np.any(np.abs(denom) < 1e-6): return None
        c = (rays * (-d / denom)[:, None]) @ R.T + t
        # A fitted plane that puts the card under the felt is a bad depth fit, not a card: use the table plane.
        if c.mean(0)[2] >= -.005 or candidate is table: break
        lifted = False
    center = c.mean(0)
    # Measured size before the rigid fit (short edge c0-c1 / c2-c3, long edge c1-c2 / c3-c0): phones, boxes and
    # half-card proposals are rejected on it.
    size_mm = [float((np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) * 500), float((np.linalg.norm(c[2] - c[1]) + np.linalg.norm(c[3] - c[0])) * 500)]
    x = (c[1] - c[0]) + (c[2] - c[3]); y = (c[0] - c[3]) + (c[1] - c[2])
    normal = np.cross(x, y); normal /= np.linalg.norm(normal)
    x -= normal * (x @ normal); x /= np.linalg.norm(x); y = np.cross(normal, x)
    hw, hh = CARD_W / 2, CARD_H / 2
    corners = np.array([center - hw * x + hh * y, center + hw * x + hh * y, center + hw * x - hh * y, center - hw * x - hh * y])
    return {'corners': corners, 'center': center, 'normal': normal, 'height_mm': float(center[2] * 1000), 'lifted': bool(lifted), 'size_mm': size_mm}
