import json
import logging
import os
import sys
import time
import html
import shutil
import subprocess
import threading
import cv2
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, url_for, Response

from src.config import (
    PROJECT_ROOT, SHORTS_OUTPUT_DIR, RAW_CLIPS_DIR, METADATA_OUTPUT_DIR, DATA_DIR, load_config,
    get_streamers, get_streamers_with_avatars, add_streamer, remove_streamer, update_streamer, update_all_streamers_min_views,
    get_autopilot_settings, save_autopilot_settings
)
from src.database import get_db_connection, init_db, update_clip_status
from src.logging_config import setup_logging
from src.video.layout import VideoComposer, cancel_active_render, generate_thumbnail
from src.video.filters import AVAILABLE_CAM_FILTERS
from src.state import status_manager
from src.version import APP_VERSION, GITHUB_REPO
from src.updater import check_for_updates, download_and_run_installer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger(__name__)
app = Flask(__name__)
@app.after_request
def add_cors_and_security_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Range, Authorization"
    response.headers["Access-Control-Expose-Headers"] = "Content-Range, Content-Length, Accept-Ranges"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Accept-Ranges"] = "bytes"
    ctype = (response.content_type or "").lower()
    if any(t in ctype for t in ("text/html", "application/javascript", "application/json")):
        response.headers.setdefault("Cache-Control", "no-cache, no-store, must-revalidate")
        response.headers.setdefault("Pragma", "no-cache")
        response.headers.setdefault("Expires", "0")
    return response


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Range, Authorization"
        return response

# Zweiter CORS-Handler entfernt (C3 Audit-Fix: überschrieb Range-Header aus dem ersten Handler)

composer = VideoComposer()

