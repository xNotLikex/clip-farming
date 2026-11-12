import json
import os
import cv2
import numpy as np
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Callable
from src.config import (
    SHORTS_OUTPUT_DIR,
    RAW_CLIPS_DIR,
    METADATA_OUTPUT_DIR,
    DATA_DIR,
    load_config,
    get_streamers,
    PRESET_CORNER_CROPS
)
from src.video.sticker import create_tiktok_sticker
from src.video.gpu import get_best_video_encoder

# Globaler Registry-Lock fuer aktive Render-Jobs
active_renders: Dict[str, Dict[str, Any]] = {}
render_lock = threading.Lock()

def cancel_active_render(clip_id: str) -> bool:
    """Bricht ein aktuell laufendes Rendering fuer clip_id sofort ab und wartet auf Handle-Freigabe."""
    proc = None
    with render_lock:
        if clip_id in active_renders:
            job = active_renders[clip_id]
            job["cancelled"] = True
            candidate = job.get("proc")
            if candidate and candidate.poll() is None:
                proc = candidate

    if proc is None:
        return False

    try:
        proc.kill()
        proc.wait(timeout=5)
        print(f"[*] Vorheriges Rendering fuer {clip_id} wurde sofort abgebrochen!")
        return True
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[!] Fehler beim Abbruch von {clip_id}: {e}")
        return False

def escape_ffmpeg_filter_path(path: Path | str) -> str:
    """Escaped einen Dateipfad sicher für FFmpeg-Filtergraph-Parameter in einfachen Anführungszeichen."""
    normalized = str(path).replace("\\", "/")
    # In FFmpeg filter_complex ('...'): ':' muss escaped werden und "'" beendet sonst das Literal.
    return normalized.replace(":", "\\:").replace("'", "'\\''")


def _even(n: int) -> int:
    """Rundet eine Pixelzahl auf die nächste gerade Zahl ab (erforderlich für yuv420p)."""
    return n - (n % 2)


def _resolve_rect(
    data: dict[str, Any],
    vw: int,
    vh: int,
    default_w: int,
    default_h: int,
    default_x: int,
    default_y: int,
    *,
    even_xy: bool = True,
) -> tuple[int, int, int, int]:
    """Normalisiert Prozent- oder Pixel-Rechtecke auf geclampte, gerade FFmpeg-Koordinaten."""
    if "x_pct" in data:
        rw = int(data["w_pct"] * vw)
        rh = int(data["h_pct"] * vh)
        rx = int(data["x_pct"] * vw)
        ry = int(data["y_pct"] * vh)
    else:
        rw = int(data.get("w", default_w))
        rh = int(data.get("h", default_h))
        rx = int(data.get("x", default_x))
        ry = int(data.get("y", default_y))

    rw = _even(max(32, min(rw, vw)))
    rh = _even(max(32, min(rh, vh)))
    rx = max(0, min(rx, vw - rw))
    ry = max(0, min(ry, vh - rh))
    if even_xy:
        rx = _even(rx)
        ry = _even(ry)
    return rx, ry, rw, rh


def _build_cam_stream(
    cx: int,
    cy: int,
    cw: int,
    ch: int,
    inputs: list[str],
    cam_3d_path: Path | None = None,
    *,
    crop_preserve_aspect: bool = True,
) -> str:
    """Erzeugt den FFmpeg-Filter-Teilstring für den Facecam-Stream (mit oder ohne 3D-Temp-Video)."""
    if cam_3d_path is not None:
        cam_inp_idx = len(inputs) // 2
        inputs.extend(["-i", str(cam_3d_path)])
        return f"[{cam_inp_idx}:v]scale=1080:720:force_original_aspect_ratio=increase,crop=1080:720[cam]"
    if crop_preserve_aspect:
        return f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1080:720:force_original_aspect_ratio=increase,crop=1080:720[cam]"
    return f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1080:720[cam]"


