import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# H3 Audit-Fix: Absoluter Pfad statt relativ zum CWD
MODELS_DIR = PROJECT_ROOT / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
YUNET_PATH = MODELS_DIR / "yunet.onnx"

AVAILABLE_CAM_FILTERS = {
    "none": "🚫 Kein Filter (Original Facecam)",
    # 🔺 3D Geometrische Prismen / Low-Poly Modelle (Snapchat Origami)
    "triangle": "🔺 3D Dreimacs Pyramide (Prismen-Kopf)",
    "inv_triangle": "🔻 3D Trichter-Kopf (Megastirn, spitzes Kinn)",
    "diamond": "💎 3D Diamant-Kopf (Kristall-Facette)",
    "cube": "📦 3D Block-Kopf (Minecraft Steve)",
    # 🧬 Moving Least Squares (MLS) Anatomische Gesichts-Morphs
    "gigachad": "🗿 3D Gigachad (Breiter Meme-Kiefer)",
    "alien": "👽 3D Megamind / Alien (Riesen-Kuppelkopf)",
    "hamster": "🎈 3D Hamsterbacken (Prall aufgeblasen)",
    "pinocchio": "🤥 3D Pinocchio (Lange Nase)",
    "big_eyes": "👀 3D Glubschaugen (Anime / Manga)",
    "tiny_face": "🤏 3D Schrumpf-Gesicht (Charlie Kirk Meme)",
    "big_mouth": "👄 3D Riesenmund (Scream / Opernsänger)",
    # 🌀 Optische Linsen- & Verzerrungs-Filter
    "hourglass": "⏳ 3D Sanduhr (Wespentaille im Gesicht)",
    "fisheye": "🐟 3D Glaskugel-Bulge (Linsen-Zoom)",
    "swirl": "🌀 3D Strudel / Wirbel (Vortex-Twist)",
    "wave": "🌊 3D Wackelpudding (Wobble-Welle)",
    "mirror_left": "🪞 Doppel-Links (Alien-Symmetrie)",
    "mirror_right": "🪞 Doppel-Rechts (Alien-Symmetrie)",
    "stretch_vert": "📏 Bleistift-Kopf (Langgezogen)",
    "squish_wide": "🗜️ Wide Meme (Pfannkuchen-Kopf)"
}

_DETECTOR_CACHE = {}

def get_face_detector(width: int, height: int):
    """Gibt eine gecachte Instanz des YuNet-Detektors zurueck."""
    if not YUNET_PATH.exists():
        return None
    key = (width, height)
    if key not in _DETECTOR_CACHE:
        try:
            det = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (width, height), score_threshold=0.6)
            _DETECTOR_CACHE[key] = det
        except Exception:
            return None
    return _DETECTOR_CACHE[key]