def format_relative_time(iso_str: str) -> tuple[str, str]:
    """Wandelt einen ISO-8601-Zeitstempel in eine benutzerfreundliche relative Zeitangabe auf Deutsch um."""
    if not iso_str:
        return ("Unbekannt", "")
    try:
        clean_str = str(iso_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        local_dt = dt.astimezone()
        local_now = now.astimezone()
        
        time_str = local_dt.strftime("%H:%M")
        date_str = local_dt.strftime("%d.%m.")
        full_date_str = local_dt.strftime("%d.%m.%Y, %H:%M Uhr")
        
        days_diff = (local_now.date() - local_dt.date()).days
        total_seconds = int((now - dt).total_seconds())
        
        if days_diff == 0:
            if total_seconds < 60:
                rel = "Gerade eben"
            elif total_seconds < 3600:
                mins = max(1, total_seconds // 60)
                rel = f"Vor {mins} Min."
            else:
                hours = max(1, total_seconds // 3600)
                rel = f"Heute, vor {hours} Std."
        elif days_diff == 1:
            rel = f"Gestern ({time_str} Uhr)"
        elif days_diff < 7:
            rel = f"Vor {days_diff} Tagen ({date_str})"
        elif days_diff < 30:
            weeks = days_diff // 7
            rel = f"Vor {weeks} Wochen ({date_str})" if weeks > 1 else f"Vor 1 Woche ({date_str})"
        else:
            rel = local_dt.strftime("%d.%m.%Y")
            
        return rel, full_date_str
    except Exception:
        return str(iso_str), str(iso_str)

def process_single_clip(clip_id: str, sub_position: str = "bottom", sticker_text_override: str = None) -> bool:
    """Schneidet einen Rohclip aus der Warteschlange und verschiebt ihn ins Studio."""
    # Falls bereits ein Rendering fuer diesen Clip aktiv war: sofort abbrechen!
    cancel_active_render(clip_id)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()
        if not clip:
            return False

    streamer = clip["streamer"]
    orig_title = clip["original_title"] or "Clip"
    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
    txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
    words_path = RAW_CLIPS_DIR / f"{clip_id}_words.json"

    # Falls Rohdatei noch nicht da ist, laden
    if not raw_path.exists() or raw_path.stat().st_size < 1000:
        from src.harvesters.twitch_clips import TwitchClipHarvester
        h = TwitchClipHarvester()
        h.download_clip(clip["url"], clip_id)

    try:
        from src.video.transcriber import VideoTranscriber
        from src.video.subtitles import SubtitleGenerator
        from src.meta.generator import MetadataGenerator

        transcriber = VideoTranscriber()
        sub_gen = SubtitleGenerator()
        meta_gen = MetadataGenerator()

        # 1. Transkription (GPU Whisper)
        status_manager.set_task("transcribing", "Transkribiere Audio (KI Whisper)...", clip_title=orig_title, streamer=streamer)
        status_manager.set_progress(percent=15, eta_seconds=5, speed="CUDA", phase="whisper", clip_id=clip_id)

        segments = transcriber.transcribe(raw_path)
        full_transcript = transcriber.get_full_transcript(segments)

        # Lokal als lesbaren Text und JSON speichern
        txt_path.write_text(full_transcript, encoding="utf-8")
        with open(words_path, "w", encoding="utf-8") as wf:
            json.dump(segments, wf, indent=2, ensure_ascii=False)

        # 2. Karaoke Untertitel mit gewählter Position
        active_sub_path = None
        if sub_position != "none":
            status_manager.set_task("subtitles", f"Generiere animierte Untertitel ({sub_position})...", clip_title=orig_title, streamer=streamer)
            status_manager.set_progress(percent=25, eta_seconds=3, phase="subtitles", clip_id=clip_id)
            sub_gen.generate_ass(segments, ass_path, position=sub_position)
            active_sub_path = ass_path

        # 3. Metadaten & Sticker
        status_manager.set_task("metadata", "Erstelle Hook & Metadaten...", clip_title=orig_title, streamer=streamer)
        metadata = meta_gen.generate(original_title=orig_title, streamer=streamer, transcript=full_transcript)
        metadata["sub_position"] = sub_position
        if sticker_text_override:
            metadata["sticker_text"] = sticker_text_override
            metadata["title"] = sticker_text_override

        meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
        with open(meta_file, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, indent=2, ensure_ascii=False)

        # 4. 9:16 Rendern (NVENC GPU) mit Live-Fortschritt & ETA
        status_manager.set_task("rendering", "Rendere 9:16 Short (NVENC GPU)...", clip_title=orig_title, streamer=streamer)
        sticker_text = sticker_text_override or metadata.get("sticker_text") or metadata.get("title") or orig_title

        def on_render_progress(pct: int, eta: int, speed: str):
            # Prozentbereich 30% bis 100%
            scaled_pct = 30 + int(pct * 0.70)
            status_manager.set_progress(percent=scaled_pct, eta_seconds=eta, speed=speed, phase="rendering", clip_id=clip_id)

        # Streamer Vorkonfiguration abrufen
        streamers = get_streamers()
        st_cfg = next((s for s in streamers if s.get("name", "").lower() == streamer.lower()), {})
        st_layout = metadata.get("layout_mode") or st_cfg.get("layout", "auto")
        st_crops = metadata.get("custom_crops") or st_cfg.get("custom_crops")

        rendered_path = composer.render_short(
            raw_video_path=raw_path,
            clip_id=clip_id,
            ass_subtitle_path=active_sub_path,
            header_sticker_text=sticker_text,
            streamer_name=streamer,
            layout_mode=st_layout,
            custom_crops=st_crops,
            on_progress=on_render_progress
        )

        status_manager.reset_progress()

        if rendered_path and rendered_path.exists():
            try:
                generate_thumbnail(clip_id, force=True)
            except Exception:
                pass
            update_clip_status(clip_id, "ready", rendered_path=str(rendered_path), ai_title=metadata.get("title"))
            status_manager.set_task("idle", f"Clip '{orig_title}' fertig ins Studio übertragen.")
            return True
    except Exception as e:
        status_manager.reset_progress()
        status_manager.set_task("error", f"Fehler bei Clip {clip_id}: {e}")
        update_clip_status(clip_id, "failed", error_log=str(e))
    return False


from src.web.templates import HTML_DASHBOARD


@app.route("/app.js")
def serve_app_js():
    import os
    from flask import send_file, make_response
    ui_app_js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.js")
    resp = make_response(send_file(ui_app_js, mimetype="application/javascript"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

def get_dashboard_dict():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT status, COUNT(*) FROM clips GROUP BY status")
        raw_counts = dict(cursor.fetchall())
        counts = {
            "harvested": raw_counts.get("harvested", 0),
            "ready": raw_counts.get("ready", 0) + raw_counts.get("completed", 0),
            "scheduled": raw_counts.get("scheduled", 0),
            "published": raw_counts.get("published", 0)
        }

        # Ready Clips (Studio - sortiert nach Streamer)
        cursor.execute("SELECT * FROM clips WHERE status IN ('ready', 'completed') ORDER BY LOWER(streamer) ASC, rowid DESC")
        ready_rows = cursor.fetchall()

        # Queue Clips (nur harvested)
        cursor.execute("SELECT * FROM clips WHERE status = 'harvested' ORDER BY view_count DESC")
        raw_queue_rows = cursor.fetchall()
        queue_rows = []
        older_queue_count = 0
        today_local = datetime.now().date()
        for r in raw_queue_rows:
            r_dict = dict(r)
            created_ago, created_full = format_relative_time(r["clip_created_at"] or r["harvested_at"])
            r_dict["created_ago"] = created_ago
            r_dict["created_full"] = created_full
            queue_rows.append(r_dict)

            ts = r["clip_created_at"] or r["harvested_at"]
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
                    if dt.date() < today_local:
                        older_queue_count += 1
                except Exception:
                    older_queue_count += 1
            else:
                older_queue_count += 1

        # Scheduled Clips (Zeitplan)
        cursor.execute("SELECT * FROM clips WHERE status = 'scheduled' ORDER BY scheduled_publish_at ASC")
        scheduled_rows = [dict(r) for r in cursor.fetchall()]

        # Published Clips
        cursor.execute("SELECT * FROM clips WHERE status = 'published' ORDER BY rowid DESC")
        published_rows = [dict(r) for r in cursor.fetchall()]

    ready_clips = []
    for r in ready_rows:
        clip_id = r["clip_id"]
        meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
        sticker_text = ""
        title = r["ai_title"] or r["original_title"] or ""
        sub_position = "bottom"
        layout_mode = "auto"
        cam_filter = "none"
        is_manually_published = bool(r["is_manually_published"]) if "is_manually_published" in r.keys() and r["is_manually_published"] else False
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    mdata = json.load(mf)
                    sticker_text = mdata.get("sticker_text") or mdata.get("title") or ""
                    sub_position = mdata.get("sub_position", "bottom")
                    layout_mode = mdata.get("layout_mode", "auto")
                    cam_filter = mdata.get("cam_filter", "none")
                    if "is_manually_published" in mdata:
                        is_manually_published = bool(mdata["is_manually_published"])
                    if not title:
                        title = mdata.get("title", "")
            except Exception:
                pass

        if not sticker_text:
            sticker_text = r["original_title"] or ""

        txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
        transcript = ""
        if txt_path.exists():
            try:
                transcript = txt_path.read_text(encoding="utf-8")
            except Exception:
                pass

        short_file = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
        thumb_file = DATA_DIR / "thumbnails" / f"{clip_id}.jpg"
        short_mtime = short_file.stat().st_mtime if short_file.exists() else 0.0
        thumb_mtime = thumb_file.stat().st_mtime if thumb_file.exists() else 0.0
        latest_mtime = max(short_mtime, thumb_mtime)
        mtime = int(latest_mtime * 1000) if latest_mtime > 0 else int(time.time() * 1000)

        created_ago, created_full = format_relative_time(r["clip_created_at"] or r["harvested_at"])
        ready_clips.append({
            "clip_id": clip_id,
            "streamer": r["streamer"],
            "title": title,
            "sticker_text": sticker_text,
            "sub_position": sub_position,
            "transcript": transcript,
            "view_count": r["view_count"],
            "layout_mode": layout_mode,
            "cam_filter": cam_filter,
            "is_manually_published": is_manually_published,
            "has_video": short_file.exists(),
            "updated_at": mtime,
            "created_ago": created_ago,
            "created_full": created_full
        })

    streamer_counts = {}
    for c in ready_clips:
        st = c["streamer"]
        streamer_counts[st] = streamer_counts.get(st, 0) + 1

    all_streamers = get_streamers_with_avatars()
    cur_state = status_manager.get_state()
    initial_logs = cur_state.get("logs", [])
    current_status = cur_state.get("status", "idle")
    current_task = cur_state.get("current_task", "Bereit zur Ausführung")
    is_running = cur_state.get("is_running", False)

    return {
        "counts": counts,
        "ready_clips": ready_clips,
        "queue_clips": queue_rows,
        "older_queue_count": older_queue_count,
        "scheduled_clips": scheduled_rows,
        "published_clips": published_rows,
        "streamers": all_streamers,
        "streamer_counts": streamer_counts,
        "cam_filters": AVAILABLE_CAM_FILTERS,
        "initial_logs": initial_logs,
        "current_status": current_status,
        "current_task": current_task,
        "is_running": is_running,
        "app_version": APP_VERSION,
        "settings": get_autopilot_settings(),
    }

@app.route("/")
def index():
    d = get_dashboard_dict()
    return render_template_string(HTML_DASHBOARD, **d)

@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION, "repo": GITHUB_REPO})

@app.route("/api/check-update")
def api_check_update():
    return jsonify(check_for_updates())

@app.route("/api/apply-update", methods=["POST"])
def api_apply_update():
    data = request.get_json(silent=True) or {}
    url = data.get("download_url") or ""
    return jsonify(download_and_run_installer(url))

@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(get_dashboard_dict())

@app.route("/api/status")
def get_status():
    return jsonify(status_manager.get_state())

# H5 Audit-Fix: Atomarer Worker-Lock gegen Doppelklicks & Race-Conditions
_WORKER_LOCK = threading.Lock()

def execute_harvest_job() -> bool:
    """Startet das Suchen & Herunterladen auf Twitch im Hintergrund."""
    with _WORKER_LOCK:
        if status_manager.get_state().get("is_running", False):
            return False
        status_manager.set_task("harvesting", "Scanne Twitch-Streamer nach neuen Clips...")
        
    def run_harvest_background():
        try:
            from src.scheduler import PipelineOrchestrator
            orch = PipelineOrchestrator()
            streamers = orch.config.get("streamers", [])
            for s in streamers:
                if s.get("enabled", True):
                    status_manager.set_task("harvesting", "Scanne Twitch...", streamer=s.get("name"))
                    orch.harvester.harvest_channel(s)
        except Exception as e:
            status_manager.set_task("error", f"Fehler beim Clip-Scannen: {e}")
        finally:
            status_manager.set_task("idle", "Twitch-Scan beendet. Clips in der Warteschlange gespeichert.")
            try:
                settings = get_autopilot_settings()
                if settings.get("auto_render", False):
                    execute_process_all_job()
            except Exception:
                pass

    thread = threading.Thread(target=run_harvest_background, daemon=True)
    thread.start()
    return True

def execute_process_all_job() -> bool:
    """Schneidet alle Clips in der Warteschlange im Hintergrund."""
    with _WORKER_LOCK:
        if status_manager.get_state().get("is_running", False):
            return False
        status_manager.set_task("processing", "Starte Schneidevorgang für alle Clips...")
        
    def run_all_worker():
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT clip_id FROM clips WHERE status = 'harvested' ORDER BY view_count DESC")
                clips = cursor.fetchall()

            for idx, c in enumerate(clips, 1):
                status_manager.set_task("processing", f"Schneide Clip [{idx}/{len(clips)}]...")
                process_single_clip(c["clip_id"])
        except Exception as e:
            status_manager.set_task("error", f"Fehler beim Schneidevorgang: {e}")
        finally:
            status_manager.set_task("idle", f"Alle Clips fertig ins Studio übertragen.")

    thread = threading.Thread(target=run_all_worker, daemon=True)
    thread.start()
    return True

def cleanup_old_clips_housekeeping(max_age_days: int = 7):
    """Löscht nicht übernommene Roh-Clips, die älter als max_age_days Tage sind."""
    try:
        cutoff = datetime.now() - timedelta(days=max_age_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT clip_id FROM clips WHERE status = 'harvested' AND clip_created_at < ?",
                (cutoff_str,)
            )
            old_rows = cursor.fetchall()
            deleted_count = 0
            for r in old_rows:
                cid = r["clip_id"]
                raw_f = RAW_CLIPS_DIR / f"{cid}.mp4"
                if raw_f.exists():
                    try:
                        raw_f.unlink()
                    except OSError as exc:
                        logger.warning("Konnte alten Rohclip %s nicht löschen: %s", raw_f, exc)
                cursor.execute("UPDATE clips SET status = 'deleted' WHERE clip_id = ?", (cid,))
                deleted_count += 1
            if deleted_count > 0:
                conn.commit()
                status_manager.log(f"🧹 Housekeeping: {deleted_count} veraltete Roh-Clips (> {max_age_days} Tage) automatisch bereinigt.")
    except Exception as e:
        status_manager.log(f"Housekeeping-Fehler: {e}")

def autopilot_background_worker():
    """Prüft periodisch im Hintergrund nach neuen Clips gemäß konfiguriertem Intervall."""
    time.sleep(10)
    last_check_timestamp = time.time()
    last_housekeeping_timestamp = 0
    while True:
        try:
            time.sleep(15)
            # Housekeeping einmal alle 24 Stunden ausführen
            if time.time() - last_housekeeping_timestamp >= 86400:
                cleanup_old_clips_housekeeping(max_age_days=7)
                last_housekeeping_timestamp = time.time()

            settings = get_autopilot_settings()
            if not settings.get("enabled", True):
                continue
            
            interval_minutes = max(1, int(settings.get("interval_minutes", 30)))
            interval_seconds = interval_minutes * 60
            
            if time.time() - last_check_timestamp >= interval_seconds:
                if not status_manager.get_state().get("is_running", False):
                    last_check_timestamp = time.time()
                    status_manager.log(f"🤖 Autopilot: Starte zyklische Prüfung (alle {interval_minutes} Min)...")
                    execute_harvest_job()
        except Exception:
            logger.exception("Fehler im autopilot_background_worker")
            time.sleep(20)


_WORKERS_LOCK = threading.Lock()
_workers_started = False


def start_workers() -> list[threading.Thread]:
    """Startet die Hintergrund-Worker idempotent (nicht bereits beim Modul-Import)."""
    global _workers_started
    with _WORKERS_LOCK:
        if _workers_started:
            return []
        autopilot_thread = threading.Thread(
            target=autopilot_background_worker, name="autopilot_background_worker", daemon=True
        )
        autopilot_thread.start()
        _workers_started = True
        return [autopilot_thread]


def create_app() -> Flask:
    """Gibt die konfigurierte Flask-App ohne Seiteneffekte (ohne Worker-Start) zurück."""
    return app


@app.route("/api/run", methods=["POST"])
def trigger_run_api():
    """Startet das Suchen & Herunterladen auf Twitch."""
    if execute_harvest_job():
        return jsonify({"success": True, "message": "Harvesting gestartet"})
    return jsonify({"success": False, "message": "Pipeline läuft bereits"})

@app.route("/process-one/<clip_id>", methods=["POST"])
def process_one_clip_route(clip_id):
    """Übernimmt einen Clip aus der Warteschlange ins Studio."""
    process_single_clip(clip_id)
    return redirect(url_for("index"))

@app.route("/api/process-all", methods=["POST"])
def process_all_api():
    """Schneidet alle Clips in der Warteschlange im Hintergrund."""
    if execute_process_all_job():
        return jsonify({"success": True, "message": "Schneidevorgang gestartet"})
    return jsonify({"success": False, "message": "Pipeline ist bereits beschäftigt"})

@app.route("/queue/delete/<clip_id>", methods=["POST"])
def delete_queue_clip(clip_id):
    """Löscht Rohdateien und markiert den Clip als dauerhaft gelöscht."""
    cancel_active_render(clip_id)
    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
    txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
    for p in [raw_path, ass_path, txt_path]:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    update_clip_status(clip_id, "deleted")
    status_manager.log(f"Clip {clip_id} gelöscht & dauerhaft ignoriert.")
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"success": True, "clip_id": clip_id})
    return redirect(url_for("index"))

@app.route("/queue/delete-older", methods=["POST"])
def delete_older_queue_clips():
    """Löscht alle Rohclips aus der Warteschlange (status = 'harvested'), deren Erstellungsdatum vor dem heutigen Tag liegt."""
    today_local = datetime.now().date()
    deleted_ids = []

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clip_id, clip_created_at, harvested_at FROM clips WHERE status = 'harvested'")
        rows = cursor.fetchall()

        for r in rows:
            clip_id = r["clip_id"]
            ts = r["clip_created_at"] or r["harvested_at"]
            is_older = False
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
                    if dt.date() < today_local:
                        is_older = True
                except Exception:
                    is_older = True
            else:
                is_older = True

            if is_older:
                deleted_ids.append(clip_id)

    count = 0
    for clip_id in deleted_ids:
        cancel_active_render(clip_id)
        raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
        txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
        words_path = RAW_CLIPS_DIR / f"{clip_id}_words.json"
        for p in [raw_path, ass_path, txt_path, words_path]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        update_clip_status(clip_id, "deleted")
        count += 1

    status_manager.log(f"🧹 {count} Roh-Clips von gestern und älter aus der Warteschlange gelöscht.")
    return redirect(url_for("index"))

def _safe_resolve_clip_path(base_dir: Path, clip_id: str, suffix: str = ".mp4") -> Optional[Path]:
    """Prüft, ob der Pfad sicher innerhalb des base_dir liegt (Schutz vor Directory Traversal)."""
    # Nur erlaubte Zeichen im clip_id
    if not clip_id or any(c in clip_id for c in ("/", "\\", "..")):
        return None
    p = (base_dir / f"{clip_id}{suffix}").resolve()
    try:
        p.relative_to(base_dir.resolve())
        return p
    except ValueError:
        return None

@app.route("/raw-video/<clip_id>")
def serve_raw_video(clip_id):
    raw_path = _safe_resolve_clip_path(RAW_CLIPS_DIR, clip_id, ".mp4")
    if raw_path and raw_path.exists():
        return send_file(raw_path, mimetype="video/mp4", conditional=True)
    return "Rohdatei nicht gefunden", 404

def make_svg_poster(title: str = "Clip", streamer: str = "") -> Response:
    """Erzeugt ein sauberes SVG-Vorschaubild mit Gradient und Titel als Fallback."""
    safe_title = html.escape(str(title)[:45])
    safe_streamer = html.escape(str(streamer).upper()) if streamer else "CLIP"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
      <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0b0f19" />
          <stop offset="50%" stop-color="#111827" />
          <stop offset="100%" stop-color="#05070e" />
        </linearGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#bg)"/>
      <circle cx="640" cy="320" r="64" fill="#1e293b" stroke="#334155" stroke-width="4"/>
      <polygon points="625,290 670,320 625,350" fill="#f59e0b"/>
      <text x="640" y="440" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="28" font-weight="bold" fill="#f8fafc" text-anchor="middle">{safe_title}</text>
      <text x="640" y="480" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="18" font-weight="bold" fill="#f59e0b" text-anchor="middle" letter-spacing="2">{safe_streamer}</text>
    </svg>"""
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})

@app.route("/thumbnail/<clip_id>")
def serve_thumbnail(clip_id):
    """Liefert ein JPEG-Vorschaubild (Poster) für das 9:16 Short."""
    thumb_path = generate_thumbnail(clip_id, force=False)
    if thumb_path and thumb_path.exists() and thumb_path.stat().st_size > 0:
        response = send_file(thumb_path, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    title = clip_id
    streamer = ""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT streamer, ai_title, original_title FROM clips WHERE clip_id = ?", (clip_id,))
            clip = cursor.fetchone()
            if clip:
                streamer = clip["streamer"] or ""
                title = clip["ai_title"] or clip["original_title"] or clip_id
    except Exception:
        pass
    return make_svg_poster(title, streamer)

@app.route("/thumbnail/raw/<clip_id>")
def serve_raw_thumbnail(clip_id):
    """Liefert das originale 16:9 Vorschaubild der Rohvideodatei."""
    thumb_dir = DATA_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"raw_{clip_id}.jpg"

    if not thumb_path.exists():
        video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        if video_path.exists():
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-ss", "00:00:00.500", "-i", str(video_path),
                    "-frames:v", "1", "-q:v", "2", str(thumb_path)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            except Exception:
                pass

            if not thumb_path.exists():
                try:
                    cap = cv2.VideoCapture(str(video_path))
                    cap.set(cv2.CAP_PROP_POS_MSEC, 500)
                    ret, frame = cap.read()
                    if not ret:
                        cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                        ret, frame = cap.read()
                    if ret and frame is not None:
                        cv2.imwrite(str(thumb_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    cap.release()
                except Exception:
                    pass

    if thumb_path.exists():
        response = send_file(thumb_path, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    return make_svg_poster("Twitch Rohdatei", clip_id)

@app.route("/video/<clip_id>")
def serve_video(clip_id):
    video_path = _safe_resolve_clip_path(SHORTS_OUTPUT_DIR, f"short_{clip_id}", ".mp4")
    if video_path and video_path.exists():
        response = send_file(video_path, mimetype="video/mp4", conditional=True)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    return "Video nicht gefunden", 404

@app.route("/download/short/<clip_id>")
def download_short_route(clip_id):
    """Ermöglicht den direkten Download des gerenderten 9:16 Shorts in HQ."""
    video_path = _safe_resolve_clip_path(SHORTS_OUTPUT_DIR, f"short_{clip_id}", ".mp4")
    if not video_path or not video_path.exists():
        return "Video noch nicht gerendert oder nicht gefunden.", 404

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT streamer, ai_title, original_title FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    streamer = clip["streamer"] if clip else "Short"
    raw_title = (clip["ai_title"] or clip["original_title"] or clip_id) if clip else clip_id
    clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "-", "_")).strip()
    download_filename = f"{streamer}_{clean_title[:45]}.mp4"

    return send_file(
        video_path,
        as_attachment=True,
        download_name=download_filename,
        mimetype="video/mp4"
    )

@app.route("/download/raw/<clip_id>")
def download_raw_route(clip_id):
    """Ermöglicht den Download der originalen Twitch-Rohvideodatei."""
    raw_path = _safe_resolve_clip_path(RAW_CLIPS_DIR, clip_id, ".mp4")
    if raw_path and raw_path.exists():
        return send_file(raw_path, as_attachment=True, download_name=f"raw_{clip_id}.mp4", mimetype="video/mp4")
    return "Rohdatei nicht gefunden", 404

def get_last_export_dir() -> Path:
    last_file = DATA_DIR / "last_export_dir.txt"
    if last_file.exists():
        try:
            p = Path(last_file.read_text(encoding="utf-8").strip())
            if p.is_dir():
                return p
        except Exception:
            pass
    dl = Path.home() / "Downloads"
    return dl if dl.exists() else SHORTS_OUTPUT_DIR

def set_last_export_dir(path: Path):
    try:
        last_file = DATA_DIR / "last_export_dir.txt"
        target_dir = path if path.is_dir() else path.parent
        last_file.write_text(str(target_dir), encoding="utf-8")
    except Exception:
        pass

def _open_in_explorer(target_path: Path, select_file: bool = True) -> None:
    """Öffnet den Windows Explorer im Zielordner oder markiert die exportierte Datei."""
    if sys.platform != "win32":
        return
    try:
        resolved = target_path.resolve()
        if select_file:
            # /select, darf bei Leerzeichen nicht zusammen mit dem Pfad gequotet werden,
            # weil explorer.exe den Parameter sonst ignoriert und "Dokumente" öffnet.
            safe_path = str(resolved).replace('"', "")
            subprocess.Popen(f'explorer.exe /select,"{safe_path}"')
        else:
            subprocess.Popen(["explorer.exe", str(resolved)])
    except Exception:
        pass

@app.route("/api/export-all-ready", methods=["POST"])
def export_all_ready_clips():
    """Phase 5: Exportiert alle fertig geschnittenen 9:16 Shorts in einen wählbaren Zielordner."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clip_id, streamer, ai_title, original_title FROM clips WHERE status = 'ready'")
        clips = cursor.fetchall()

    if not clips:
        return jsonify({"success": False, "error": "Keine fertigen Shorts zum Exportieren vorhanden."}), 400

    init_dir = get_last_export_dir()
    from src.save_dialog import open_save_dialog
    # Wähle einen Dateinamen als Ordner-Anker
    selected = open_save_dialog("hier_speichern.mp4", str(init_dir), "Zielordner für alle fertigen Shorts auswählen")
    if not selected:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    target_dir = Path(selected).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    set_last_export_dir(target_dir)

    exported_count = 0
    for c in clips:
        cid = c["clip_id"]
        vpath = SHORTS_OUTPUT_DIR / f"short_{cid}.mp4"
        if vpath.exists():
            st = c["streamer"] or "Short"
            title = c["ai_title"] or c["original_title"] or cid
            clean_t = "".join(ch for ch in title if ch.isalnum() or ch in (" ", "-", "_")).strip()[:40]
            dest = target_dir / f"{st}_{clean_t}_{cid[:6]}.mp4"
            try:
                shutil.copy2(vpath, dest)
                exported_count += 1
            except Exception:
                pass

    status_manager.log(f"📦 Stapel-Export: {exported_count} fertige Shorts nach '{target_dir.name}' exportiert.")
    _open_in_explorer(target_dir, select_file=False)

    return jsonify({
        "success": True,
        "count": exported_count,
        "folder": str(target_dir),
        "message": f"{exported_count} Shorts erfolgreich exportiert!"
    })