def compute_cam_crop_for_layout(
    vw: int,
    vh: int,
    layout_mode: str = "auto",
    custom_crops: dict[str, Any] | None = None,
    face_box: tuple[int, int, int, int] | None = None,
) -> dict[str, int] | None:
    """Berechnet die Cam-Crop-Koordinaten (x, y, w, h) falls ein Cam-Split aktiv ist."""
    is_single_916 = (layout_mode == "single_916") or bool(
        custom_crops and custom_crops.get("mode") == "single_916"
    )
    if is_single_916:
        return None

    if custom_crops and custom_crops.get("enabled", True):
        cam_data = custom_crops.get("cam", {})
        has_cam = cam_data.get("enabled", True) and (
            cam_data.get("w", 0) > 20 or cam_data.get("w_pct", 0) > 0.05
        )
        if not has_cam:
            return None
        cx, cy, cw, ch = _resolve_rect(cam_data, vw, vh, 480, 360, vw - 480, vh - 360)
        return {"x": cx, "y": cy, "w": cw, "h": ch}

    if face_box:
        fx, fy, fw, fh = face_box
        cam_crop_w = max(int(fw * 2.2), 340)
        cam_crop_h = int(cam_crop_w * (720 / 1080))
        cam_crop_x = max(0, fx - int(fw * 0.6))
        cam_crop_y = max(0, fy - int(fh * 0.4))
        return {"x": cam_crop_x, "y": cam_crop_y, "w": cam_crop_w, "h": cam_crop_h}

    return None