def safe_remap(frame: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    """Führt cv2.remap mit garantierter float32 Typisierung aus."""
    mx = map_x.astype(np.float32, copy=False) if map_x.dtype != np.float32 else map_x
    my = map_y.astype(np.float32, copy=False) if map_y.dtype != np.float32 else map_y
    return cv2.remap(frame, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT_101)

def apply_mls_morph(
    h: int, w: int,
    fx: float, fy: float, fw: float, fh: float,
    p_pts: np.ndarray, q_pts: np.ndarray,
    alpha: float = 1.0
) -> Tuple[np.ndarray, np.ndarray]:
    """Berechnet Moving-Least-Squares (MLS) Deformationsmatrizen fuer Gesichts-Landmarks.
    Verwendet einen aeusseren Ring fixer Ankerpunkte, damit der Hintergrund 100% statisch bleibt.
    """
    pad = int(max(fw, fh) * 0.45)
    x1 = max(0, int(fx - pad))
    y1 = max(0, int(fy - pad))
    x2 = min(w, int(fx + fw + pad))
    y2 = min(h, int(fy + fh + pad))

    roi_h = y2 - y1
    roi_w = x2 - x1

    # Äußerer Ankerring: 16 fixe Punkte um das Gesicht herum
    n_ring = 16
    angles = np.linspace(0, 2 * np.pi, n_ring, endpoint=False, dtype=np.float32)
    rx = fw * 0.95
    ry = fh * 1.05
    cx = fx + fw * 0.5
    cy = fy + fh * 0.5
    ring_x = cx + rx * np.cos(angles)
    ring_y = cy + ry * np.sin(angles)
    boundary_pts = np.stack([ring_x, ring_y], axis=1).astype(np.float32)

    all_p = np.vstack([p_pts, boundary_pts]).astype(np.float32)
    all_q = np.vstack([q_pts, boundary_pts]).astype(np.float32)

    y_idx, x_idx = np.indices((roi_h, roi_w), dtype=np.float32)
    v_x = x_idx + x1
    v_y = y_idx + y1

    dx = v_x[:, :, None] - all_q[:, 0]
    dy = v_y[:, :, None] - all_q[:, 1]
    d2 = dx**2 + dy**2
    weights = 1.0 / (d2 + 1e-4) ** alpha
    sum_w = np.sum(weights, axis=-1, keepdims=True)

    disp = (all_p - all_q).astype(np.float32)
    v_disp = np.sum(weights[:, :, :, None] * disp[None, None, :, :], axis=2) / sum_w

    map_x = np.indices((h, w), dtype=np.float32)[1]
    map_y = np.indices((h, w), dtype=np.float32)[0]
    map_x[y1:y2, x1:x2] = v_x + v_disp[:, :, 0]
    map_y[y1:y2, x1:x2] = v_y + v_disp[:, :, 1]
    return map_x, map_y

def filter_cam_frame_3d(
    frame: np.ndarray,
    filter_name: str,
    tracker_state: dict,
    detector=None,
    frame_idx: int = 0
) -> np.ndarray:
    """Wendet einen echten anatomischen 3D-Gesichtsfilter auf das Bild an.
    
    Der Hintergrund (Zimmer, Gaming-Chair, Mikrofon, Schultern) bleibt 100% erhalten!
    Nur der Kopf / das Gesicht wird anatomisch erkannt und in das 3D-Modell verwandelt.
    """
    if not filter_name or filter_name == "none":
        return frame

    h, w = frame.shape[:2]

    # 1. Face Tracking & Glättung
    needs_detect = (tracker_state.get("box") is None) or (frame_idx % 4 == 0)
    
    if needs_detect and detector is not None:
        try:
            detector.setInputSize((w, h))
            ret, faces = detector.detect(frame)
            if faces is not None and len(faces) > 0:
                f = faces[0]
                t_box = f[0:4].astype(np.float32)
                t_re = f[4:6].astype(np.float32)
                t_le = f[6:8].astype(np.float32)
                t_nt = f[8:10].astype(np.float32)
                t_rc = f[10:12].astype(np.float32)
                t_lc = f[12:14].astype(np.float32)
                t_eyes_y = (t_re[1] + t_le[1]) / 2.0
                
                if tracker_state.get("box") is None:
                    tracker_state["box"] = t_box
                    tracker_state["re"] = t_re
                    tracker_state["le"] = t_le
                    tracker_state["nt"] = t_nt
                    tracker_state["rc"] = t_rc
                    tracker_state["lc"] = t_lc
                    tracker_state["eyes_y"] = float(t_eyes_y)
                else:
                    tracker_state["box"] = tracker_state["box"] * 0.72 + t_box * 0.28
                    tracker_state["re"] = tracker_state["re"] * 0.72 + t_re * 0.28
                    tracker_state["le"] = tracker_state["le"] * 0.72 + t_le * 0.28
                    tracker_state["nt"] = tracker_state["nt"] * 0.72 + t_nt * 0.28
                    tracker_state["rc"] = tracker_state["rc"] * 0.72 + t_rc * 0.28
                    tracker_state["lc"] = tracker_state["lc"] * 0.72 + t_lc * 0.28
                    tracker_state["eyes_y"] = tracker_state["eyes_y"] * 0.72 + t_eyes_y * 0.28
        except Exception:
            pass

    if tracker_state.get("box") is not None:
        fx, fy, fw, fh = tracker_state["box"]
        nt_x, nt_y = tracker_state["nt"]
        eyes_y = tracker_state["eyes_y"]
        cx = float(nt_x)
        cy = float(eyes_y + fh * 0.08)
        rx = float(fw * 0.85)
        ry = float(fh * 0.95)
    else:
        cx = float(w * 0.5)
        cy = float(h * 0.45)
        rx = float(w * 0.25)
        ry = float(h * 0.35)
        fw, fh = rx * 1.2, ry * 1.1
        fx, fy = cx - fw * 0.5, cy - fh * 0.5

    # Landmarks vorbereiten
    re = tracker_state.get("re", np.array([cx - fw * 0.22, cy - fh * 0.12], dtype=np.float32))
    le = tracker_state.get("le", np.array([cx + fw * 0.22, cy - fh * 0.12], dtype=np.float32))
    nt = tracker_state.get("nt", np.array([cx, cy], dtype=np.float32))
    rc = tracker_state.get("rc", np.array([cx - fw * 0.18, cy + fh * 0.25], dtype=np.float32))
    lc = tracker_state.get("lc", np.array([cx + fw * 0.18, cy + fh * 0.25], dtype=np.float32))

    chin = np.array([cx, fy + fh], dtype=np.float32)
    forehead = np.array([cx, fy + fh * 0.08], dtype=np.float32)
    jaw_l = np.array([fx + fw * 0.15, fy + fh * 0.8], dtype=np.float32)
    jaw_r = np.array([fx + fw * 0.85, fy + fh * 0.8], dtype=np.float32)
    temple_l = np.array([fx + fw * 0.12, fy + fh * 0.25], dtype=np.float32)
    temple_r = np.array([fx + fw * 0.88, fy + fh * 0.25], dtype=np.float32)
    cheek_l = np.array([fx + fw * 0.2, fy + fh * 0.55], dtype=np.float32)
    cheek_r = np.array([fx + fw * 0.8, fy + fh * 0.55], dtype=np.float32)

    # Koordinaten-Gitter
    y_grid, x_grid = np.indices((h, w), dtype=np.float32)
    dx = (x_grid - cx) / np.maximum(10.0, rx)
    dy = (y_grid - cy) / np.maximum(10.0, ry)
    r2 = dx**2 + dy**2

    # Saubere elliptische Maske um den Kopf mit sanftem Rand-Übergang
    inside_mask = np.clip(1.0 - (r2 - 0.7) / 0.3, 0.0, 1.0)
    inside_mask = inside_mask * inside_mask * (3.0 - 2.0 * inside_mask) # Smoothstep

    # =========================================================================
    # 🔺 1. 3D Dreimacs Pyramide (Prismen-Kopf mit Facetten)
    # =========================================================================
    if filter_name == "triangle":
        v = np.clip((dy + 0.95) / 1.9, 0.001, 1.0)
        half_w = rx * (0.05 + 1.35 * (v ** 0.92))
        u = (x_grid - cx) / np.maximum(1.0, half_w)
        in_pyr = (np.abs(u) <= 1.0) & (dy >= -0.98) & (dy <= 1.08)

        src_x = cx + u * rx * 0.88
        src_y = cy + (v - 0.5) * ry * 1.6
        ridge_factor = np.exp(-((x_grid - cx) / max(1.0, fw * 0.35))**2)
        src_y_adj = src_y - ridge_factor * (fh * 0.07)

        feather = np.clip((1.0 - np.abs(u)) / 0.08, 0.0, 1.0)
        w_pyr = in_pyr.astype(np.float32) * inside_mask * feather

        map_x = x_grid * (1.0 - w_pyr) + src_x * w_pyr
        map_y = y_grid * (1.0 - w_pyr) + src_y_adj * w_pyr
        result = safe_remap(frame, map_x, map_y)

        # 3D Facetten-Beleuchtung (Links Schatten, Rechts Glanzlicht)
        res_f = result.astype(np.float32)
        left_facet = (u < 0) & (w_pyr > 0.35)
        right_facet = (u >= 0) & (w_pyr > 0.35)
        res_f[left_facet] *= (0.82 + 0.14 * (1.0 + u[left_facet]))[:, None]
        res_f[right_facet] = np.clip(res_f[right_facet] * (1.14 - 0.10 * u[right_facet])[:, None] + 6, 0, 255)
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 🔻 2. 3D Trichter-Kopf (Umgekehrte Pyramide)
    # =========================================================================
    elif filter_name == "inv_triangle":
        v = np.clip((0.95 - dy) / 1.9, 0.001, 1.0)
        half_w = rx * (0.05 + 1.35 * (v ** 0.92))
        u = (x_grid - cx) / np.maximum(1.0, half_w)
        in_pyr = (np.abs(u) <= 1.0) & (dy >= -1.08) & (dy <= 0.98)

        src_x = cx + u * rx * 0.88
        src_y = cy + (0.5 - v) * ry * 1.6
        feather = np.clip((1.0 - np.abs(u)) / 0.08, 0.0, 1.0)
        w_pyr = in_pyr.astype(np.float32) * inside_mask * feather

        map_x = x_grid * (1.0 - w_pyr) + src_x * w_pyr
        map_y = y_grid * (1.0 - w_pyr) + src_y * w_pyr
        result = safe_remap(frame, map_x, map_y)

        res_f = result.astype(np.float32)
        left_facet = (u < 0) & (w_pyr > 0.35)
        right_facet = (u >= 0) & (w_pyr > 0.35)
        res_f[left_facet] *= (0.82 + 0.14 * (1.0 + u[left_facet]))[:, None]
        res_f[right_facet] = np.clip(res_f[right_facet] * (1.14 - 0.10 * u[right_facet])[:, None] + 6, 0, 255)
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 💎 3. 3D Diamant-Kopf (Kristall-Facette)
    # =========================================================================
    elif filter_name == "diamond":
        v_d = np.clip((dy + 1.0) / 2.0, 0.001, 0.999)
        half_w_d = rx * 1.35 * (1.0 - 1.8 * np.abs(v_d - 0.5))
        half_w_d = np.maximum(4.0, half_w_d)
        u_d = (x_grid - cx) / half_w_d
        in_diamond = (np.abs(u_d) <= 1.0) & (dy >= -1.0) & (dy <= 1.0)

        src_x = cx + u_d * rx * 0.85
        src_y = cy + (v_d - 0.5) * ry * 1.6
        feather = np.clip((1.0 - np.abs(u_d)) / 0.1, 0.0, 1.0)
        w_d = in_diamond.astype(np.float32) * inside_mask * feather

        map_x = x_grid * (1.0 - w_d) + src_x * w_d
        map_y = y_grid * (1.0 - w_d) + src_y * w_d
        result = safe_remap(frame, map_x, map_y)

        res_f = result.astype(np.float32)
        res_f[(u_d >= 0) & (v_d < 0.5) & (w_d > 0.3)] = np.clip(res_f[(u_d >= 0) & (v_d < 0.5) & (w_d > 0.3)] * 1.15 + 10, 0, 255)
        res_f[(u_d < 0) & (v_d >= 0.5) & (w_d > 0.3)] *= 0.82
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 📦 4. 3D Block-Kopf (Minecraft Steve)
    # =========================================================================
    elif filter_name == "cube":
        in_cube = (np.abs(dx) <= 0.85) & (np.abs(dy) <= 0.85)
        u_c = np.clip(dx / 0.85, -1.0, 1.0)
        v_c = np.clip(dy / 0.85, -1.0, 1.0)
        src_x = cx + u_c * rx * 0.9
        src_y = cy + v_c * ry * 0.9
        w_c = in_cube.astype(np.float32) * inside_mask

        map_x = x_grid * (1.0 - w_c) + src_x * w_c
        map_y = y_grid * (1.0 - w_c) + src_y * w_c
        result = safe_remap(frame, map_x, map_y)

        res_f = result.astype(np.float32)
        res_f[(dx > 0.65) & (w_c > 0.3)] *= 0.80 # Schattenseite
        res_f[(dy < -0.65) & (w_c > 0.3)] = np.clip(res_f[(dy < -0.65) & (w_c > 0.3)] * 1.18 + 12, 0, 255) # Lichtseite
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 🗿 5. 3D Gigachad (Breiter Meme-Kiefer mit MLS)
    # =========================================================================
    elif filter_name == "gigachad":
        chin_tgt = np.array([cx, fy + fh * 1.35], dtype=np.float32)
        jaw_l_tgt = np.array([fx - fw * 0.28, fy + fh * 1.05], dtype=np.float32)
        jaw_r_tgt = np.array([fx + fw * 1.28, fy + fh * 1.05], dtype=np.float32)
        cheek_l_tgt = np.array([fx + fw * 0.28, fy + fh * 0.55], dtype=np.float32)
        cheek_r_tgt = np.array([fx + fw * 0.72, fy + fh * 0.55], dtype=np.float32)

        p_pts = np.vstack([re, le, nt, rc, lc, chin, jaw_l, jaw_r, cheek_l, cheek_r, forehead])
        q_pts = np.vstack([re, le, nt, rc, lc, chin_tgt, jaw_l_tgt, jaw_r_tgt, cheek_l_tgt, cheek_r_tgt, forehead])
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        result = safe_remap(frame, map_x, map_y)

        # Kantiger Schatten unter der Kieferlinie
        jaw_shadow = (dy > 0.48) & (np.abs(dx) < 0.95) & (inside_mask > 0.25)
        res_f = result.astype(np.float32)
        res_f[jaw_shadow] *= 0.82
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 👽 6. 3D Megamind / Alien (Riesen-Kuppelkopf mit MLS)
    # =========================================================================
    elif filter_name == "alien":
        forehead_tgt = np.array([cx, fy - fh * 0.45], dtype=np.float32)
        temple_l_tgt = np.array([fx - fw * 0.35, fy + fh * 0.05], dtype=np.float32)
        temple_r_tgt = np.array([fx + fw * 1.35, fy + fh * 0.05], dtype=np.float32)
        chin_tgt = np.array([cx, fy + fh * 0.88], dtype=np.float32)
        jaw_l_tgt = np.array([fx + fw * 0.32, fy + fh * 0.8], dtype=np.float32)
        jaw_r_tgt = np.array([fx + fw * 0.68, fy + fh * 0.8], dtype=np.float32)

        p_pts = np.vstack([forehead, temple_l, temple_r, re, le, nt, chin, jaw_l, jaw_r])
        q_pts = np.vstack([forehead_tgt, temple_l_tgt, temple_r_tgt, re, le, nt, chin_tgt, jaw_l_tgt, jaw_r_tgt])
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        result = safe_remap(frame, map_x, map_y)

        # Kuppel-Glanzlicht oben
        highlight = np.exp(-((x_grid - cx)**2 + (y_grid - (cy - ry*0.65))**2) / max(1.0, (rx*0.55)**2))
        res_f = result.astype(np.float32)
        res_f += (highlight * inside_mask * 45)[:, :, None]
        return res_f.clip(0, 255).astype(np.uint8)

    # =========================================================================
    # 🎈 7. 3D Hamsterbacken (Prall aufgeblasen mit MLS)
    # =========================================================================
    elif filter_name == "hamster":
        cheek_l_tgt = np.array([fx - fw * 0.40, fy + fh * 0.65], dtype=np.float32)
        cheek_r_tgt = np.array([fx + fw * 1.40, fy + fh * 0.65], dtype=np.float32)
        jaw_l_tgt = np.array([fx - fw * 0.25, fy + fh * 0.90], dtype=np.float32)
        jaw_r_tgt = np.array([fx + fw * 1.25, fy + fh * 0.90], dtype=np.float32)

        p_pts = np.vstack([re, le, nt, rc, lc, chin, forehead, cheek_l, cheek_r, jaw_l, jaw_r])
        q_pts = np.vstack([re, le, nt, rc, lc, chin, forehead, cheek_l_tgt, cheek_r_tgt, jaw_l_tgt, jaw_r_tgt])
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 🤥 8. 3D Pinocchio (Lange Nase mit MLS)
    # =========================================================================
    elif filter_name == "pinocchio":
        nt_tgt = np.array([cx, cy + fh * 0.55], dtype=np.float32)
        chin_tgt = np.array([cx, fy + fh * 1.08], dtype=np.float32)
        p_pts = np.vstack([re, le, nt, rc, lc, chin, forehead, cheek_l, cheek_r])
        q_pts = np.vstack([re, le, nt_tgt, rc, lc, chin_tgt, forehead, cheek_l, cheek_r])
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 👀 9. 3D Glubschaugen (Anime / Manga)
    # =========================================================================
    elif filter_name == "big_eyes":
        d_re = np.sqrt(((x_grid - re[0]) / max(10.0, fw * 0.24))**2 + ((y_grid - re[1]) / max(10.0, fh * 0.20))**2)
        d_le = np.sqrt(((x_grid - le[0]) / max(10.0, fw * 0.24))**2 + ((y_grid - le[1]) / max(10.0, fh * 0.20))**2)
        bulge_re = np.where(d_re < 1.0, np.cos(d_re * np.pi * 0.5) * 0.65, 0.0)
        bulge_le = np.where(d_le < 1.0, np.cos(d_le * np.pi * 0.5) * 0.65, 0.0)
        map_x = x_grid - (x_grid - re[0]) * bulge_re - (x_grid - le[0]) * bulge_le
        map_y = y_grid - (y_grid - re[1]) * bulge_re - (y_grid - le[1]) * bulge_le
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 🤏 10. 3D Schrumpf-Gesicht (Charlie Kirk Meme mit MLS)
    # =========================================================================
    elif filter_name == "tiny_face":
        center_face = np.array([cx, cy + fh * 0.05], dtype=np.float32)
        p_pts = np.vstack([re, le, nt, rc, lc, chin, forehead, cheek_l, cheek_r, jaw_l, jaw_r])
        q_pts = p_pts.copy()
        for i in range(5):
            q_pts[i] = center_face + (p_pts[i] - center_face) * 0.35
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 👄 11. 3D Riesenmund (Scream / Opernsänger mit MLS)
    # =========================================================================
    elif filter_name == "big_mouth":
        rc_tgt = np.array([rc[0] - fw * 0.28, rc[1] + fh * 0.12], dtype=np.float32)
        lc_tgt = np.array([lc[0] + fw * 0.28, lc[1] + fh * 0.12], dtype=np.float32)
        chin_tgt = np.array([cx, fy + fh * 1.30], dtype=np.float32)
        p_pts = np.vstack([re, le, nt, rc, lc, chin, forehead, cheek_l, cheek_r])
        q_pts = np.vstack([re, le, nt, rc_tgt, lc_tgt, chin_tgt, forehead, cheek_l, cheek_r])
        map_x, map_y = apply_mls_morph(h, w, fx, fy, fw, fh, p_pts, q_pts)
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # ⏳ 12. 3D Sanduhr (Wespentaille im Gesicht)
    # =========================================================================
    elif filter_name == "hourglass":
        scale_x = 0.52 + 0.70 * (np.clip(dy, -1.0, 1.0) ** 2)
        src_x = cx + (x_grid - cx) / np.maximum(0.15, scale_x)
        map_x = x_grid * (1.0 - inside_mask) + src_x * inside_mask
        return safe_remap(frame, map_x, y_grid)

    # =========================================================================
    # 🐟 13. 3D Glaskugel-Bulge (Linsen-Zoom auf Nase)
    # =========================================================================
    elif filter_name == "fisheye":
        r = np.sqrt(r2)
        bulge = np.where(r < 1.0, np.sin(r * np.pi / 2.0) / np.maximum(1e-4, r), 1.0)
        src_x = cx + (x_grid - cx) * bulge
        src_y = cy + (y_grid - cy) * bulge
        map_x = x_grid * (1.0 - inside_mask) + src_x * inside_mask
        map_y = y_grid * (1.0 - inside_mask) + src_y * inside_mask
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 🌀 14. 3D Strudel / Wirbel (Vortex-Twist)
    # =========================================================================
    elif filter_name == "swirl":
        r = np.sqrt(r2)
        angle = (1.0 - np.clip(r, 0.0, 1.0)) * 1.35 * inside_mask
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        rx_c = x_grid - cx
        ry_c = y_grid - cy
        map_x = cx + rx_c * cos_a - ry_c * sin_a
        map_y = cy + rx_c * sin_a + ry_c * cos_a
        return safe_remap(frame, map_x, map_y)

    # =========================================================================
    # 🌊 15. 3D Wackelpudding (Wobble-Welle)
    # =========================================================================
    elif filter_name == "wave":
        wobble = np.sin(dy * 7.0 + frame_idx * 0.15) * (rx * 0.22) * inside_mask
        map_x = x_grid + wobble
        return safe_remap(frame, map_x, y_grid)

    # =========================================================================
    # 🪞 16. Doppel-Links (Alien-Symmetrie)
    # =========================================================================
    elif filter_name == "mirror_left":
        map_x = np.where((x_grid > cx) & (inside_mask > 0.2), cx - (x_grid - cx), x_grid)
        return safe_remap(frame, map_x, y_grid)

    # =========================================================================
    # 🪞 17. Doppel-Rechts (Alien-Symmetrie)
    # =========================================================================
    elif filter_name == "mirror_right":
        map_x = np.where((x_grid < cx) & (inside_mask > 0.2), cx + (cx - x_grid), x_grid)
        return safe_remap(frame, map_x, y_grid)

    # =========================================================================
    # 📏 18. Bleistift-Kopf (Langgezogen)
    # =========================================================================
    elif filter_name == "stretch_vert":
        src_x = cx + (x_grid - cx) * 1.85
        map_x = x_grid * (1.0 - inside_mask) + src_x * inside_mask
        return safe_remap(frame, map_x, y_grid)

    # =========================================================================
    # 🗜️ 19. Wide Meme (Pfannkuchen-Kopf)
    # =========================================================================
    elif filter_name == "squish_wide":
        src_x = cx + (x_grid - cx) * 0.55
        src_y = cy + (y_grid - cy) * 1.55
        map_x = x_grid * (1.0 - inside_mask) + src_x * inside_mask
        map_y = y_grid * (1.0 - inside_mask) + src_y * inside_mask
        return safe_remap(frame, map_x, map_y)

    return frame

def process_cam_video_3d(
    raw_video_path: Path,
    cam_crop: dict[str, Any],
    filter_name: str,
    output_path: Path,
    on_progress=None,
) -> Path | None:
    """Schneidet das Cam-Fenster aus dem Rohvideo, wendet den 3D-Filter an und piped direkt in ffmpeg."""
    if not filter_name or filter_name == "none":
        return None

    cap = cv2.VideoCapture(str(raw_video_path))
    if not cap.isOpened():
        return None

    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    # Cam-Koordinaten berechnen
    if "x_pct" in cam_crop:
        cw = int(cam_crop["w_pct"] * vw)
        ch = int(cam_crop["h_pct"] * vh)
        cx = int(cam_crop["x_pct"] * vw)
        cy = int(cam_crop["y_pct"] * vh)
    else:
        cw = int(cam_crop.get("w", 540))
        ch = int(cam_crop.get("h", 360))
        cx = int(cam_crop.get("x", vw - cw))
        cy = int(cam_crop.get("y", vh - ch))

    cw = max(32, min(cw, vw))
    ch = max(32, min(ch, vh))
    cx = max(0, min(cx, vw - cw))
    cy = max(0, min(cy, vh - ch))

    cw -= cw % 2
    ch -= ch % 2
    cx -= cx % 2
    cy -= cy % 2

    detector = get_face_detector(cw, ch)
    tracker_state: dict[str, Any] = {}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{cw}x{ch}",
        "-r",
        f"{fps:.6f}",
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "16",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output_path),
    ]
    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            cam_frame = frame[cy : cy + ch, cx : cx + cw]
            if cam_frame.shape[0] != ch or cam_frame.shape[1] != cw:
                cam_frame = cv2.resize(cam_frame, (cw, ch))

            filtered = filter_cam_frame_3d(
                cam_frame, filter_name, tracker_state, detector, frame_idx
            )
            if proc.stdin is not None:
                proc.stdin.write(np.ascontiguousarray(filtered).tobytes())

            frame_idx += 1
            if on_progress and frame_idx % 30 == 0:
                pct = int((frame_idx / max(1, total_frames)) * 40)
                on_progress(
                    pct,
                    None,
                    f"3D-Filter '{filter_name}' ({frame_idx}/{total_frames} Frames)...",
                )
    except BrokenPipeError:
        logger.warning("FFmpeg-Pipe beim 3D-Cam-Filter unerwartet geschlossen.")
    finally:
        cap.release()
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        stderr_bytes = b""
        if proc.stderr is not None:
            try:
                stderr_bytes = proc.stderr.read()
            except OSError:
                pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            logger.warning("FFmpeg 3D-Cam-Prozess nach Timeout beendet.")

    if proc.returncode != 0:
        err_msg = stderr_bytes.decode("utf-8", errors="replace")[-300:]
        logger.warning("FFmpeg 3D-Cam-Filter fehlgeschlagen (rc=%s): %s", proc.returncode, err_msg)
        return None

    return output_path if output_path.exists() else None