@app.route("/api/clip/<clip_id>/export-dialog", methods=["POST", "GET"])
def export_clip_dialog(clip_id):
    """Öffnet den nativen Windows 'Speichern unter'-Dialog und speichert das 9:16 Short am Wunschort."""
    import shutil
    import subprocess

    video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if not video_path.exists():
        video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"

    if not video_path.exists():
        return jsonify({"success": False, "error": "Video nicht gefunden"}), 404

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT streamer, ai_title, original_title FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    streamer = clip["streamer"] if clip else "Short"
    raw_title = (clip["ai_title"] or clip["original_title"] or clip_id) if clip else clip_id
    clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "-", "_")).strip()
    clean_title = clean_title[:45]
    filename = f"{streamer}_{clean_title}.mp4"

    init_dir = get_last_export_dir()

    selected_path_str = ""
    try:
        from src.save_dialog import open_save_dialog
        selected_path_str = open_save_dialog(filename, str(init_dir), f"HQ Video speichern unter ({streamer})")
    except Exception as dlg_err:
        print(f"[!] Direct save_dialog exception: {dlg_err}, trying subprocess...")
        try:
            res = subprocess.run(
                [sys.executable, "-m", "src.save_dialog", filename, str(init_dir), f"HQ Video speichern unter ({streamer})"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=180
            )
            if res.returncode == 0 and res.stdout:
                selected_path_str = res.stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return jsonify({"success": False, "error": f"Dialog-Fehler: {e}"}), 500

    if not selected_path_str:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    dest_path = Path(selected_path_str)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, dest_path)
        set_last_export_dir(dest_path.parent)

        _open_in_explorer(dest_path)

        return jsonify({
            "success": True,
            "cancelled": False,
            "filename": dest_path.name,
            "path": str(dest_path),
            "folder": str(dest_path.parent)
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Kopierfehler: {e}"}), 500

@app.route("/api/clip/<clip_id>/export-raw-dialog", methods=["POST", "GET"])
def export_raw_dialog(clip_id):
    """Öffnet den nativen Windows 'Speichern unter'-Dialog für die 16:9 Rohdatei."""
    import shutil
    import subprocess

    video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    if not video_path.exists():
        return jsonify({"success": False, "error": "Rohdatei nicht gefunden"}), 404

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT streamer, original_title FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    streamer = clip["streamer"] if clip else "Clip"
    raw_title = (clip["original_title"] or clip_id) if clip else clip_id
    clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "-", "_")).strip()[:40]
    filename = f"{streamer}_raw_{clean_title}.mp4" if clean_title else f"raw_{clip_id}.mp4"

    init_dir = get_last_export_dir()

    selected_path_str = ""
    try:
        from src.save_dialog import open_save_dialog
        selected_path_str = open_save_dialog(filename, str(init_dir), f"Rohdatei speichern unter ({streamer})")
    except Exception as dlg_err:
        print(f"[!] Direct raw save_dialog exception: {dlg_err}, trying subprocess...")
        try:
            res = subprocess.run(
                [sys.executable, "-m", "src.save_dialog", filename, str(init_dir), f"Rohdatei speichern unter ({streamer})"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=180
            )
            if res.returncode == 0 and res.stdout:
                selected_path_str = res.stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return jsonify({"success": False, "error": f"Dialog-Fehler: {e}"}), 500

    if not selected_path_str:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    dest_path = Path(selected_path_str)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, dest_path)
        set_last_export_dir(dest_path.parent)

        _open_in_explorer(dest_path)

        return jsonify({
            "success": True,
            "cancelled": False,
            "filename": dest_path.name,
            "path": str(dest_path),
            "folder": str(dest_path.parent)
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Kopierfehler: {e}"}), 500

@app.route("/api/clip/<clip_id>/export-to-downloads", methods=["POST", "GET"])
def export_clip_to_downloads(clip_id):
    """Kopiert das gerenderte 9:16 Video direkt in den Windows Downloads-Ordner und öffnet Explorer."""
    import shutil
    import subprocess

    video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if not video_path.exists():
        video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"

    if not video_path.exists():
        return jsonify({"success": False, "error": "Video nicht gefunden"}), 404

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT streamer, ai_title, original_title FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    streamer = clip["streamer"] if clip else "Short"
    raw_title = (clip["ai_title"] or clip["original_title"] or clip_id) if clip else clip_id
    clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "-", "_")).strip()
    clean_title = clean_title[:45]
    filename = f"{streamer}_{clean_title}.mp4"

    downloads_dir = Path.home() / "Downloads"
    if not downloads_dir.exists():
        downloads_dir = SHORTS_OUTPUT_DIR

    dest_path = downloads_dir / filename
    if dest_path.exists():
        dest_path = downloads_dir / f"{streamer}_{clean_title}_{clip_id[:6]}.mp4"
        filename = dest_path.name

    shutil.copy2(video_path, dest_path)

    # Windows Explorer mit markierter Datei öffnen
    _open_in_explorer(dest_path)

    return jsonify({
        "success": True,
        "filename": filename,
        "path": str(dest_path),
        "folder": str(dest_path.parent)
    })