def build_filter_graph(
    raw_video_path: Path,
    video_info: dict[str, Any],
    layout_mode: str = "auto",
    custom_crops: dict[str, Any] | None = None,
    face_box: tuple[int, int, int, int] | None = None,
    cam_3d_path: Path | None = None,
    sticker_path: Path | None = None,
    ass_subtitle_path: Path | None = None,
) -> tuple[str, list[str], int]:
    """Reine Funktion: baut FFmpeg filter_complex, Inputs-Liste und sticker_y deterministisch auf."""
    vw = int(video_info.get("width") or 1920)
    vh = int(video_info.get("height") or 1080)
    inputs: list[str] = ["-i", str(raw_video_path)]
    is_single_916 = (layout_mode == "single_916") or bool(
        custom_crops and custom_crops.get("mode") == "single_916"
    )

    if is_single_916:
        single_data: dict[str, Any] = {}
        if custom_crops:
            single_data = (
                custom_crops.get("single")
                or custom_crops.get("single_916")
                or custom_crops.get("game")
                or {}
            )
        ideal_w = _even(int(vh * (9.0 / 16.0)))
        if "x_pct" in single_data:
            sx = int(single_data["x_pct"] * vw)
        elif "x" in single_data:
            sx = int(single_data["x"])
        else:
            sx = (vw - ideal_w) // 2

        sw = ideal_w
        sh = _even(vh)
        sx = _even(max(0, min(sx, vw - sw)))
        base_graph = f"[0:v]crop={sw}:{sh}:{sx}:0,scale=1080:1920[base]"
        sticker_y = 480

    elif custom_crops and custom_crops.get("enabled", True):
        cam_data = custom_crops.get("cam", {})
        game_data = custom_crops.get("game", {})
        has_cam = cam_data.get("enabled", True) and (
            cam_data.get("w", 0) > 20 or cam_data.get("w_pct", 0) > 0.05
        )

        if has_cam:
            cx, cy, cw, ch = _resolve_rect(cam_data, vw, vh, 480, 360, vw - 480, vh - 360)
            if "x_pct" in game_data or ("w" in game_data and game_data.get("w", 0) > 20):
                gw_def = int(game_data.get("w", 972))
                gx, gy, gw, gh = _resolve_rect(
                    game_data, vw, vh, 972, 1080, (vw - gw_def) // 2, 0
                )
                game_filter = (
                    f"[0:v]crop={gw}:{gh}:{gx}:{gy},"
                    f"scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
                )
            else:
                game_filter = (
                    "[0:v]scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
                )

            cam_stream = _build_cam_stream(
                cx, cy, cw, ch, inputs, cam_3d_path=cam_3d_path, crop_preserve_aspect=True
            )
            base_graph = f"{cam_stream};{game_filter}[cam][game]vstack=inputs=2[base]"
            sticker_y = 620
        else:
            if "x_pct" in game_data or ("w" in game_data and game_data.get("w", 0) > 20):
                gx, gy, gw, gh = _resolve_rect(
                    game_data, vw, vh, vw, vh, 0, 0, even_xy=False
                )
                base_graph = (
                    f"[0:v]crop={gw}:{gh}:{gx}:{gy},"
                    f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base]"
                )
            else:
                base_graph = (
                    "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                    "boxblur=6:2,scale=1080:1920[bg];"
                    "[0:v]scale=1080:608[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
                )
            sticker_y = 520
    else:
        if face_box:
            fx, fy, fw, fh = face_box
            cam_crop_w = max(int(fw * 2.2), 340)
            cam_crop_h = int(cam_crop_w * (720 / 1080))
            cam_crop_x = max(0, fx - int(fw * 0.6))
            cam_crop_y = max(0, fy - int(fh * 0.4))
            cam_stream = _build_cam_stream(
                cam_crop_x,
                cam_crop_y,
                cam_crop_w,
                cam_crop_h,
                inputs,
                cam_3d_path=cam_3d_path,
                crop_preserve_aspect=False,
            )
            base_graph = (
                f"{cam_stream};"
                "[0:v]scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
                "[cam][game]vstack=inputs=2[base]"
            )
            sticker_y = 620
        else:
            base_graph = (
                "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                "boxblur=6:2,scale=1080:1920[bg];"
                "[0:v]scale=1080:608[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
            )
            sticker_y = 520

    sticker_filter = ""
    if sticker_path is not None:
        sticker_idx = len(inputs) // 2
        inputs.extend(["-i", str(sticker_path)])
        sticker_filter = f";[base][{sticker_idx}:v]overlay=(W-w)/2:{sticker_y}[with_sticker]"
        curr_target = "[with_sticker]"
    else:
        curr_target = "[base]"

    if ass_subtitle_path is not None:
        clean_sub_path = escape_ffmpeg_filter_path(ass_subtitle_path)
        filter_complex = f"{base_graph}{sticker_filter};{curr_target}subtitles='{clean_sub_path}'[v]"
    else:
        filter_complex = f"{base_graph}{sticker_filter};{curr_target}copy[v]"

    return filter_complex, inputs, sticker_y


def _parse_fps(rate_str: str) -> float:
    """Parst ffprobe r_frame_rate/avg_frame_rate (z.B. '60/1' oder '30000/1001')."""
    if not rate_str or rate_str == "0/0":
        return 30.0
    if "/" in rate_str:
        num_s, den_s = rate_str.split("/", 1)
        try:
            den = float(den_s)
            return float(num_s) / den if den > 0 else 30.0
        except ValueError:
            return 30.0
    try:
        return float(rate_str)
    except ValueError:
        return 30.0


def probe_video(video_path: Path) -> dict[str, Any]:
    """Liest Dauer, Auflösung, FPS und Audio-Existenz in einem einzigen ffprobe-Aufruf."""
    defaults: dict[str, Any] = {
        "duration": 30.0,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "has_audio": True,
    }
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10)
        data = json.loads(out)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return defaults

    fmt = data.get("format") or {}
    try:
        dur = float(fmt.get("duration") or 0)
        if dur > 0:
            defaults["duration"] = dur
    except (TypeError, ValueError):
        pass

    streams = data.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream:
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        if width > 0 and height > 0:
            defaults["width"] = width
            defaults["height"] = height
        if defaults["duration"] == 30.0:
            try:
                sdur = float(video_stream.get("duration") or 0)
                if sdur > 0:
                    defaults["duration"] = sdur
            except (TypeError, ValueError):
                pass
        defaults["fps"] = _parse_fps(
            video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or ""
        )

    defaults["has_audio"] = any(s.get("codec_type") == "audio" for s in streams)
    return defaults