@app.route("/api/clip/<clip_id>/export-raw-to-downloads", methods=["POST", "GET"])
def export_raw_to_downloads(clip_id):
    """Kopiert das rohe 16:9 Video in Downloads und öffnet Explorer."""
    import shutil
    import subprocess

    video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    if not video_path.exists():
        return jsonify({"success": False, "error": "Rohdatei nicht gefunden"}), 404

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT streamer, original_title FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    streamer = clip["streamer"] if clip else "Clip"
    raw_title = (clip["original_title"] or clip_id) if clip else clip_id
    clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "-", "_")).strip()[:40]
    filename = f"{streamer}_raw_{clean_title}.mp4" if clean_title else f"raw_{clip_id}.mp4"

    downloads_dir = Path.home() / "Downloads"
    if not downloads_dir.exists():
        downloads_dir = RAW_CLIPS_DIR
    dest_path = downloads_dir / filename
    if dest_path.exists():
        dest_path = downloads_dir / f"{streamer}_raw_{clean_title}_{clip_id[:6]}.mp4"
        filename = dest_path.name

    shutil.copy2(video_path, dest_path)

    _open_in_explorer(dest_path)

    return jsonify({"success": True, "filename": filename, "path": str(dest_path), "folder": str(dest_path.parent)})

@app.route("/save/<clip_id>", methods=["POST"])
def save_clip(clip_id):
    action = request.form.get("action")
    is_fetch = request.headers.get("X-Requested-With") == "fetch"

    def _finish_save(redirect_tab: str = "studio"):
        if is_fetch:
            return jsonify({"success": True, "action": action or "save", "clip_id": clip_id})
        return redirect(url_for("index") + f"?tab={redirect_tab}")

    if action == "delete":
        cancel_active_render(clip_id)
        update_clip_status(clip_id, "deleted")
        short_file = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
        if short_file.exists():
            deleted = False
            for _ in range(5):
                try:
                    short_file.unlink()
                    deleted = True
                    break
                except PermissionError:
                    time.sleep(0.15)
                except OSError as e:
                    print(f"[!] Konnte {short_file.name} nicht löschen: {e}")
                    deleted = True
                    break
            if not deleted and short_file.exists():
                def _bg_unlink(path_to_del):
                    for _ in range(10):
                        time.sleep(0.5)
                        try:
                            if not path_to_del.exists():
                                return
                            path_to_del.unlink()
                            return
                        except OSError:
                            continue
                threading.Thread(target=_bg_unlink, args=(short_file,), daemon=True).start()
        return _finish_save("studio")

    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    meta = {}
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    title = request.form.get("title", meta.get("title", "")).strip()
    sticker_text = request.form.get("sticker_text", meta.get("sticker_text", "")).strip() if "sticker_text" in request.form else meta.get("sticker_text", "")
    sub_position = request.form.get("sub_position", meta.get("sub_position", "bottom")) if "sub_position" in request.form else meta.get("sub_position", "bottom")
    layout_mode = request.form.get("layout_mode", meta.get("layout_mode", "auto")) if "layout_mode" in request.form else meta.get("layout_mode", "auto")
    cam_filter = request.form.get("cam_filter", meta.get("cam_filter", "none")) if "cam_filter" in request.form else meta.get("cam_filter", "none")

    txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
    if "transcript" in request.form:
        edited_transcript = request.form.get("transcript", "").strip()
        txt_path.write_text(edited_transcript, encoding="utf-8")
    elif txt_path.exists():
        edited_transcript = txt_path.read_text(encoding="utf-8", errors="replace").strip()
    else:
        edited_transcript = ""

    meta["sticker_text"] = sticker_text
    meta["title"] = title
    meta["sub_position"] = sub_position
    meta["layout_mode"] = layout_mode
    meta["cam_filter"] = cam_filter
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    update_clip_status(clip_id, "ready", ai_title=title)

    if action == "rerender":
        # Wenn der Nutzer nochmals auf Rendern drückt:
        # Vorheriges Rendering sofort abbrechen und neues starten!
        cancel_active_render(clip_id)
        status_manager.log(f"Vorheriges Rendering für '{title}' abgebrochen. Starte Neu-Rendern...")

        raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
        txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
        words_path = RAW_CLIPS_DIR / f"{clip_id}_words.json"

        if edited_transcript:
            txt_path.write_text(edited_transcript, encoding="utf-8")

        if raw_path.exists():
            status_manager.set_task("rendering", f"Rendere Short '{title}' neu...", clip_title=title)
            try:
                active_sub_path = None
                if sub_position != "none":
                    from src.video.subtitles import SubtitleGenerator, align_words_with_edited_text
                    sub_gen = SubtitleGenerator()
                    segments = None
                    if words_path.exists():
                        try:
                            with open(words_path, "r", encoding="utf-8") as wf:
                                segments = json.load(wf)
                        except Exception:
                            pass
                    
                    if not segments and raw_path.exists():
                        from src.video.transcriber import VideoTranscriber
                        transcriber = VideoTranscriber()
                        segments = transcriber.transcribe(raw_path)

                    # Wenn der Nutzer den Untertiteltext bearbeitet hat, Wörter und Zeitstempel neu ausrichten!
                    if edited_transcript:
                        total_dur = 30.0
                        try:
                            from src.video.layout import get_video_duration
                            total_dur = get_video_duration(raw_path)
                        except Exception:
                            pass
                        segments = align_words_with_edited_text(segments, edited_transcript, total_dur)
                        with open(words_path, "w", encoding="utf-8") as wf:
                            json.dump(segments, wf, indent=2, ensure_ascii=False)

                    if segments:
                        sub_gen.generate_ass(segments, ass_path, position=sub_position)
                        active_sub_path = ass_path

                def on_rerender_progress(pct: int, eta: int, speed: str):
                    status_manager.set_progress(percent=pct, eta_seconds=eta, speed=speed, phase="rendering", clip_id=clip_id)

                rendered_file = composer.render_short(
                    raw_video_path=raw_path,
                    clip_id=clip_id,
                    ass_subtitle_path=active_sub_path,
                    header_sticker_text=sticker_text,
                    streamer_name=(meta.get("streamer") or ""),
                    layout_mode=layout_mode,
                    custom_crops=meta.get("custom_crops"),
                    cam_filter=cam_filter,
                    on_progress=on_rerender_progress
                )
                if rendered_file and rendered_file.exists():
                    try:
                        generate_thumbnail(clip_id, force=True)
                    except Exception:
                        pass
                    status_manager.set_task("idle", f"Neu-Rendern von '{title}' fertiggestellt.")
                else:
                    status_manager.set_task("error", f"Neu-Rendern von '{title}' fehlgeschlagen oder abgebrochen.")
            except Exception as e:
                status_manager.set_task("error", f"Fehler beim Neu-Rendern von '{title}': {e}")
            finally:
                status_manager.reset_progress()

        return _finish_save("studio")

    return _finish_save("studio")


@app.route("/api/clip/<clip_id>/toggle-published", methods=["POST"])
def toggle_clip_published(clip_id):
    data = request.get_json(silent=True) or {}
    is_pub = 1 if data.get("is_published", False) else 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE clips SET is_manually_published = ? WHERE clip_id = ?", (is_pub, clip_id))
        conn.commit()

    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["is_manually_published"] = bool(is_pub)
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    status_manager.log(f"Clip {clip_id}: 'Veröffentlicht'-Status auf {bool(is_pub)} gesetzt.")
    return jsonify({"success": True, "is_manually_published": bool(is_pub)})

@app.route("/api/streamers/add", methods=["POST"])
def add_streamer_route():
    name = request.form.get("name", "").strip().lower()
    min_views = int(request.form.get("min_views", 30))
    max_clips = int(request.form.get("max_clips", 2))
    layout = request.form.get("layout", "auto")
    if name:
        if add_streamer(name, min_views=min_views, max_clips=max_clips, layout=layout):
            status_manager.log(f"Streamer '{name}' zur Überwachungsliste hinzugefügt.")
    return redirect(url_for("index"))

@app.route("/api/streamers/remove/<name>", methods=["POST"])
def remove_streamer_route(name):
    if remove_streamer(name):
        status_manager.log(f"Streamer '{name}' aus der Überwachungsliste entfernt.")
    return redirect(url_for("index"))