def get_video_duration(video_path: Path) -> float:
    """Ermittelt die exakte Laenge des Videos in Sekunden via ffprobe."""
    return probe_video(video_path)["duration"]

def generate_thumbnail(clip_id: str, force: bool = False) -> Optional[Path]:
    """
    Erzeugt ein 9:16 JPEG-Vorschaubild aus dem fertigen Short (oder Rohclip als Fallback).
    Mit force=True wird ein bestehendes Vorschaubild stets ueberschrieben.
    """
    thumb_dir = DATA_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{clip_id}.jpg"

    if thumb_path.exists() and not force:
        return thumb_path

    video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if not video_path.exists():
        video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"

    if not video_path.exists():
        return None

    try:
        # Extrahiere Frame bei 1.0s (wo Bild, Hook-Sticker & Untertitel sichtbar sind)
        subprocess.run([
            "ffmpeg", "-y", "-ss", "00:00:01.000", "-i", str(video_path),
            "-frames:v", "1", "-update", "1", "-q:v", "2", str(thumb_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
    except Exception:
        pass

    if not thumb_path.exists() or thumb_path.stat().st_size == 0:
        try:
            # Fallback bei ultrakurzen Videos auf 0.2s
            subprocess.run([
                "ffmpeg", "-y", "-ss", "00:00:00.200", "-i", str(video_path),
                "-frames:v", "1", "-update", "1", "-q:v", "2", str(thumb_path)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
        except Exception:
            pass

    if not thumb_path.exists() or thumb_path.stat().st_size == 0:
        try:
            cap = cv2.VideoCapture(str(video_path))
            cap.set(cv2.CAP_PROP_POS_MSEC, 500)
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                ret, frame = cap.read()
            if ret and frame is not None:
                cv2.imwrite(str(thumb_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            cap.release()
        except Exception:
            pass

    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        return thumb_path
    return None

class VideoComposer:
    def __init__(self):
        self.config = load_config()
        self.video_cfg = self.config.get("video", {})
        self.use_nvenc = self.video_cfg.get("use_nvenc", True)
        self.hardware_encoder = self.video_cfg.get("hardware_encoder", "auto")
        if not self.use_nvenc and self.hardware_encoder == "auto":
            self.hardware_encoder = "cpu"
        self.encoder_profile = get_best_video_encoder(self.hardware_encoder)
        self.audio_normalize = self.video_cfg.get("audio_normalize", True)

    def detect_facecam_overlay(self, video_path: Path, max_samples: int = 18) -> Optional[Tuple[int, int, int, int]]:
        """
        Intelligente, ultra-schnelle Facecam-Erkennung (< 0.5s):
        Downscaled Frames fuer Haar-Cascade und misst raeumliche Stabilitaet.
        """
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        cap = cv2.VideoCapture(str(video_path))
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return None

        step = max(1, total_frames // max_samples)
        
        frame_faces = []
        crowd_frames = 0
        sampled_count = 0

        for f_idx in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            sampled_count += 1

            # Ultra-schnelles Downscaling auf 480px Breite für sofortige Erkennung
            h, w = frame.shape[:2]
            scale = 480.0 / max(1, w)
            target_h = int(h * scale)
            small = cv2.resize(frame, (480, target_h), interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(25, 25))
            
            if len(faces) > 3:
                crowd_frames += 1
            elif len(faces) > 0:
                for (fx, fy, fw, fh) in faces:
                    # Zurückskalieren auf Originalauflösung
                    frame_faces.append((
                        int(fx / scale),
                        int(fy / scale),
                        int(fw / scale),
                        int(fh / scale)
                    ))

        cap.release()

        # 1. Wenn viele Crowd-Frames erkannt wurden -> Eindeutig IRL / Gamescom / Event!
        if crowd_frames > 2:
            return None

        # 2. Zu wenige Gesichter für eine permanente Facecam
        if len(frame_faces) < (sampled_count * 0.3):
            return None

        # 3. Positions-Stabilität (Varianz) prüfen
        xs = [f[0] for f in frame_faces]
        ys = [f[1] for f in frame_faces]
        std_x = np.std(xs)
        std_y = np.std(ys)

        # Wenn die Kamera wackelt / handheld ist (std > 48px) -> Kein Webcam Overlay!
        if std_x > 48 or std_y > 48:
            return None

        avg_x = int(np.mean(xs))
        avg_y = int(np.mean(ys))
        avg_w = int(np.mean([f[2] for f in frame_faces]))
        avg_h = int(np.mean([f[3] for f in frame_faces]))

        return (avg_x, avg_y, avg_w, avg_h)

    def render_short(
        self,
        raw_video_path: Path,
        clip_id: str,
        ass_subtitle_path: Optional[Path] = None,
        header_sticker_text: Optional[str] = None,
        streamer_name: str = "",
        layout_mode: str = "auto",
        custom_crops: Optional[Dict[str, Any]] = None,
        cam_filter: str = "none",
        on_progress: Optional[Callable[[int, Optional[int], Optional[str]], None]] = None
    ) -> Optional[Path]:
        """
        Rendert das Video ins 9:16 Format.
        Unterstützt automatisches KI-Layout, Split-Cam, Blur-Stack und benutzerdefinierte Zuschnitt-Rahmen.
        Bricht vorheriges Rendering für denselben Clip ab, falls noch aktiv.
        Liefert prozentualen Fortschritt und Restdauer in Echtzeit.
        """
        # 0. Vorheriges Rendering für den gleichen Clip abbrechen, falls noch aktiv!
        cancel_active_render(clip_id)

        output_file = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
        temp_output_file = SHORTS_OUTPUT_DIR / f"tmp_short_{clip_id}.mp4"
        video_info = probe_video(raw_video_path)
        total_duration = video_info["duration"]
        vw = video_info["width"]
        vh = video_info["height"]
        face_box = None
        
        # 0.1 Falls custom_crops nicht direkt uebergeben wurde, aus Metadata oder Streamer-Config laden
        if custom_crops is None:
            meta_f = METADATA_OUTPUT_DIR / f"{clip_id}.json"
            if meta_f.exists():
                try:
                    with open(meta_f, "r", encoding="utf-8") as mf:
                        m = json.load(mf)
                        if layout_mode in ("custom", "single_916") or m.get("layout_mode") in ("custom", "single_916"):
                            custom_crops = m.get("custom_crops")
                        if not custom_crops and m.get("layout_mode") in PRESET_CORNER_CROPS:
                            custom_crops = PRESET_CORNER_CROPS[m.get("layout_mode")]
                except Exception:
                    pass

            # Falls immer noch None: Prüfe ob für den Streamer ein vorkonfiguriertes Layout existiert
            if custom_crops is None and streamer_name:
                try:
                    for s in get_streamers():
                        if s.get("name", "").lower() == streamer_name.lower():
                            st_layout = s.get("layout", "auto")
                            if st_layout in PRESET_CORNER_CROPS:
                                custom_crops = PRESET_CORNER_CROPS[st_layout]
                                layout_mode = "custom"
                            elif s.get("custom_crops"):
                                custom_crops = s.get("custom_crops")
                                if layout_mode == "auto":
                                    layout_mode = st_layout or "custom"
                            elif layout_mode == "auto" and st_layout != "auto":
                                layout_mode = st_layout
                            break
                except Exception:
                    pass

        if layout_mode in PRESET_CORNER_CROPS and not custom_crops:
            custom_crops = PRESET_CORNER_CROPS[layout_mode]

        # Prüfen ob Reines 9:16 Vollbild (IRL / Einzelfokus ohne Cam-Split)
        is_single_916 = (layout_mode == "single_916") or (custom_crops and custom_crops.get("mode") == "single_916")

        # Inputs & Filter initialisieren
        temp_cam_file = None

        if not cam_filter or cam_filter == "none":
            meta_f = METADATA_OUTPUT_DIR / f"{clip_id}.json"
            if meta_f.exists():
                try:
                    with open(meta_f, encoding="utf-8") as mf:
                        m = json.load(mf)
                        cam_filter = m.get("cam_filter", "none")
                except (OSError, json.JSONDecodeError):
                    pass
            if custom_crops and "cam_filter" in custom_crops:
                cam_filter = custom_crops.get("cam_filter", "none")

        if not is_single_916 and not (custom_crops and custom_crops.get("enabled", True)):
            if layout_mode == "split_cam_top":
                face_box = self.detect_facecam_overlay(raw_video_path) or (0, 0, 320, 240)
            elif layout_mode == "auto":
                face_box = self.detect_facecam_overlay(raw_video_path)

        cam_crop_dict = compute_cam_crop_for_layout(
            vw, vh, layout_mode=layout_mode, custom_crops=custom_crops, face_box=face_box
        )
        if cam_crop_dict and cam_filter and cam_filter != "none":
            try:
                from src.video.filters import process_cam_video_3d

                candidate_cam_file = RAW_CLIPS_DIR / f"temp_3d_{clip_id}.mp4"
                print(
                    f"[*] Starte anatomischen 3D-Gesichtsfilter '{cam_filter}' "
                    f"({cam_crop_dict['w']}x{cam_crop_dict['h']})..."
                )
                res_p = process_cam_video_3d(
                    raw_video_path, cam_crop_dict, cam_filter, candidate_cam_file, on_progress
                )
                if res_p and res_p.exists():
                    temp_cam_file = res_p
            except Exception as e:
                print(f"[!] Fehler bei 3D-Gesichtsfilter: {e}")
                temp_cam_file = None

        # 2. Sticker Badge erzeugen (falls Text vorhanden)
        sticker_png = None
        if header_sticker_text and header_sticker_text.strip():
            sticker_png = raw_video_path.parent / f"sticker_{clip_id}.png"
            create_tiktok_sticker(header_sticker_text.strip(), sticker_png)

        # 3. Filtergraph deterministisch aufbauen
        active_sub_path = (
            ass_subtitle_path if (ass_subtitle_path and ass_subtitle_path.exists()) else None
        )
        filter_complex, inputs, _sticker_y = build_filter_graph(
            raw_video_path=raw_video_path,
            video_info=video_info,
            layout_mode=layout_mode,
            custom_crops=custom_crops,
            face_box=face_box,
            cam_3d_path=temp_cam_file,
            sticker_path=sticker_png,
            ass_subtitle_path=active_sub_path,
        )

        # Phase 5: Erweiterter 2-Pass/Broadcast-Audio-Booster (Dynamische Kompression + EBU R128 Loudness)
        audio_filter = "acompressor=threshold=-18dB:ratio=3:attack=5:release=50,loudnorm=I=-14:TP=-1.5:LRA=11" if self.audio_normalize else "anull"
        encoder_args = self.encoder_profile["args"]
        codec = self.encoder_profile["codec"]
        speed_factor = 2.5 if "nvenc" in codec else (2.0 if ("amf" in codec or "mf" in codec or "qsv" in codec) else 0.9)

        cmd = [
            "ffmpeg", "-y",
            "-progress", "pipe:1",
            "-nostats",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:a", "aac", "-b:a", "192k",
            "-af", audio_filter,
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(temp_output_file)
        ]

        try:
            layout_desc = "Reines 9:16 Vollbild (IRL)" if is_single_916 else ("Benutzerdefinierte Rahmen" if custom_crops else ("Split-Cam" if face_box else "Blur-Stack IRL"))
            print(f"[*] Rendere Short fuer Clip {clip_id} ({layout_desc}) mit {self.encoder_profile['name']}...")
            if on_progress:
                on_progress(5, int(total_duration / speed_factor), self.encoder_profile["name"])

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Hintergrund-Thread zum kontinuierlichen Leeren von stderr (verhindert Pipe-Deadlock!)
            stderr_lines = []
            def drain_stderr():
                try:
                    for s_line in proc.stderr:
                        stderr_lines.append(s_line)
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()

            with render_lock:
                active_renders[clip_id] = {"proc": proc, "cancelled": False}

            current_sec = 0.0
            # M7 Audit-Fix: Verwende den oben präzise ermittelten speed_factor statt hartem Überschreiben

            for line in proc.stdout:
                with render_lock:
                    if active_renders.get(clip_id, {}).get("cancelled", False):
                        proc.kill()
                        break

                line = line.strip()
                if not line:
                    continue

                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=")[1])
                        current_sec = us / 1_000_000.0
                        pct = min(99, max(5, int((current_sec / max(1.0, total_duration)) * 100)))
                        rem_sec = max(0.0, total_duration - current_sec)
                        eta = max(0, int(rem_sec / max(0.5, speed_factor)))
                        if on_progress:
                            on_progress(pct, eta, f"{speed_factor:.1f}x")
                    except Exception:
                        pass
                elif line.startswith("speed="):
                    try:
                        speed_str = line.split("=")[1].replace("x", "").strip()
                        speed_factor = float(speed_str)
                    except Exception:
                        pass
                elif line == "progress=end":
                    if on_progress:
                        on_progress(100, 0, f"{speed_factor:.1f}x")

            proc.wait()
            try:
                stderr_thread.join(timeout=1.0)
            except Exception:
                pass
            stderr_out = "".join(stderr_lines)

            with render_lock:
                was_cancelled = active_renders.get(clip_id, {}).get("cancelled", False)
                if clip_id in active_renders:
                    del active_renders[clip_id]

            if was_cancelled:
                for p in (temp_output_file, sticker_png, temp_cam_file):
                    if p and p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                print(f"[*] Rendering fuer {clip_id} wurde vorzeitig abgebrochen.")
                return None

            # Aufräumen des temporären PNGs und 3D Cam MP4s
            if sticker_png and sticker_png.exists():
                try:
                    sticker_png.unlink()
                except Exception:
                    pass

            if temp_cam_file and temp_cam_file.exists():
                try:
                    temp_cam_file.unlink()
                except Exception:
                    pass

            if temp_output_file.exists() and temp_output_file.stat().st_size > 1000:
                replaced = False
                for _ in range(8):
                    try:
                        os.replace(str(temp_output_file), str(output_file))
                        replaced = True
                        break
                    except PermissionError:
                        time.sleep(0.15)
                if not replaced:
                    os.replace(str(temp_output_file), str(output_file))
                print(f"[+] 9:16 Short fertiggestellt: {output_file.name}")
                try:
                    generate_thumbnail(clip_id, force=True)
                    print(f"[+] Vorschaubild fuer {clip_id} erfolgreich neu generiert.")
                except Exception as th_err:
                    print(f"[!] Fehler beim Aktualisieren des Vorschaubilds fuer {clip_id}: {th_err}")
                if on_progress:
                    on_progress(100, 0, f"{speed_factor:.1f}x")
                return output_file
            else:
                if temp_output_file.exists():
                    try:
                        temp_output_file.unlink()
                    except Exception:
                        pass
                print(f"[!] FFmpeg Fehler: {stderr_out[-500:] if stderr_out else 'Unbekannt'}")
        except Exception as e:
            print(f"[!] Exception beim Rendern: {e}")
            with render_lock:
                if clip_id in active_renders:
                    del active_renders[clip_id]

        return None