@app.route("/api/streamers/update", methods=["POST"])
def update_streamer_route():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip().lower()
    min_views = data.get("min_clip_views")
    max_clips = data.get("max_clips_per_run")
    layout = data.get("layout")
    if not name:
        return jsonify({"success": False, "error": "Name fehlt"}), 400
    
    if update_streamer(name, min_views=min_views, max_clips=max_clips, layout=layout):
        status_manager.log(f"Streamer '{name}' Einstellungen aktualisiert (Min. Views: {min_views}, Max Clips: {max_clips}).")
        return jsonify({"success": True, "message": f"Streamer {name} aktualisiert"})
    return jsonify({"success": False, "error": "Streamer nicht gefunden"}), 404

@app.route("/api/streamers/<name>/layout", methods=["POST"])
def set_streamer_layout_route(name):
    clean_name = name.strip().lower()
    data = request.get_json(silent=True) or request.form
    layout = data.get("layout", "custom")
    custom_crops = data.get("custom_crops")
    
    if update_streamer(clean_name, layout=layout, custom_crops=custom_crops):
        status_manager.log(f"Standard-Layout für Streamer '{clean_name}' auf '{layout}' gesetzt.")
        return jsonify({"success": True, "message": f"Standard-Layout für {clean_name} aktualisiert"})
    return jsonify({"success": False, "error": "Streamer nicht gefunden"}), 404

@app.route("/api/streamers/<name>/config", methods=["GET", "POST"])
def streamer_config_route(name):
    clean_name = name.strip().lower()
    streamers = get_streamers()
    st_cfg = next((s for s in streamers if s.get("name", "").lower() == clean_name), None)
    if not st_cfg:
        return jsonify({"success": False, "error": f"Streamer '{clean_name}' nicht gefunden."}), 404

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        min_views = data.get("min_clip_views")
        max_clips = data.get("max_clips_per_run")
        layout = data.get("layout")
        custom_crops = data.get("custom_crops")
        
        ok = update_streamer(
            clean_name,
            min_views=min_views,
            max_clips=max_clips,
            layout=layout,
            custom_crops=custom_crops
        )
        if ok:
            status_manager.log(f"Streamer-Konfiguration für '{clean_name}' gespeichert.")
            return jsonify({"success": True, "message": f"Konfiguration für {clean_name} gespeichert."})
        return jsonify({"success": False, "error": "Fehler beim Speichern"}), 500

    return jsonify({
        "success": True,
        "name": st_cfg.get("name"),
        "min_clip_views": st_cfg.get("min_clip_views", 25),
        "max_clips_per_run": st_cfg.get("max_clips_per_run", 2),
        "layout": st_cfg.get("layout", "auto"),
        "has_custom_crops": bool(st_cfg.get("custom_crops")),
        "custom_crops": st_cfg.get("custom_crops")
    })

@app.route("/api/streamers/<name>/sample-clip", methods=["GET", "POST"])
def streamer_sample_clip_route(name):
    clean_name = name.strip().lower()
    raw_clips_dir = RAW_CLIPS_DIR
    raw_clips_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Prüfen ob wir bereits eine lokale Videodatei dieses Streamers haben
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT clip_id, original_title FROM clips WHERE LOWER(streamer) = ? AND raw_path IS NOT NULL ORDER BY rowid DESC LIMIT 1",
            (clean_name,)
        )
        row = cursor.fetchone()
        if row:
            c_id = row["clip_id"]
            local_p = raw_clips_dir / f"{c_id}.mp4"
            if local_p.exists() and local_p.stat().st_size > 10000:
                return jsonify({
                    "success": True,
                    "clip_id": c_id,
                    "streamer": clean_name,
                    "title": row["original_title"] or f"Clip von {clean_name}",
                    "is_new": False
                })

    # Prüfen ob bereits ein sample_{name}.mp4 existiert
    sample_p = raw_clips_dir / f"sample_{clean_name}.mp4"
    if sample_p.exists() and sample_p.stat().st_size > 10000:
        return jsonify({
            "success": True,
            "clip_id": f"sample_{clean_name}",
            "streamer": clean_name,
            "title": f"Test-Clip von {clean_name}",
            "is_new": False
        })

    # 2. Von Twitch über GQL einen Clip herunterladen
    try:
        from src.harvesters.twitch_clips import TwitchClipHarvester
        h = TwitchClipHarvester()
        clips = h.fetch_clips_gql_fallback(clean_name, time_filter="LAST_WEEK", limit=5)
        if not clips:
            clips = h.fetch_clips_gql_fallback(clean_name, time_filter="ALL_TIME", limit=5)
            
        if not clips:
            return jsonify({"success": False, "error": f"Keine Clips für {clean_name} auf Twitch gefunden."}), 404
            
        top_clip = clips[0]
        c_id = f"sample_{clean_name}"
        dl_res = h.download_clip(top_clip["url"], c_id)
        if not dl_res or not dl_res.exists():
            return jsonify({"success": False, "error": "Download des Test-Clips fehlgeschlagen."}), 500
            
        return jsonify({
            "success": True,
            "clip_id": c_id,
            "streamer": clean_name,
            "title": top_clip.get("title") or f"Test-Clip von {clean_name}",
            "is_new": True
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Fehler beim Laden des Test-Clips: {e}"}), 500

@app.route("/api/streamers/update-all-views", methods=["POST"])
def update_all_streamers_views_route():
    data = request.get_json(silent=True) or request.form
    min_views = data.get("min_clip_views")
    if min_views is None:
        return jsonify({"success": False, "error": "Mindest-Views fehlen"}), 400
    try:
        count = update_all_streamers_min_views(int(min_views))
        status_manager.log(f"Mindest-Views für alle {count} Streamer auf {min_views} gesetzt.")
        return jsonify({"success": True, "count": count, "message": f"Mindest-Views für alle {count} Streamer auf {min_views} gesetzt."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/settings", methods=["GET", "POST"])
def settings_route():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        ok = save_autopilot_settings(data)
        if ok:
            status_manager.log("System- und Autopilot-Einstellungen wurden gespeichert.")
            return jsonify({"success": True, "message": "Einstellungen gespeichert."})
        return jsonify({"success": False, "error": "Konnte Einstellungen nicht speichern"}), 500
    return jsonify(get_autopilot_settings())

# ==================== MANUELLE STREAMER-CLIP-SUCHE & IMPORT ====================

@app.route("/api/twitch/search-clips", methods=["GET"])
def api_twitch_search_clips():
    """Sucht manuell Clips eines beliebigen Twitch-Streamers im gewünschten Zeitfenster."""
    streamer = (request.args.get("streamer") or request.args.get("q") or "").strip()
    timeframe = (request.args.get("timeframe") or "LAST_DAY").strip().upper()
    try:
        limit = int(request.args.get("limit", 24))
    except (ValueError, TypeError):
        limit = 24

    if not streamer:
        return jsonify({"success": False, "error": "Bitte einen Streamer-Namen eingeben.", "clips": []}), 400

    from src.harvesters.twitch_clips import TwitchClipHarvester
    harvester = TwitchClipHarvester()
    result = harvester.search_channel_clips_detailed(streamer, time_filter=timeframe, limit=limit)
    if not result.get("success"):
        return jsonify(result), 404 if "nicht gefunden" in (result.get("error") or "") else 400

    clips = result.get("clips", [])
    if clips:
        clip_ids = [c["clip_id"] for c in clips]
        placeholders = ",".join("?" for _ in clip_ids)
        status_map = {}
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT clip_id, status FROM clips WHERE clip_id IN ({placeholders})", clip_ids)
            for row in cursor.fetchall():
                status_map[row["clip_id"]] = row["status"]

        for c in clips:
            c["db_status"] = status_map.get(c["clip_id"])
            created_ago, created_full = format_relative_time(c.get("created_at"))
            c["created_ago"] = created_ago
            c["created_full"] = created_full

    return jsonify(result)


@app.route("/api/twitch/import-clip", methods=["POST"])
def api_twitch_import_clip():
    """Lädt einen manuell ausgewählten Twitch-Clip herunter und übernimmt ihn in Studio oder Warteschlange."""
    data = request.get_json(silent=True) or {}
    clip_id = (data.get("clip_id") or "").strip()
    streamer = (data.get("streamer") or "").strip().lower()
    title = (data.get("title") or "Clip").strip()
    url = (data.get("url") or "").strip()
    mode = (data.get("mode") or "studio").strip().lower()

    if not clip_id or not url or not streamer:
        return jsonify({"success": False, "error": "Clip-Daten (clip_id, streamer, url) sind unvollständig."}), 400
    if any(ch in clip_id for ch in ("/", "\\", "..")):
        return jsonify({"success": False, "error": "Ungültige Clip-ID."}), 400

    def _upsert_imported_clip(raw_file_path: Path):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT clip_id FROM clips WHERE clip_id = ?", (clip_id,))
            exists = cursor.fetchone() is not None
            if exists:
                cursor.execute("""
                    UPDATE clips
                    SET status = 'harvested', raw_path = ?, rendered_path = NULL,
                        error_log = NULL, is_manually_published = 0, harvested_at = ?
                    WHERE clip_id = ?
                """, (str(raw_file_path), datetime.now().isoformat(), clip_id))
            else:
                cursor.execute("""
                    INSERT INTO clips (
                        clip_id, streamer, platform, original_title, url, view_count,
                        duration, clip_created_at, harvested_at, status, raw_path
                    ) VALUES (?, ?, 'twitch', ?, ?, ?, ?, ?, ?, 'harvested', ?)
                """, (
                    clip_id,
                    streamer,
                    title,
                    url,
                    int(data.get("view_count") or 0),
                    float(data.get("duration") or 30.0),
                    data.get("created_at"),
                    datetime.now().isoformat(),
                    str(raw_file_path)
                ))
            conn.commit()

    if mode == "queue":
        try:
            from src.harvesters.twitch_clips import TwitchClipHarvester
            harvester = TwitchClipHarvester()
            raw_path = harvester.download_clip(url, clip_id)
            if not raw_path or not raw_path.exists():
                return jsonify({"success": False, "error": "Clip-Download fehlgeschlagen."}), 500
            _upsert_imported_clip(raw_path)
            status_manager.log(f"📥 Clip '{title}' ({streamer}) manuell in Warteschlange importiert.")
            return jsonify({"success": True, "mode": "queue", "message": f"'{title}' in Warteschlange importiert!"})
        except Exception as e:
            return jsonify({"success": False, "error": f"Import fehlgeschlagen: {e}"}), 500

    # Direkt ins Studio importieren (Download + Transkription + Untertitel + 9:16 Render)
    with _WORKER_LOCK:
        if status_manager.get_state().get("is_running", False):
            return jsonify({
                "success": False,
                "error": "Pipeline arbeitet gerade noch an einem anderen Clip. Bitte kurz warten oder '+ Queue' nutzen."
            }), 409
        status_manager.set_task("processing", f"Lade Clip '{title}' für Studio-Import...", clip_title=title, streamer=streamer)

    def studio_import_worker():
        try:
            from src.harvesters.twitch_clips import TwitchClipHarvester
            harvester = TwitchClipHarvester()
            raw_path = harvester.download_clip(url, clip_id)
            if not raw_path or not raw_path.exists():
                status_manager.set_task("error", f"Download fehlgeschlagen für '{title}'.")
                return

            _upsert_imported_clip(raw_path)
            process_single_clip(clip_id)
        except Exception as e:
            status_manager.reset_progress()
            status_manager.set_task("error", f"Fehler beim Studio-Import von '{title}': {e}")

    t = threading.Thread(target=studio_import_worker, daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "mode": "studio",
        "message": f"Import & 9:16 Rendering für '{title}' gestartet..."
    })

# ==================== VISUELLER ZUSCHNITT (CROP) ENDPOINTS ====================

@app.route("/api/clip/<clip_id>/meta")
def get_clip_meta_api(clip_id):
    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    meta = {}
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as mf:
                meta = json.load(mf)
        except Exception:
            pass

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()

    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    vw, vh, duration = 1920, 1080, 30.0
    if raw_path.exists():
        try:
            cap = cv2.VideoCapture(str(raw_path))
            vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
            vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = round(frame_count / max(1.0, fps), 1)
            cap.release()
        except Exception:
            pass

    streamer_name = ((clip["streamer"] if clip else None) or meta.get("streamer") or "").strip()
    if not streamer_name and clip_id.startswith("sample_"):
        streamer_name = clip_id.replace("sample_", "").strip()
    streamer_crops = None
    streamer_layout = "auto"
    if streamer_name:
        for s in get_streamers():
            if s.get("name", "").lower() == streamer_name.lower():
                streamer_layout = s.get("layout", "auto")
                streamer_crops = s.get("custom_crops")
                break

    resolved_crops = meta.get("custom_crops") or streamer_crops
    resolved_layout = meta.get("layout_mode") or streamer_layout
    txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
    transcript_text = ""
    if txt_path.exists():
        try:
            transcript_text = txt_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass

    return jsonify({
        "clip_id": clip_id,
        "streamer": streamer_name,
        "title": (clip["ai_title"] or clip["original_title"] if clip else "") or meta.get("title", "") or (f"Test-Clip ({streamer_name})" if streamer_name else clip_id),
        "sticker_text": meta.get("sticker_text", ""),
        "sub_position": meta.get("sub_position", "bottom"),
        "layout_mode": resolved_layout,
        "custom_crops": resolved_crops,
        "streamer_default_crops": streamer_crops,
        "cam_filter": meta.get("cam_filter", "none"),
        "transcript": transcript_text,
        "video_w": vw,
        "video_h": vh,
        "duration": duration
    })

@app.route("/api/clip/<clip_id>/detect-cam")
def detect_cam_api(clip_id):
    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    if not raw_path.exists():
        return jsonify({"success": False, "error": "Clip nicht gefunden"}), 404

    cap = cv2.VideoCapture(str(raw_path))
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    cap.release()

    box = composer.detect_facecam_overlay(raw_path)
    if box:
        fx, fy, fw, fh = box
        cam_crop_w = max(int(fw * 2.2), 340)
        cam_crop_h = int(cam_crop_w * (720 / 1080))
        cam_crop_x = max(0, fx - int(fw * 0.6))
        cam_crop_y = max(0, fy - int(fh * 0.4))
        cam_crop_w = min(cam_crop_w, vw)
        cam_crop_h = min(cam_crop_h, vh)
        cam_crop_x = min(cam_crop_x, vw - cam_crop_w)
        cam_crop_y = min(cam_crop_y, vh - cam_crop_h)
        return jsonify({
            "success": True,
            "detected": True,
            "cam": {
                "x_pct": round(cam_crop_x / vw, 4),
                "y_pct": round(cam_crop_y / vh, 4),
                "w_pct": round(cam_crop_w / vw, 4),
                "h_pct": round(cam_crop_h / vh, 4),
                "x": cam_crop_x,
                "y": cam_crop_y,
                "w": cam_crop_w,
                "h": cam_crop_h
            }
        })
    return jsonify({
        "success": True,
        "detected": False,
        "cam": {
            "x_pct": 0.73,
            "y_pct": 0.64,
            "w_pct": 0.26,
            "h_pct": 0.34,
            "x": int(vw * 0.73),
            "y": int(vh * 0.64),
            "w": int(vw * 0.26),
            "h": int(vh * 0.34)
        }
    })

@app.route("/api/clip/<clip_id>/save-crop", methods=["POST"])
def save_crop_api(clip_id):
    data = request.get_json() or {}
    custom_crops = data.get("custom_crops")
    layout_mode = data.get("layout_mode", "custom")
    render_now = data.get("render_now", False)
    
    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    meta = {}
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as mf:
                meta = json.load(mf)
        except Exception:
            pass
            
    meta["layout_mode"] = layout_mode
    if custom_crops:
        meta["custom_crops"] = custom_crops
    
    if "title" in data and data["title"] is not None:
        meta["title"] = str(data["title"]).strip()
    if "sticker_text" in data and data["sticker_text"] is not None:
        meta["sticker_text"] = str(data["sticker_text"]).strip()
    if "sub_position" in data and data["sub_position"]:
        meta["sub_position"] = data["sub_position"]
    if "cam_filter" in data:
        meta["cam_filter"] = data["cam_filter"]
    if "transcript" in data and isinstance(data["transcript"], str):
        (RAW_CLIPS_DIR / f"{clip_id}_transcript.txt").write_text(data["transcript"].strip(), encoding="utf-8")

    with open(meta_file, "w", encoding="utf-8") as mf:
        json.dump(meta, mf, indent=2, ensure_ascii=False)

    if clip_id.startswith("sample_"):
        streamer_name = clip_id.replace("sample_", "").strip()
        if streamer_name:
            update_streamer(streamer_name, layout=layout_mode, custom_crops=custom_crops)

    update_clip_status(clip_id, "ready", ai_title=meta.get("title"))

    if render_now:
        cancel_active_render(clip_id)
        raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
        words_path = RAW_CLIPS_DIR / f"{clip_id}_words.json"
        title = meta.get("title") or clip_id
        sticker_text = meta.get("sticker_text") or title
        sub_position = meta.get("sub_position") or "bottom"
        streamer_name = (meta.get("streamer") or "").strip()
        if not streamer_name:
            try:
                with get_db_connection() as conn:
                    row = conn.execute("SELECT streamer FROM clips WHERE clip_id = ?", (clip_id,)).fetchone()
                    if row and row["streamer"]:
                        streamer_name = str(row["streamer"]).strip()
            except Exception:
                pass
        raw_transcript = data.get("transcript")

        def render_worker():
            finished_cleanly = False
            try:
                if not raw_path.exists():
                    status_manager.set_task("error", f"Rohvideo für '{title}' nicht gefunden.")
                    finished_cleanly = True
                    return

                status_manager.set_task("rendering", f"Rendere Short mit Zuschnitt: '{title}'...", clip_title=title, streamer=streamer_name)
                active_sub_path = None
                if sub_position != "none":
                    from src.video.subtitles import SubtitleGenerator
                    sub_gen = SubtitleGenerator()
                    segments = None
                    if words_path.exists():
                        try:
                            with open(words_path, "r", encoding="utf-8") as wf:
                                segments = json.load(wf)
                        except Exception:
                            pass
                    if not segments:
                        from src.video.transcriber import VideoTranscriber
                        transcriber = VideoTranscriber()
                        segments = transcriber.transcribe(raw_path)
                        with open(words_path, "w", encoding="utf-8") as wf:
                            json.dump(segments, wf, indent=2, ensure_ascii=False)

                    if isinstance(raw_transcript, str) and raw_transcript.strip():
                        ed_transcript = raw_transcript.strip()
                        txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
                        txt_path.write_text(ed_transcript, encoding="utf-8")
                        total_dur = 30.0
                        try:
                            from src.video.layout import get_video_duration
                            total_dur = get_video_duration(raw_path)
                        except Exception:
                            pass
                        from src.video.subtitles import align_words_with_edited_text
                        segments = align_words_with_edited_text(segments, ed_transcript, total_dur)
                        with open(words_path, "w", encoding="utf-8") as wf:
                            json.dump(segments, wf, indent=2, ensure_ascii=False)

                    if segments:
                        sub_gen.generate_ass(segments, ass_path, position=sub_position)
                        active_sub_path = ass_path

                def on_progress(pct: int, eta: int, speed: str):
                    status_manager.set_progress(percent=pct, eta_seconds=eta, speed=speed, phase="rendering", clip_id=clip_id)

                rendered_path = composer.render_short(
                    raw_video_path=raw_path,
                    clip_id=clip_id,
                    ass_subtitle_path=active_sub_path,
                    header_sticker_text=sticker_text,
                    streamer_name=streamer_name,
                    layout_mode=layout_mode,
                    custom_crops=custom_crops,
                    cam_filter=meta.get("cam_filter", "none"),
                    on_progress=on_progress
                )
                if rendered_path and rendered_path.exists():
                    try:
                        generate_thumbnail(clip_id, force=True)
                    except Exception:
                        pass
                    status_manager.set_task("idle", f"Zuschnitt-Rendering für '{title}' fertiggestellt.")
                    update_clip_status(clip_id, "ready", rendered_path=str(rendered_path), ai_title=title)
                else:
                    status_manager.set_task("error", f"Rendering für '{title}' fehlgeschlagen oder abgebrochen.")
                finished_cleanly = True
            except Exception as e:
                status_manager.log(f"Fehler beim Rendern von {clip_id}: {e}")
                status_manager.set_task("error", f"Fehler beim Rendern von '{title}': {e}")
                finished_cleanly = True
            finally:
                status_manager.reset_progress()
                if not finished_cleanly:
                    status_manager.set_task("error", f"Rendering für '{title}' unerwartet beendet.")

        t = threading.Thread(target=render_worker, daemon=True)
        t.start()
        return jsonify({"success": True, "message": "Rendering mit manuellem Zuschnitt gestartet"})

    return jsonify({"success": True, "message": "Zuschnitt gespeichert"})

def start_studio(port: int = 5000):
    setup_logging()
    init_db()
    start_workers()
    logger.info("Clip-Farming Studio gestartet auf http://localhost:%s", port)
    print("\n" + "="*70)
    print(f"  CLIP-FARMING STUDIO GESTARTET!")
    print(f"  👉 Öffne im Browser: http://localhost:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

if __name__ == "__main__":
    start_studio()
