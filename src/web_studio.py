import os
import sys
import json
import time
import threading
import cv2
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, url_for

from src.config import (
    SHORTS_OUTPUT_DIR, RAW_CLIPS_DIR, METADATA_OUTPUT_DIR, DATA_DIR, load_config,
    get_streamers, add_streamer, remove_streamer
)
from src.database import get_db_connection, update_clip_status
from src.video.layout import VideoComposer, cancel_active_render
from src.video.filters import AVAILABLE_CAM_FILTERS
from src.uploaders.youtube import YouTubeUploader
from src.uploaders.tiktok import TikTokUploader
from src.uploaders.account_manager import account_manager
from src.uploaders.browser_login import start_tiktok_browser_login, get_browser_login_status
from src.state import status_manager

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = Flask(__name__)
@app.after_request
def add_cors_and_security_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Range, Authorization"
    response.headers["Access-Control-Expose-Headers"] = "Content-Range, Content-Length, Accept-Ranges"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Accept-Ranges"] = "bytes"
    return response


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

composer = VideoComposer()
yt_uploader = YouTubeUploader()
tt_uploader = TikTokUploader()

# Lock fuer Scheduling-Operationen
schedule_lock = threading.Lock()

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

        rendered_path = composer.render_short(
            raw_video_path=raw_path,
            clip_id=clip_id,
            ass_subtitle_path=active_sub_path,
            header_sticker_text=sticker_text,
            layout_mode="auto",
            on_progress=on_render_progress
        )

        status_manager.reset_progress()

        if rendered_path and rendered_path.exists():
            update_clip_status(clip_id, "ready", rendered_path=str(rendered_path), ai_title=metadata.get("title"))
            status_manager.set_task("idle", f"Clip '{orig_title}' fertig ins Studio übertragen.")
            return True
    except Exception as e:
        status_manager.reset_progress()
        status_manager.log(f"Fehler bei Clip {clip_id}: {e}")
        update_clip_status(clip_id, "failed", error_log=str(e))
    return False

def publish_clip_now(clip_id: str) -> bool:
    """Veröffentlicht einen einzelnen Clip sofort auf YouTube Shorts und/oder TikTok."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,))
        clip = cursor.fetchone()
        if not clip:
            return False

    short_file = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if not short_file.exists():
        return False

    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    meta = {}
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    title = clip["ai_title"] or meta.get("title") or clip["original_title"] or "Twitch Short"
    desc = meta.get("description", "#Shorts #Gaming")
    tags = meta.get("tags", "Shorts, Gaming, Twitch")

    yt_id = None
    tt_id = None

    # YouTube Upload
    if yt_uploader.is_configured():
        status_manager.set_task("publishing", f"Lade '{title}' auf YouTube Shorts hoch...", clip_title=title)
        yt_id = yt_uploader.upload_short(short_file, title=title, description=desc, tags=tags)

    # TikTok Upload
    if tt_uploader.is_configured():
        status_manager.set_task("publishing", f"Lade '{title}' auf TikTok hoch...", clip_title=title)
        tt_id = tt_uploader.upload_short(short_file, caption=title)

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_clip_status(
        clip_id,
        "published",
        published_at=now_iso,
        youtube_video_id=yt_id,
        tiktok_video_id=tt_id
    )
    status_manager.log(f"Clip '{title}' erfolgreich veröffentlicht (YT: {yt_id or '-'}, TikTok: {tt_id or '-'})")
    status_manager.set_task("idle", f"Clip '{title}' veröffentlicht.")
    return True

def auto_publisher_worker():
    """Hintergrund-Worker: Veröffentlicht fällige geplante Clips nach Zeitspanne."""
    while True:
        try:
            time.sleep(15)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT clip_id, ai_title, original_title 
                    FROM clips 
                    WHERE status = 'scheduled' AND scheduled_publish_at <= ?
                    ORDER BY scheduled_publish_at ASC
                """, (now_str,))
                due_clips = cursor.fetchall()

            for c in due_clips:
                clip_id = c["clip_id"]
                clip_title = c["ai_title"] or c["original_title"] or clip_id
                status_manager.log(f"⏰ Zeitplan erreicht für '{clip_title}'. Starte Veröffentlichung...")
                publish_clip_now(clip_id)
        except Exception as e:
            time.sleep(15)

# Hintergrund-Thread fuer zeitgesteuertes Publizieren starten
pub_thread = threading.Thread(target=auto_publisher_worker, daemon=True)
pub_thread.start()

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="de" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Clip-Farming Studio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0b0f19; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
        .tab-btn.active { border-bottom: 2px solid #f59e0b; color: #f3f4f6; font-weight: 600; }
        .tab-content.hidden { display: none !important; }
        #preview-modal.hidden, #streamer-modal.hidden, #crop-modal.hidden {
            display: none !important;
            pointer-events: none !important;
            visibility: hidden !important;
        }
        #preview-modal:not(.hidden), #streamer-modal:not(.hidden), #crop-modal:not(.hidden) {
            display: flex !important;
            pointer-events: auto !important;
            visibility: visible !important;
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        .crop-handle {
            position: absolute;
            width: 14px;
            height: 14px;
            background: #ffffff;
            border: 2px solid #0f172a;
            border-radius: 4px;
            box-shadow: 0 0 6px rgba(0,0,0,0.8);
            z-index: 20;
            transition: transform 0.1s;
        }
        .crop-handle:hover {
            transform: scale(1.3);
            background: #f8fafc;
        }
        .handle-nw { top: -7px; left: -7px; cursor: nwse-resize; }
        .handle-ne { top: -7px; right: -7px; cursor: nesw-resize; }
        .handle-se { bottom: -7px; right: -7px; cursor: nwse-resize; }
        .handle-sw { bottom: -7px; left: -7px; cursor: nesw-resize; }
        .handle-n { top: -7px; left: calc(50% - 7px); cursor: ns-resize; }
        .handle-s { bottom: -7px; left: calc(50% - 7px); cursor: ns-resize; }
        .handle-w { top: calc(50% - 7px); left: -7px; cursor: ew-resize; }
        .handle-e { top: calc(50% - 7px); right: -7px; cursor: ew-resize; }
    </style>
    <script>
        // Immediate Zero-Delay Handlers (execute on initial paint before any async script)
        function openStreamerModal() {
            var m = document.getElementById('streamer-modal');
            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
            }
        }
        function closeStreamerModal() {
            var m = document.getElementById('streamer-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(function(el) {
                el.classList.add('hidden');
                el.style.setProperty('display', 'none', 'important');
            });
            document.querySelectorAll('.tab-btn').forEach(function(el) {
                el.classList.remove('active', 'text-amber-400');
                el.classList.add('text-slate-400');
            });
            var target = document.getElementById('tab-' + tabId);
            if (target) {
                target.classList.remove('hidden');
                target.style.setProperty('display', 'block', 'important');
            }
            var btn = document.getElementById('tab-' + tabId + '-btn');
            if (btn) {
                btn.classList.add('active', 'text-amber-400');
                btn.classList.remove('text-slate-400');
            }
        }
        var currentCropClipId = '';
        var currentCropStreamer = '';
        var currentCropTitle = '';
        var currentCropMode = 'split'; // 'split' oder 'single_916'
        var cropState = {
            cam: { x: 0.68, y: 0.58, w: 0.28, h: 0.35, enabled: true },
            game: { x: 0.24, y: 0.0, w: 0.52, h: 1.0, enabled: true },
            single: { x: 0.34, y: 0.0, w: 0.32, h: 1.0, enabled: true }
        };
        var activeCropDrag = null;
        var cropFallbackImg = new Image();

        function openCropModal(clipId, streamer, title) {
            if (!clipId) return;
            currentCropClipId = clipId;
            currentCropStreamer = streamer || '';
            currentCropTitle = title || '';

            var badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = (streamer ? streamer + ': ' : '') + (title ? title.slice(0, 30) : clipId);

            var m = document.getElementById('crop-modal');
            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
            }

            // Sync visual boxes immediately so they are never at (0, 0)
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');

            // Preload thumbnail into fallback image for instant canvas rendering
            cropFallbackImg.src = '/thumbnail/' + clipId;
            cropFallbackImg.onload = function() {
                draw916Preview();
            };

            // Setup Video
            var vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.poster = '/thumbnail/' + clipId;
                vid.muted = true;
                vid.src = '/raw-video/' + clipId;
                vid.currentTime = 0.5;
                vid.load();
                vid.play().then(function() {
                    vid.pause();
                    vid.currentTime = 0.5;
                    draw916Preview();
                }).catch(function() {
                    draw916Preview();
                });
            }

            // Fetch saved metadata if available
            fetch('/api/clip/' + clipId + '/meta')
                .then(function(r) { return r.json(); })
                .then(function(meta) {
                    if (meta && meta.custom_crops) {
                        applyLoadedCropMeta(meta);
                    }
                    updateBoxDom('cam');
                    updateBoxDom('game');
                    updateBoxDom('single');
                    draw916Preview();
                })
                .catch(function() {
                    draw916Preview();
                });
        }

        function closeCropModal() {
            var vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.pause();
                vid.src = '';
            }
            var m = document.getElementById('crop-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }

        function switchCropMode(mode) {
            currentCropMode = mode;
            var btnSplit = document.getElementById('btn-mode-split');
            var btnSingle = document.getElementById('btn-mode-single');
            var tbSplit = document.getElementById('toolbar-split');
            var tbSingle = document.getElementById('toolbar-single');
            var boxCam = document.getElementById('crop-box-cam');
            var boxGame = document.getElementById('crop-box-game');
            var boxSingle = document.getElementById('crop-box-single');
            var btnToggleCam = document.getElementById('btn-crop-toggle-cam');

            if (mode === 'single_916') {
                if (btnSplit) btnSplit.className = 'flex-1 py-1.5 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800';
                if (btnSingle) btnSingle.className = 'flex-1 py-1.5 px-3 rounded text-xs font-semibold transition flex items-center justify-center gap-2 bg-emerald-900/90 text-emerald-100 border border-emerald-500 shadow';
                if (tbSplit) {
                    tbSplit.classList.add('hidden');
                    tbSplit.style.display = 'none';
                }
                if (tbSingle) {
                    tbSingle.classList.remove('hidden');
                    tbSingle.style.display = 'flex';
                }
                if (boxCam) boxCam.style.display = 'none';
                if (boxGame) boxGame.style.display = 'none';
                if (boxSingle) boxSingle.style.display = 'flex';
                if (btnToggleCam) {
                    btnToggleCam.innerText = '📷 Facecam wieder aktivieren';
                    btnToggleCam.className = 'px-2.5 py-1 bg-emerald-900/80 hover:bg-emerald-800 border border-emerald-500 text-xs font-bold rounded-lg text-emerald-200 transition';
                }
                updateBoxDom('single');
            } else {
                if (btnSplit) btnSplit.className = 'flex-1 py-1.5 px-3 rounded text-xs font-semibold transition flex items-center justify-center gap-2 bg-zinc-700 text-zinc-100 border border-zinc-600';
                if (btnSingle) btnSingle.className = 'flex-1 py-1.5 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800';
                if (tbSplit) {
                    tbSplit.classList.remove('hidden');
                    tbSplit.style.display = 'block';
                }
                if (tbSingle) {
                    tbSingle.classList.add('hidden');
                    tbSingle.style.display = 'none';
                }
                if (boxCam) boxCam.style.display = 'flex';
                if (boxGame) boxGame.style.display = 'flex';
                if (boxSingle) boxSingle.style.display = 'none';
                if (btnToggleCam) {
                    btnToggleCam.innerText = '🚫 Keine Cam (Vollbild / 1 Rahmen)';
                    btnToggleCam.className = 'px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition';
                }
                updateBoxDom('cam');
                updateBoxDom('game');
            }
            draw916Preview();
        }

        function toggleCamEnabled() {
            if (currentCropMode === 'single_916') {
                switchCropMode('split');
            } else {
                switchCropMode('single_916');
            }
        }
        window.toggleCamEnabled = toggleCamEnabled;

        function updateBoxDom(type) {
            var box = document.getElementById('crop-box-' + type);
            if (!box) return;
            var s = cropState[type];
            if (!s) return;
            box.style.left = (s.x * 100) + '%';
            box.style.top = (s.y * 100) + '%';
            box.style.width = (s.w * 100) + '%';
            box.style.height = (s.h * 100) + '%';

            var readout = document.getElementById('crop-coords-readout');
            if (readout) {
                if (currentCropMode === 'single_916') {
                    readout.innerText = '📱 Vollbild 9:16: ' + Math.round(cropState.single.w * 1920) + 'x1080 px (1 Rahmen • Keine Cam)';
                } else {
                    var camW = Math.round(cropState.cam.w * 1920);
                    var camH = Math.round(cropState.cam.h * 1080);
                    var gameW = Math.round(cropState.game.w * 1920);
                    var gameH = Math.round(cropState.game.h * 1080);
                    readout.innerText = '📷 Cam: ' + camW + 'x' + camH + ' • 🎮 Game: ' + gameW + 'x' + gameH + ' (2 Rahmen)';
                }
            }
        }

        function draw916Preview() {
            var canvas = document.getElementById('crop-preview-canvas');
            if (!canvas) return;
            var ctx = canvas.getContext('2d');
            var vid = document.getElementById('crop-stage-video');
            var source = (vid && vid.readyState >= 2) ? vid : ((cropFallbackImg && cropFallbackImg.complete && cropFallbackImg.naturalWidth > 0) ? cropFallbackImg : null);

            ctx.fillStyle = '#05070e';
            ctx.fillRect(0, 0, 270, 480);

            if (!source) {
                ctx.fillStyle = '#1e293b';
                ctx.fillRect(10, 10, 250, 460);
                ctx.fillStyle = '#94a3b8';
                ctx.font = '12px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('Lade Frame...', 135, 240);
                return;
            }

            var vw = source.videoWidth || source.naturalWidth || 1920;
            var vh = source.videoHeight || source.naturalHeight || 1080;

            if (currentCropMode === 'single_916') {
                var sx = cropState.single.x * vw;
                var sy = 0;
                var sw = Math.max(16, cropState.single.w * vw);
                var sh = vh;
                try {
                    ctx.drawImage(source, sx, sy, sw, sh, 0, 0, 270, 480);
                } catch(e) {}
            } else {
                // Split Screen:
                // 1. Gameplay in lower portion (or background)
                var gx = cropState.game.x * vw;
                var gy = cropState.game.y * vh;
                var gw = Math.max(16, cropState.game.w * vw);
                var gh = Math.max(16, cropState.game.h * vh);

                var gameDestY = cropState.cam.enabled ? 160 : 0;
                var gameDestH = cropState.cam.enabled ? 320 : 480;

                try {
                    ctx.drawImage(source, gx, gy, gw, gh, 0, gameDestY, 270, gameDestH);
                } catch(e) {}

                // 2. Facecam in top portion
                if (cropState.cam.enabled) {
                    var cx = cropState.cam.x * vw;
                    var cy = cropState.cam.y * vh;
                    var cw = Math.max(16, cropState.cam.w * vw);
                    var ch = Math.max(16, cropState.cam.h * vh);

                    ctx.save();
                    ctx.drawImage(source, cx, cy, cw, ch, 0, 0, 270, 160);

                    // Thin separator line
                    ctx.strokeStyle = '#334155';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.moveTo(0, 160);
                    ctx.lineTo(270, 160);
                    ctx.stroke();
                    ctx.restore();
                }
            }

            // Hook Sticker simulation (title badge)
            if (currentCropTitle) {
                ctx.save();
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                var stickerW = 220;
                var stickerH = 24;
                var stickerY = (currentCropMode === 'split' && cropState.cam.enabled) ? 172 : 110;
                var stickerX = (270 - stickerW) / 2;
                ctx.fillRect(stickerX, stickerY, stickerW, stickerH);
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                var dispText = currentCropTitle.length > 32 ? currentCropTitle.slice(0, 30) + '...' : currentCropTitle;
                ctx.fillText(dispText, 135, stickerY + (stickerH / 2));
                ctx.restore();
            }
        }

        function applyPreset(preset) {
            if (preset === 'cam_br') {
                cropState.cam.x = 0.69; cropState.cam.y = 0.60; cropState.cam.enabled = true;
            } else if (preset === 'cam_tl') {
                cropState.cam.x = 0.03; cropState.cam.y = 0.05; cropState.cam.enabled = true;
            } else if (preset === 'cam_tr') {
                cropState.cam.x = 0.69; cropState.cam.y = 0.05; cropState.cam.enabled = true;
            } else if (preset === 'cam_bl') {
                cropState.cam.x = 0.03; cropState.cam.y = 0.60; cropState.cam.enabled = true;
            } else if (preset === 'cam_off') {
                cropState.cam.enabled = !cropState.cam.enabled;
            } else if (preset === 'game_center') {
                cropState.game.x = (1 - cropState.game.w) / 2;
            } else if (preset === 'game_left') {
                cropState.game.x = 0.02;
            } else if (preset === 'game_right') {
                cropState.game.x = 1 - cropState.game.w - 0.02;
            } else if (preset === 'single_center') {
                cropState.single.x = (1 - cropState.single.w) / 2;
            } else if (preset === 'single_left') {
                cropState.single.x = 0.02;
            } else if (preset === 'single_right') {
                cropState.single.x = 1 - cropState.single.w - 0.02;
            }
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');
            draw916Preview();
        }

        function setCamPixelWidth(wPx) {
            var w = Math.max(280, Math.min(800, parseInt(wPx, 10) || 540));
            cropState.cam.w = w / 1920;
            cropState.cam.h = (w * (2 / 3)) / 1080;
            if (cropState.cam.x + cropState.cam.w > 1) cropState.cam.x = 1 - cropState.cam.w;
            if (cropState.cam.y + cropState.cam.h > 1) cropState.cam.y = 1 - cropState.cam.h;
            var disp = document.getElementById('crop-cam-size-display');
            if (disp) disp.innerText = w + ' x ' + Math.round(w * (2 / 3)) + ' px';
            var slider = document.getElementById('crop-cam-size-slider');
            if (slider) slider.value = w;
            updateBoxDom('cam');
            draw916Preview();
        }

        function setGamePixelWidth(wPx) {
            var w = Math.max(480, Math.min(1200, parseInt(wPx, 10) || 972));
            cropState.game.w = w / 1920;
            cropState.game.h = 1.0;
            if (cropState.game.x + cropState.game.w > 1) cropState.game.x = 1 - cropState.game.w;
            var disp = document.getElementById('crop-game-size-display');
            if (disp) disp.innerText = w + ' x 1080 px';
            var slider = document.getElementById('crop-game-size-slider');
            if (slider) slider.value = w;
            updateBoxDom('game');
            draw916Preview();
        }

        function seekCropVideo(delta) {
            var vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.currentTime = Math.max(0, Math.min(vid.duration || 60, vid.currentTime + delta));
            }
        }

        function toggleCropVideoPlay() {
            var vid = document.getElementById('crop-stage-video');
            var btn = document.getElementById('crop-play-btn');
            if (!vid) return;
            if (vid.paused) {
                vid.play();
                if (btn) btn.innerText = '⏸️ Pause';
            } else {
                vid.pause();
                if (btn) btn.innerText = '▶️ Play';
            }
        }

        function onCropSliderInput(val) {
            var vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.currentTime = parseFloat(val) || 0;
            }
        }

        function saveCropCoordinates(renderNow) {
            if (!currentCropClipId) return;
            var payload = {
                layout_mode: currentCropMode === 'single_916' ? 'single_916' : 'custom',
                custom_crops: {
                    mode: currentCropMode,
                    cam: {
                        enabled: cropState.cam.enabled,
                        x: Math.round(cropState.cam.x * 1920),
                        y: Math.round(cropState.cam.y * 1080),
                        w: Math.round(cropState.cam.w * 1920),
                        h: Math.round(cropState.cam.h * 1080),
                        x_pct: cropState.cam.x,
                        y_pct: cropState.cam.y,
                        w_pct: cropState.cam.w,
                        h_pct: cropState.cam.h
                    },
                    game: {
                        enabled: true,
                        x: Math.round(cropState.game.x * 1920),
                        y: 0,
                        w: Math.round(cropState.game.w * 1920),
                        h: 1080,
                        x_pct: cropState.game.x,
                        y_pct: 0,
                        w_pct: cropState.game.w,
                        h_pct: 1.0
                    },
                    single: {
                        x: Math.round(cropState.single.x * 1920),
                        y: 0,
                        w: 608,
                        h: 1080,
                        x_pct: cropState.single.x,
                        y_pct: 0,
                        w_pct: 608 / 1920,
                        h_pct: 1.0
                    }
                },
                render_now: !!renderNow
            };

            fetch('/api/clip/' + currentCropClipId + '/save-crop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function() {
                closeCropModal();
                if (renderNow) {
                    if (window.showToast) window.showToast('Zuschnitt gespeichert & Rendering gestartet!', 'success');
                    setTimeout(updateLiveStatus, 300);
                } else {
                    if (window.showToast) window.showToast('Zuschnitt erfolgreich gespeichert!', 'success');
                }
            }).catch(function(err) {
                alert('Fehler beim Speichern: ' + err);
            });
        }

        function detectFacecamInCropModal() {
            if (!currentCropClipId) return;
            var badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = '🔍 KI scannt Facecam...';
            fetch('/api/clip/' + currentCropClipId + '/detect-cam')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.success && data.cam) {
                        cropState.cam.x = data.cam.x_pct;
                        cropState.cam.y = data.cam.y_pct;
                        cropState.cam.w = data.cam.w_pct;
                        cropState.cam.h = data.cam.h_pct;
                        cropState.cam.enabled = true;
                        updateBoxDom('cam');
                        draw916Preview();
                    }
                    if (badge) badge.innerText = (currentCropStreamer ? currentCropStreamer + ': ' : '') + currentCropTitle;
                })
                .catch(function() {
                    if (badge) badge.innerText = (currentCropStreamer ? currentCropStreamer + ': ' : '') + currentCropTitle;
                });
        }

        function applyLoadedCropMeta(meta) {
            if (!meta) return;
            var c = meta.custom_crops;
            if (c) {
                if (c.mode === 'single_916' || meta.layout_mode === 'single_916') {
                    currentCropMode = 'single_916';
                    if (c.single && c.single.x_pct !== undefined) cropState.single.x = c.single.x_pct;
                } else {
                    currentCropMode = 'split';
                    if (c.cam) {
                        if (c.cam.x_pct !== undefined) cropState.cam.x = c.cam.x_pct;
                        if (c.cam.y_pct !== undefined) cropState.cam.y = c.cam.y_pct;
                        if (c.cam.w_pct !== undefined) cropState.cam.w = c.cam.w_pct;
                        if (c.cam.h_pct !== undefined) cropState.cam.h = c.cam.h_pct;
                        if (c.cam.enabled !== undefined) cropState.cam.enabled = c.cam.enabled;
                    }
                    if (c.game) {
                        if (c.game.x_pct !== undefined) cropState.game.x = c.game.x_pct;
                        if (c.game.w_pct !== undefined) cropState.game.w = c.game.w_pct;
                    }
                }
            }
            switchCropMode(currentCropMode);
        }

        function initCropInteractions() {
            var stage = document.getElementById('crop-stage-container');
            if (!stage) return;

            function onPointerDown(e, target, isResize, handle) {
                e.preventDefault();
                e.stopPropagation();
                var rect = stage.getBoundingClientRect();
                activeCropDrag = {
                    target: target,
                    isResize: isResize,
                    handle: handle,
                    startX: e.clientX,
                    startY: e.clientY,
                    stageW: rect.width,
                    stageH: rect.height,
                    initX: cropState[target].x,
                    initY: cropState[target].y,
                    initW: cropState[target].w,
                    initH: cropState[target].h
                };
            }

            var camBox = document.getElementById('crop-box-cam');
            if (camBox) {
                camBox.addEventListener('pointerdown', function(e) {
                    if (e.target.classList.contains('crop-cam-handle')) return;
                    onPointerDown(e, 'cam', false, null);
                });
            }

            document.querySelectorAll('.crop-cam-handle').forEach(function(h) {
                h.addEventListener('pointerdown', function(e) {
                    onPointerDown(e, 'cam', true, h.getAttribute('data-handle'));
                });
            });

            var gameBox = document.getElementById('crop-box-game');
            if (gameBox) {
                gameBox.addEventListener('pointerdown', function(e) {
                    if (e.target.classList.contains('crop-game-handle')) return;
                    onPointerDown(e, 'game', false, null);
                });
            }

            var singleBox = document.getElementById('crop-box-single');
            if (singleBox) {
                singleBox.addEventListener('pointerdown', function(e) {
                    onPointerDown(e, 'single', false, null);
                });
            }

            window.addEventListener('pointermove', function(e) {
                if (!activeCropDrag) return;
                e.preventDefault();
                var d = activeCropDrag;
                var dx = (e.clientX - d.startX) / d.stageW;
                var dy = (e.clientY - d.startY) / d.stageH;

                if (!d.isResize) {
                    var s = cropState[d.target];
                    s.x = Math.max(0, Math.min(1 - s.w, d.initX + dx));
                    if (d.target === 'cam') {
                        s.y = Math.max(0, Math.min(1 - s.h, d.initY + dy));
                    }
                } else if (d.target === 'cam') {
                    var scaleDelta = (d.handle.includes('r') ? dx : -dx);
                    var newW = Math.max(280 / 1920, Math.min(800 / 1920, d.initW + scaleDelta));
                    var newH = (newW * 1920 * (2 / 3)) / 1080;
                    cropState.cam.w = newW;
                    cropState.cam.h = newH;
                    if (cropState.cam.x + cropState.cam.w > 1) cropState.cam.x = 1 - cropState.cam.w;
                    if (cropState.cam.y + cropState.cam.h > 1) cropState.cam.y = 1 - cropState.cam.h;
                }
                updateBoxDom(d.target);
                draw916Preview();
            });

            window.addEventListener('pointerup', function() { activeCropDrag = null; });
            window.addEventListener('pointercancel', function() { activeCropDrag = null; });

            // Setup video event listeners
            var vid = document.getElementById('crop-stage-video');
            var slider = document.getElementById('crop-time-slider');
            var timeDisp = document.getElementById('crop-time-display');
            if (vid) {
                function onMeta() {
                    if (slider) slider.max = vid.duration || 60;
                    draw916Preview();
                }
                vid.addEventListener('loadedmetadata', onMeta);
                vid.addEventListener('loadeddata', onMeta);
                vid.addEventListener('canplay', onMeta);
                vid.addEventListener('seeked', draw916Preview);
                vid.addEventListener('timeupdate', function() {
                    if (slider) slider.value = vid.currentTime;
                    if (timeDisp) {
                        var cur = Math.floor(vid.currentTime);
                        var dur = Math.floor(vid.duration || 0);
                        var curStr = (cur < 10 ? '0' : '') + Math.floor(cur / 60) + ':' + (cur % 60 < 10 ? '0' : '') + (cur % 60);
                        var durStr = (dur < 10 ? '0' : '') + Math.floor(dur / 60) + ':' + (dur % 60 < 10 ? '0' : '') + (dur % 60);
                        timeDisp.innerText = curStr + ' / ' + durStr;
                    }
                    draw916Preview();
                });
            }
        }

        function showToast(message, type) {
            type = type || 'info';
            var toast = document.getElementById('ui-toast');
            if (!toast) {
                toast = document.createElement('div');
                toast.id = 'ui-toast';
                document.body.appendChild(toast);
            }
            var borderCls = 'border-slate-700 bg-slate-900/95 text-slate-200';
            var iconSvg = '<svg class="w-4 h-4 text-amber-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
            if (type === 'success') {
                borderCls = 'border-emerald-700 bg-emerald-950/95 text-emerald-100';
                iconSvg = '<svg class="w-4 h-4 text-emerald-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>';
            } else if (type === 'error') {
                borderCls = 'border-rose-700 bg-rose-950/95 text-rose-100';
                iconSvg = '<svg class="w-4 h-4 text-rose-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
            }
            toast.className = 'fixed bottom-5 right-5 z-[9999] max-w-sm px-4 py-3 rounded-lg border ' + borderCls + ' shadow-2xl text-xs font-semibold flex items-center gap-2.5 transition-all duration-200 pointer-events-none';
            toast.innerHTML = iconSvg + ' <span>' + message + '</span>';
            toast.style.display = 'flex';
            toast.style.opacity = '1';
            clearTimeout(window._toastTimeout);
            window._toastTimeout = setTimeout(function() {
                toast.style.opacity = '0';
                setTimeout(function() { toast.style.display = 'none'; }, 250);
            }, 3500);
        }
        window.showToast = showToast;

        async function downloadShortVideo(clipId, btn, evt) {
            if (!clipId) return;
            var isQuick = evt && evt.shiftKey;
            var origContent = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="inline-block animate-spin mr-1">⌛</span> <span>' + (isQuick ? 'Speichere...' : 'Öffne...') + '</span>';
            }
            if (isQuick) {
                showToast('Exportiere HQ Video direkt in Downloads...', 'info');
            } else {
                showToast('Speicherort wählen... (Windows-Dialog geöffnet)', 'info');
            }
            try {
                var url = isQuick 
                    ? ('/api/clip/' + encodeURIComponent(clipId) + '/export-to-downloads')
                    : ('/api/clip/' + encodeURIComponent(clipId) + '/export-dialog');
                var res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Accept': 'application/json' }
                });
                var data = await res.json();
                if (data && data.success) {
                    showToast('✓ Video gespeichert: ' + data.filename, 'success');
                } else if (data && data.cancelled) {
                    showToast('Speichern abgebrochen', 'info');
                } else {
                    window.location.href = '/download/short/' + encodeURIComponent(clipId);
                }
            } catch (err) {
                console.warn('Export endpoint failed, falling back:', err);
                window.location.href = '/download/short/' + encodeURIComponent(clipId);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origContent;
                }
            }
        }

        async function downloadRawVideo(clipId, btn, evt) {
            if (!clipId) return;
            var isQuick = evt && evt.shiftKey;
            var origContent = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="inline-block animate-spin mr-1">⌛</span> <span>' + (isQuick ? 'Speichere...' : 'Öffne...') + '</span>';
            }
            if (isQuick) {
                showToast('Exportiere Rohdatei direkt in Downloads...', 'info');
            } else {
                showToast('Speicherort wählen... (Windows-Dialog geöffnet)', 'info');
            }
            try {
                var url = isQuick
                    ? ('/api/clip/' + encodeURIComponent(clipId) + '/export-raw-to-downloads')
                    : ('/api/clip/' + encodeURIComponent(clipId) + '/export-raw-dialog');
                var res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Accept': 'application/json' }
                });
                var data = await res.json();
                if (data && data.success) {
                    showToast('✓ Rohdatei gespeichert: ' + data.filename, 'success');
                } else if (data && data.cancelled) {
                    showToast('Speichern abgebrochen', 'info');
                } else {
                    window.location.href = '/download/raw/' + encodeURIComponent(clipId);
                }
            } catch (err) {
                console.warn('Export raw endpoint failed, falling back:', err);
                window.location.href = '/download/raw/' + encodeURIComponent(clipId);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origContent;
                }
            }
        }

        window.addEventListener('DOMContentLoaded', function() {
            initCropInteractions();
        });
        setTimeout(initCropInteractions, 100);
        var currentPreviewClipId = '';
        var currentPreviewStreamer = '';
        var currentPreviewTitle = '';

        function openRawPreview(clipId, streamer, title, views, duration, createdAgo, createdFull) {
            if (!clipId) return;
            currentPreviewClipId = clipId;
            currentPreviewStreamer = streamer || '';
            currentPreviewTitle = title || '';
            var sEl = document.getElementById('modal-streamer');
            if (sEl) sEl.innerText = (streamer || '').toUpperCase();
            var tEl = document.getElementById('modal-title');
            if (tEl) tEl.innerText = title || '';
            var statsElem = document.getElementById('modal-stats');
            if (statsElem) {
                var txt = (views || 0) + ' Views • ' + (duration || 0) + 's (Rohdatei)';
                if (createdAgo) txt += ' • ' + createdAgo;
                statsElem.innerText = txt;
                if (createdFull) statsElem.title = createdFull;
            }
            var player = document.getElementById('modal-video-player');
            if (player) {
                player.poster = '/thumbnail/' + clipId;
                player.src = '/raw-video/' + clipId;
                player.load();
                player.play().catch(function() {});
            }
            var procForm = document.getElementById('modal-process-form');
            if (procForm) procForm.action = '/process-one/' + clipId;
            var delForm = document.getElementById('modal-delete-form');
            if (delForm) delForm.action = '/queue/delete/' + clipId;
            var dlRaw = document.getElementById('modal-download-raw');
            if (dlRaw) {
                dlRaw.onclick = function(e) { downloadRawVideo(clipId, dlRaw, e); };
            }
            var m = document.getElementById('preview-modal');
            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
            }
        }
        function closePreviewModal() {
            var player = document.getElementById('modal-video-player');
            if (player) {
                player.pause();
                player.src = '';
            }
            var m = document.getElementById('preview-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }
        function triggerRun() {
            var btn = document.getElementById('btn-trigger');
            if (btn) {
                btn.disabled = true;
                btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-zinc-800 text-zinc-400 font-semibold text-xs rounded cursor-not-allowed';
                btn.innerHTML = '<span class="inline-block animate-spin mr-1">⟳</span> Suche läuft...';
            }
            fetch('/api/run', { method: 'POST' }).then(function() {
                if (window.showToast) window.showToast('Twitch-Scan gestartet!', 'info');
                setTimeout(updateLiveStatus, 200);
            });
        }
        function processAll() {
            if (window.__realProcessAll) {
                window.__realProcessAll();
            } else {
                fetch('/api/process-all', { method: 'POST' }).then(function() {
                    setTimeout(updateLiveStatus, 200);
                });
            }
        }
        function toggleLogs() {
            var box = document.getElementById('log-box');
            var icon = document.getElementById('log-toggle-icon');
            if (!box) return;
            if (box.classList.contains('hidden') || box.style.display === 'none') {
                box.classList.remove('hidden');
                box.style.display = 'block';
                if (icon) icon.innerText = '▲ Verbergen';
                window.logsOpen = true;
            } else {
                box.classList.add('hidden');
                box.style.display = 'none';
                if (icon) icon.innerText = '▼ Anzeigen';
                window.logsOpen = false;
            }
        }
        function updateLiveStatus() {
            fetch('/api/status')
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    var dot = document.getElementById('live-dot');
                    var text = document.getElementById('live-status-text');
                    var desc = document.getElementById('live-task-desc');
                    var btn = document.getElementById('btn-trigger');
                    var progressCard = document.getElementById('render-progress-card');
                    var progressBar = document.getElementById('render-progress-bar');
                    var progressPercent = document.getElementById('render-percent-text');
                    var progressEta = document.getElementById('render-eta-text');
                    var progressSpeed = document.getElementById('render-speed-badge');
                    var progressTitle = document.getElementById('render-progress-title');

                    if (data.is_running) {
                        if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
                        if (text) text.innerText = 'AKTIV: ' + (data.status || 'ARBEITET').toUpperCase();
                        if (desc) desc.innerText = (data.current_task || '') + (data.streamer ? ' (' + data.streamer + ')' : '');
                        if (btn) {
                            btn.disabled = true;
                            btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-zinc-800 text-zinc-400 font-semibold text-xs rounded cursor-not-allowed';
                            btn.innerHTML = '<span class="inline-block animate-spin mr-1">⟳</span> Suche läuft...';
                        }
                        if (data.status === 'rendering' || data.progress_percent > 0) {
                            if (progressCard) progressCard.classList.remove('hidden');
                            if (progressBar) progressBar.style.width = data.progress_percent + '%';
                            if (progressPercent) progressPercent.innerText = data.progress_percent + '%';
                            if (progressEta && data.eta_seconds) progressEta.innerText = 'Noch ca. ' + data.eta_seconds + 's';
                            if (progressSpeed && data.speed) progressSpeed.innerText = data.speed + ' NVENC';
                            if (progressTitle) progressTitle.innerText = data.current_task || 'Rendere Video...';
                        } else {
                            if (progressCard) progressCard.classList.add('hidden');
                        }
                    } else {
                        if (dot) dot.className = 'w-2 h-2 rounded-full bg-slate-400';
                        if (text) text.innerText = 'STANDBY';
                        if (desc) desc.innerText = data.current_task || 'Bereit zur Ausführung';
                        if (progressCard) progressCard.classList.add('hidden');
                        if (btn && btn.disabled) {
                            btn.disabled = false;
                            btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-400 font-semibold text-xs rounded transition text-zinc-950 shadow-sm';
                            btn.innerHTML = '<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Neue Clips auf Twitch suchen';
                        }
                    }

                    if (data.logs && data.logs.length > 0) {
                        var countEl = document.getElementById('log-count');
                        if (countEl) countEl.innerText = data.logs.length + ' Einträge';
                        var box = document.getElementById('log-box');
                        if (box) {
                            box.innerHTML = data.logs.slice(-40).map(function(l) {
                                return '<div class="text-slate-300 leading-relaxed font-mono">' + l + '</div>';
                            }).join('');
                            box.scrollTop = box.scrollHeight;
                        }
                    }
                })
                .catch(function(err) {});
        }
        setInterval(updateLiveStatus, 1500);
        setTimeout(updateLiveStatus, 400);
    </script>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-7xl mx-auto space-y-6">
        
        <!-- Header & Live Status Bar -->
        <header class="flex flex-col lg:flex-row justify-between items-start lg:items-center pb-6 border-b border-slate-800 gap-4">
            <div>
                <div class="flex items-center gap-3">
                    <h1 class="text-xl font-bold tracking-tight text-zinc-100 flex items-center gap-2.5">
                        <span>CLIP-FARMING</span><span class="text-xs font-mono font-medium px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">STUDIO</span>
                    </h1>
                    <span id="live-indicator" class="flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold uppercase tracking-wider bg-slate-800 text-slate-300 border border-slate-700 shadow-sm">
                        <span class="w-2 h-2 rounded-full {% if is_running %}bg-emerald-400 animate-ping{% else %}bg-slate-400{% endif %}" id="live-dot"></span>
                        <span id="live-status-text">{% if is_running %}AKTIV: {{ current_status|upper }}{% else %}STANDBY{% endif %}</span>
                    </span>
                </div>
                <p id="live-task-desc" class="text-slate-400 text-sm mt-1">{{ current_task }}</p>
            </div>

            <!-- Quick Action Buttons -->
            <div class="flex flex-wrap items-center gap-3">
                <button onclick="openStreamerModal()" class="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm rounded transition text-slate-200 shadow">
                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg> Streamer verwalten ({{ streamers|length }})
                </button>
                <button onclick="triggerRun()" id="btn-trigger" class="flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-400 font-semibold text-xs rounded transition text-zinc-950 shadow-sm">
                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Neue Clips auf Twitch suchen
                </button>
            </div>
        </header>

        <!-- LIVE RENDER PROGRESS CARD (Wird eingeblendet wenn aktiv) -->
        <div id="render-progress-card" class="hidden bg-zinc-900 border border-zinc-700 rounded-lg p-5 shadow-2xl animate-pulse-subtle">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-3">
                <div class="flex items-center gap-2.5">
                    <span class="w-3 h-3 rounded-full bg-pink-500 animate-ping"></span>
                    <span id="render-progress-title" class="text-sm font-bold text-white tracking-wide">Rendern aktiv...</span>
                </div>
                <div class="flex items-center gap-3 font-mono">
                    <span id="render-speed-badge" class="text-xs bg-zinc-800 text-zinc-300 px-2.5 py-0.5 rounded border border-zinc-700">NVENC</span>
                    <span id="render-eta-text" class="text-xs font-semibold text-amber-300 bg-amber-950/60 px-2 py-0.5 rounded border border-amber-800/60">Noch ca. --s</span>
                    <span id="render-percent-text" class="text-lg font-black text-white">0%</span>
                </div>
            </div>
            <!-- Progress Bar -->
            <div class="w-full bg-slate-950 rounded h-2.5 overflow-hidden p-0.5 border border-slate-700/80 shadow-inner">
                <div id="render-progress-bar" class="bg-amber-500 h-full rounded transition-all duration-300 shadow-lg" style="width: 0%"></div>
            </div>
        </div>

        <!-- KPI Cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-lg cursor-pointer hover:border-zinc-700 transition" onclick="switchTab('queue')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">1. Warteschlange</span>
                <span class="text-3xl font-black text-amber-400 mt-1 block">{{ counts.harvested }}</span>
                <span class="text-xs text-slate-500 mt-1 block">Rohdateien gespeichert</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-lg cursor-pointer hover:border-zinc-700 transition" onclick="switchTab('studio')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">2. Studio & Freigabe</span>
                <span class="text-3xl font-black text-amber-400 mt-1 block">{{ counts.ready }}</span>
                <span class="text-xs text-slate-500 mt-1 block">9:16 Shorts bereit</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-lg cursor-pointer hover:border-zinc-700 transition" onclick="switchTab('planner')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">3. Veröffentlichungs-Plan</span>
                <div class="flex items-baseline gap-2 mt-1">
                    <span class="text-3xl font-black text-sky-400">{{ counts.scheduled }}</span>
                    <span class="text-sm font-bold text-emerald-400">/ {{ counts.published }} online</span>
                </div>
                <span class="text-xs text-slate-500 mt-1 block">Zeitgesteuerte Veröffentlichung</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-lg cursor-pointer hover:border-zinc-700 transition" onclick="switchTab('accounts')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">4. Konten-Status</span>
                <div class="flex items-center gap-2 mt-1">
                    <span class="text-sm font-bold {% if account_status.youtube.is_connected %}text-emerald-400{% else %}text-slate-500{% endif %}">YT: {% if account_status.youtube.is_connected %}✓{% else %}✗{% endif %}</span>
                    <span class="text-slate-600">•</span>
                    <span class="text-sm font-bold {% if account_status.tiktok.is_connected %}text-emerald-400{% else %}text-slate-500{% endif %}">TikTok: {% if account_status.tiktok.is_connected %}✓{% else %}✗{% endif %}</span>
                </div>
                <span class="text-xs text-slate-500 mt-1 block">Klicken zum Verknüpfen</span>
            </div>
        </div>

        <!-- Live Activity Log Bar (Collapsible) -->
        <div class="bg-slate-900/60 border border-slate-800/80 rounded-lg p-4">
            <div class="flex justify-between items-center cursor-pointer" onclick="toggleLogs()">
                <div class="flex items-center gap-2">
                    <span class="text-xs font-bold uppercase tracking-wider text-amber-400">📡 Live Activity Feed</span>
                    <span id="log-count" class="text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded">{{ initial_logs|length }} Einträge</span>
                </div>
                <span id="log-toggle-icon" class="text-slate-400 text-xs font-medium hover:text-amber-400 transition">▲ Verbergen</span>
            </div>
            <div id="log-box" class="mt-3 bg-slate-950 p-4 rounded font-mono text-xs text-slate-300 max-h-48 overflow-y-auto space-y-1.5 border border-slate-800/50">
                {% if initial_logs %}
                    {% for log in initial_logs[-40:] %}
                        <div class="text-slate-300 leading-relaxed font-mono">{{ log }}</div>
                    {% endfor %}
                {% else %}
                    <div class="text-slate-500">Warte auf Aktionen...</div>
                {% endif %}
            </div>
        </div>

        <!-- Tabs Navigation -->
        <div class="flex flex-wrap gap-4 border-b border-slate-800 text-sm font-semibold">
            <button onclick="switchTab('queue')" id="tab-queue-btn" class="tab-btn pb-3 active flex items-center gap-2">
                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/></svg> 1. Warteschlange ({{ counts.harvested }})
            </button>
            <button onclick="switchTab('studio')" id="tab-studio-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"/></svg> 2. Studio & Freigabe ({{ counts.ready }})
            </button>
            <button onclick="switchTab('planner')" id="tab-planner-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> 3. Veröffentlichungs-Planer ({{ counts.scheduled }})
            </button>
            <button onclick="switchTab('accounts')" id="tab-accounts-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg> 4. Konten verknüpfen
            </button>
        </div>

        <!-- TAB 1: WARTESCHLANGE -->
        <div id="tab-queue" class="tab-content space-y-4">
            <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center p-4 bg-slate-950/70 border-b border-slate-800 gap-3">
                    <div>
                        <span class="text-sm font-bold text-slate-200">📥 {{ counts.harvested }} Roh-Clips lokal auf der Festplatte</span>
                        <span class="text-xs text-slate-400 block">Tipp: Klicke auf eine Zeile, um das Video vor dem Schneiden abzuspielen.</span>
                    </div>
                    {% if counts.harvested > 0 %}
                    <div class="flex flex-wrap items-center gap-2.5">
                        {% if older_queue_count > 0 %}
                        <form action="/queue/delete-older" method="POST" class="inline" onsubmit="return confirm('Wirklich alle {{ older_queue_count }} Roh-Clips von gestern und älter aus der Warteschlange löschen?\n\n(Clips von heute bleiben vollständig erhalten)');">
                            <button type="submit" class="px-4 py-2.5 bg-rose-950/80 hover:bg-rose-900 border border-rose-800/80 font-bold text-xs rounded shadow-lg shadow-rose-950/40 text-rose-300 hover:text-white flex items-center gap-2 transition active:scale-95" title="Löscht alle {{ older_queue_count }} Roh-Clips von gestern & älter">
                                <span><svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></span> Gestern & älter löschen ({{ older_queue_count }})
                            </button>
                        </form>
                        {% endif %}
                        <button onclick="processAll()" id="btn-process-all" class="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center gap-2 shadow-sm">
                            <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Alle Warteschlangen-Clips ins Studio übernehmen
                        </button>
                    </div>
                    {% endif %}
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-sm">
                        <thead>
                            <tr class="border-b border-slate-800 bg-slate-950/50 text-slate-400 text-xs uppercase font-semibold">
                                <th class="py-3.5 px-4 w-12 text-center whitespace-nowrap">Play</th>
                                <th class="py-3.5 px-4 whitespace-nowrap">Streamer</th>
                                <th class="py-3.5 px-4 min-w-[220px]">Titel des Clips (Klicken zum Abspielen)</th>
                                <th class="py-3.5 px-4 whitespace-nowrap">Erstellt</th>
                                <th class="py-3.5 px-4 whitespace-nowrap">Views</th>
                                <th class="py-3.5 px-4 whitespace-nowrap">Dauer</th>
                                <th class="py-3.5 px-4 whitespace-nowrap">Status</th>
                                <th class="py-3.5 px-4 text-right whitespace-nowrap">Aktion</th>
                            </tr>
                        </thead>
                        <tbody id="queue-tbody" class="divide-y divide-slate-800/80">
                            {% for clip in queue_clips %}
                            <tr onclick="openRawPreview('{{ clip.clip_id }}', '{{ clip.streamer|e }}', '{{ clip.original_title|e }}', '{{ clip.view_count }}', '{{ '%.0f'|format(clip.duration) }}', '{{ clip.created_ago|e }}', '{{ clip.created_full|e }}')"
                                class="hover:bg-slate-800/60 cursor-pointer transition group">
                                <td class="py-3.5 px-4 text-center whitespace-nowrap">
                                    <span class="w-8 h-8 rounded-full bg-slate-800 group-hover:bg-amber-500 group-hover:text-zinc-950 flex items-center justify-center text-xs text-white transition shadow">
                                        ▶
                                    </span>
                                </td>
                                <td class="py-3.5 px-4 font-bold text-amber-400 whitespace-nowrap">{{ clip.streamer }}</td>
                                <td class="py-3.5 px-4 font-semibold text-slate-200 group-hover:text-amber-400 transition">
                                    <div>{{ clip.original_title }}</div>
                                    <span class="text-xs text-slate-500 font-normal">Klicken zum Vorschauen</span>
                                </td>
                                <td class="py-3.5 px-4 whitespace-nowrap" title="{{ clip.created_full }}">
                                    <div class="flex items-center gap-1.5 text-xs text-slate-300 font-medium">
                                        <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> {{ clip.created_ago }}
                                    </div>
                                    {% if clip.created_full %}
                                    <span class="text-[11px] text-slate-500 block">{{ clip.created_full }}</span>
                                    {% endif %}
                                </td>
                                <td class="py-3.5 px-4 text-slate-300 font-semibold whitespace-nowrap"><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg> {{ clip.view_count }}</td>
                                <td class="py-3.5 px-4 text-slate-400 whitespace-nowrap">{{ "%.0f"|format(clip.duration) }}s</td>
                                <td class="py-3.5 px-4 whitespace-nowrap">
                                    <span class="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 font-medium whitespace-nowrap shadow-sm">
                                        ✓ Lokal geladen
                                    </span>
                                </td>
                                <td class="py-3.5 px-4 text-right whitespace-nowrap" onclick="event.stopPropagation()">
                                    <div class="flex items-center justify-end gap-2">
                                        <form action="/process-one/{{ clip.clip_id }}" method="POST" class="inline">
                                            <button type="submit" class="px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center gap-1.5 shadow-sm whitespace-nowrap">
                                                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879a3 3 0 11-4.242-4.242 3 3 0 014.242 0L12 12zm0 0L9.121 9.121a3 3 0 10-4.242 4.242 3 3 0 004.242 0L12 12z"/></svg> In Studio übernehmen
                                            </button>
                                        </form>
                                        <form action="/queue/delete/{{ clip.clip_id }}" method="POST" class="inline" onsubmit="return confirm('Clip unwiderruflich löschen? Er wird NIE wieder von Twitch heruntergeladen.');">
                                            <button type="submit" class="p-1.5 px-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 text-rose-300 font-bold text-xs rounded-lg transition" title="Clip löschen & dauerhaft ignorieren">
                                                <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                                            </button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="8" class="py-12 text-center text-slate-500">Keine Clips in der Warteschlange.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 2: STUDIO & FREIGABE -->
        <div id="tab-studio" class="tab-content hidden space-y-6">
            {% if ready_clips %}
            <!-- Sammel-Aktionen Header -->
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-lg gap-3">
                <div>
                    <span class="text-sm font-bold text-white">🎬 {{ counts.ready }} Shorts bereit zur Bearbeitung & Veröffentlichung</span>
                    <span class="text-xs text-slate-400 block">Du kannst jeden Clip einzeln anpassen oder alle gestaffelt im Zeitplan veröffentlichen.</span>
                </div>
                <form action="/api/schedule-all" method="POST" class="flex items-center gap-2">
                    <span class="text-xs font-semibold text-slate-400">Intervall:</span>
                    <select name="interval_minutes" class="bg-slate-800 border border-slate-700 text-xs text-white rounded-lg px-2.5 py-2">
                        <option value="15">alle 15 Min</option>
                        <option value="30" selected>alle 30 Min</option>
                        <option value="45">alle 45 Min</option>
                        <option value="60">jede 1 Stunde</option>
                        <option value="120">alle 2 Stunden</option>
                    </select>
                    <button type="submit" class="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 font-semibold text-xs rounded transition flex items-center gap-2">
                        <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Alle gestaffelt einplanen
                    </button>
                </form>
            </div>

            <!-- Streamer Filter Bar (Sortiert nach Streamer) -->
            <div id="streamer-pills-container" class="flex flex-wrap items-center gap-2 bg-slate-900/80 border border-slate-800 p-3.5 rounded-lg shadow">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">🔍 Filter nach Streamer:</span>
                <button onclick="filterStudioByStreamer('all')" id="pill-all" class="streamer-pill active px-3.5 py-1.5 rounded text-xs font-bold bg-amber-500 text-zinc-950 font-semibold transition">
                    Alle ({{ ready_clips|length }})
                </button>
                {% for st_name, count in streamer_counts.items() %}
                <button onclick="filterStudioByStreamer('{{ st_name|lower }}')" id="pill-{{ st_name|lower }}" class="streamer-pill px-3.5 py-1.5 rounded text-xs font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition">
                    {{ st_name }} ({{ count }})
                </button>
                {% endfor %}
            </div>

            <div id="studio-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
                {% for clip in ready_clips %}
                <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl flex flex-col hover:border-slate-700 transition-all duration-300 studio-clip-card {% if clip.is_manually_published %}opacity-40 grayscale hover:grayscale-0 hover:opacity-95 border-emerald-900/80 bg-slate-950/90{% endif %}" id="card-{{ clip.clip_id }}" data-streamer="{{ clip.streamer|lower }}">
                    <!-- Card Header: Streamer & Veröffentlicht-Checkbox -->
                    <div class="flex justify-between items-center bg-slate-950/90 px-4 py-2.5 border-b border-slate-800">
                        <div class="flex items-center gap-2">
                            <span class="bg-zinc-800 border border-zinc-700 text-xs font-semibold px-2 py-0.5 rounded text-amber-400">
                                {{ clip.streamer }}
                            </span>
                            {% if clip.created_ago %}
                            <span class="text-[11px] text-slate-400 font-medium whitespace-nowrap" title="{{ clip.created_full }}">
                                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> {{ clip.created_ago }}
                            </span>
                            {% endif %}
                        </div>
                        <label class="flex items-center gap-2 cursor-pointer bg-slate-900 hover:bg-slate-800 px-3 py-1 rounded-lg border border-slate-700/80 transition" title="Video als veröffentlicht markieren (graut die Karte aus)">
                            <input type="checkbox" onchange="toggleManualPublished('{{ clip.clip_id }}', this.checked)" {% if clip.is_manually_published %}checked{% endif %} class="w-4 h-4 accent-emerald-500 rounded cursor-pointer">
                            <span class="text-xs font-bold {% if clip.is_manually_published %}text-emerald-400{% else %}text-slate-400{% endif %}" id="pub-label-{{ clip.clip_id }}">
                                {% if clip.is_manually_published %}✓ Veröffentlicht{% else %}Veröffentlicht?{% endif %}
                            </span>
                        </label>
                    </div>

                    <!-- Video Player Container (9:16) -->
                    <div class="relative bg-black aspect-[9/16] w-full max-h-[480px] flex items-center justify-center overflow-hidden">
                        {% if clip.has_video %}
                        <video controls preload="metadata" poster="/thumbnail/{{ clip.clip_id }}" class="w-full h-full object-contain">
                            <source src="/video/{{ clip.clip_id }}" type="video/mp4">
                        </video>
                        {% else %}
                        <div class="text-center p-6 text-slate-500">
                            <span class="text-4xl block mb-2 animate-bounce">⏳</span>
                            Video wird gerendert...
                        </div>
                        {% endif %}
                        
                        <span class="absolute top-3 right-3 bg-slate-900/80 text-xs text-slate-300 font-semibold px-2 py-1 rounded-md backdrop-blur">
                            <svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg> {{ clip.view_count }}
                        </span>

                        {% if clip.has_video %}
                        <button type="button" onclick="downloadShortVideo('{{ clip.clip_id }}', this, event)" 
                            class="absolute bottom-3 right-3 bg-slate-900/90 hover:bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-lg border border-slate-700/80 backdrop-blur transition flex items-center gap-1.5 cursor-pointer z-10"
                            title="Speicherort wählen & HQ Video sichern (Shift-Klick für Direkt-Export in Downloads)">
                            <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/></svg> <span>HQ Download</span>
                        </button>
                        {% endif %}
                    </div>

                    <!-- Edit Form -->
                    <form action="/save/{{ clip.clip_id }}" method="POST" class="p-5 flex-1 flex flex-col justify-between gap-4">
                        <div class="space-y-3">
                            <!-- Sticker Hook Text -->
                            <div>
                                <label class="block text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-1 flex justify-between">
                                    <span>TikTok / Shorts Hook</span>
                                    <span class="text-slate-500 font-normal">Mitte</span>
                                </label>
                                <input type="text" name="sticker_text" value="{{ clip.sticker_text }}" 
                                    placeholder="z. B. Gtastys ki hittet double mace"
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                            </div>

                            <!-- Video Title -->
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                                    Titel (YouTube / TikTok)
                                </label>
                                <input type="text" name="title" value="{{ clip.title }}" 
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                            </div>

                            <!-- Untertitel-Platzierung -->
                            <div>
                                <label class="block text-xs font-semibold text-amber-400 uppercase tracking-wider mb-1">
                                    Untertitel-Platzierung
                                </label>
                                <select name="sub_position" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                                    <option value="bottom" {% if clip.sub_position == 'bottom' %}selected{% endif %}>📌 Unten (Standard, über Shorts-UI)</option>
                                    <option value="center" {% if clip.sub_position == 'center' %}selected{% endif %}>📌 Mitte (Unteres Drittel über Game)</option>
                                    <option value="top" {% if clip.sub_position == 'top' %}selected{% endif %}>📌 Oben (Über Facecam)</option>
                                    <option value="none" {% if clip.sub_position == 'none' %}selected{% endif %}>🚫 Keine Untertitel (z.B. Trymacs bereits im Stream)</option>
                                </select>
                            </div>

                            <!-- Video-Layout & Aufteilung (Split-Screen vs. Blur vs. IRL 9:16) -->
                            <div>
                                <label class="block text-xs font-semibold text-amber-400 uppercase tracking-wider mb-1">
                                    Video-Layout & Aufteilung
                                </label>
                                <select name="layout_mode" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                                    <option value="auto" {% if clip.layout_mode == 'auto' %}selected{% endif %}>🤖 Automatisch (KI erkennt Facecam vs. IRL)</option>
                                    <option value="custom" {% if clip.layout_mode == 'custom' %}selected{% endif %}>Benutzerdefiniert (Visuelle Schnittrahmen)</option>
                                    <option value="single_916" {% if clip.layout_mode == 'single_916' %}selected{% endif %}>📱 Reines 9:16 Vollbild (IRL / Einzelfokus)</option>
                                    <option value="split_cam_top" {% if clip.layout_mode == 'split_cam_top' %}selected{% endif %}>✂️ Split-Screen (Cam oben, Gameplay unten)</option>
                                    <option value="blur_stack" {% if clip.layout_mode == 'blur_stack' %}selected{% endif %}>🌫️ Blur-Stack (IRL / Vollbild mit unscharfem Hintergrund)</option>
                                </select>
                                <button type="button" onclick="openCropModal('{{ clip.clip_id }}', '{{ clip.streamer|replace("'", "\\'") }}', '{{ clip.title|replace("'", "\\'") }}')" 
                                    class="w-full mt-2 py-2 px-3 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-200 hover:text-white rounded text-xs font-medium transition flex items-center justify-center gap-2">
                                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg> Bildausschnitt anpassen (Split-Cam oder 9:16)
                                </button>
                            </div>

                            <!-- Cam-Filter / Effekte (Snapchat / TikTok Style) -->
                            <div>
                                <label class="block text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1 flex justify-between">
                                    <span>Facecam-Effekt & Warp (MLS 3D)</span>
                                    <span class="text-slate-500 font-normal">Fun-Warp für Facecam</span>
                                </label>
                                <select name="cam_filter" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500">
                                    {% for f_key, f_label in cam_filters.items() %}
                                    <option value="{{ f_key }}" {% if clip.cam_filter == f_key %}selected{% endif %}>{{ f_label }}</option>
                                    {% endfor %}
                                </select>
                            </div>

                            <!-- Transkribierter Text / Untertitel (hier editierbar) -->
                            <div>
                                <label class="block text-xs font-semibold text-amber-300 uppercase tracking-wider mb-1 flex justify-between">
                                    <span>📄 Untertiteltext (hier bearbeiten & korrigieren)</span>
                                    <span class="text-slate-500 font-normal">Wird ins Video übernommen</span>
                                </label>
                                <textarea name="transcript" rows="4" placeholder="Hier Untertiteltext bearbeiten oder eingeben..." 
                                    class="w-full min-h-[96px] bg-slate-950/90 border border-slate-700 hover:border-amber-500/70 focus:border-amber-400 rounded-lg p-3 text-xs text-slate-200 font-mono leading-relaxed focus:outline-none transition">{{ clip.transcript }}</textarea>
                            </div>
                        </div>

                        <!-- Action Buttons -->
                        <div class="pt-4 border-t border-slate-800 flex flex-col gap-2">
                            <button type="submit" name="action" value="rerender" 
                                class="w-full py-2 px-4 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center justify-center gap-2 shadow-sm">
                                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Speichern & Neu Rendern
                            </button>

                            {% if clip.has_video %}
                            <button type="button" onclick="downloadShortVideo('{{ clip.clip_id }}', this, event)" 
                                class="w-full py-2.5 px-4 bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-700/60 font-bold text-xs rounded-lg transition flex items-center justify-center gap-2 text-emerald-300 hover:text-white shadow cursor-pointer"
                                title="Speicherort wählen & HQ Video sichern (Shift-Klick für Downloads-Ordner)">
                                <span>💾</span> <span>HQ Video speichern unter... (.mp4)</span>
                            </button>
                            {% endif %}

                            <div class="grid grid-cols-2 gap-2">
                                <button type="submit" name="action" value="schedule" 
                                    class="py-2 px-3 bg-sky-700 hover:bg-sky-600 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Zeitplan
                                </button>
                                <button type="submit" name="action" value="publish_now" 
                                    class="py-2 px-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Sofort posten
                                </button>
                            </div>
                            <div class="text-right">
                                <button type="submit" name="action" value="delete" 
                                    onclick="return confirm('Clip wirklich löschen?');"
                                    class="text-xs text-rose-400 hover:text-rose-300 transition">
                                    <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg> Löschen & Ignorieren
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="bg-slate-900 border border-slate-800 rounded-lg p-12 text-center">
                <span class="text-5xl block mb-3">🎬</span>
                <h3 class="text-lg font-bold text-slate-300">Noch keine fertig gerenderten Shorts im Studio</h3>
                <p class="text-sm text-slate-500 mt-1 max-w-md mx-auto">
                    Klicke im Reiter <strong>„1. Warteschlange“</strong> bei deinen Wunsch-Clips auf <strong>„<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879a3 3 0 11-4.242-4.242 3 3 0 014.242 0L12 12zm0 0L9.121 9.121a3 3 0 10-4.242 4.242 3 3 0 004.242 0L12 12z"/></svg> In Studio übernehmen“</strong>!
                </p>
            </div>
            {% endif %}
        </div>

        <!-- TAB 3: VERÖFFENTLICHUNGS-PLANER & HISTORIE -->
        <div id="tab-planner" class="tab-content hidden space-y-6">
            
            <!-- Planer Einstellungen Card -->
            <div class="bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h3 class="text-base font-bold text-white flex items-center gap-2">
                        <svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> Automatische Veröffentlichungs-Warteschlange (Drip-Feed)
                    </h3>
                    <p class="text-xs text-slate-400 mt-1">
                        Verhindert Spam: Eingeplante Clips werden automatisch im gewählten Zeitabstand nacheinander auf YouTube Shorts & TikTok hochgeladen.
                    </p>
                </div>
                <form action="/api/schedule/set-interval" method="POST" class="flex items-center gap-2">
                    <span class="text-xs font-semibold text-slate-300">Standard-Intervall:</span>
                    <select name="interval_minutes" onchange="this.form.submit()" class="bg-slate-800 border border-slate-700 text-xs text-white rounded-lg px-3 py-2 font-semibold">
                        <option value="15" {% if account_status.publishing_interval == 15 %}selected{% endif %}><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 15 Minuten</option>
                        <option value="30" {% if account_status.publishing_interval == 30 %}selected{% endif %}><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 30 Minuten (Empfohlen)</option>
                        <option value="45" {% if account_status.publishing_interval == 45 %}selected{% endif %}><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 45 Minuten</option>
                        <option value="60" {% if account_status.publishing_interval == 60 %}selected{% endif %}><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 1 Stunde</option>
                        <option value="120" {% if account_status.publishing_interval == 120 %}selected{% endif %}><svg class="w-3.5 h-3.5 inline-block -mt-0.5 text-zinc-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 2 Stunden</option>
                    </select>
                </form>
            </div>

            <!-- 1. Geplante Clips (Warteschlange) -->
            <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
                <div class="p-4 bg-slate-950/70 border-b border-slate-800 flex justify-between items-center">
                    <span class="text-sm font-bold text-sky-400">⏳ Geplante Veröffentlichungen ({{ scheduled_clips|length }})</span>
                    <span class="text-xs text-slate-400">Hintergrund-Worker prüft alle 15 Sekunden</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-sm">
                        <thead>
                            <tr class="border-b border-slate-800 bg-slate-950/50 text-slate-400 text-xs uppercase font-semibold">
                                <th class="py-3.5 px-4">Streamer</th>
                                <th class="py-3.5 px-4">Titel</th>
                                <th class="py-3.5 px-4">Geplante Veröffentlichung</th>
                                <th class="py-3.5 px-4">Plattformen</th>
                                <th class="py-3.5 px-4 text-right">Aktionen</th>
                            </tr>
                        </thead>
                        <tbody id="planner-tbody" class="divide-y divide-slate-800/80">
                            {% for clip in scheduled_clips %}
                            <tr class="hover:bg-slate-800/40 transition">
                                <td class="py-3.5 px-4 font-bold text-amber-400">{{ clip.streamer }}</td>
                                <td class="py-3.5 px-4 font-semibold text-slate-200">{{ clip.ai_title or clip.original_title }}</td>
                                <td class="py-3.5 px-4 font-mono text-amber-300">
                                    <div class="flex items-center gap-1.5">
                                        <span>⏰ {{ clip.scheduled_publish_at }}</span>
                                    </div>
                                </td>
                                <td class="py-3.5 px-4">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs px-2 py-0.5 rounded {% if account_status.youtube.is_connected %}bg-red-950 text-red-300 border border-red-800{% else %}bg-slate-800 text-slate-500{% endif %}">YouTube</span>
                                        <span class="text-xs px-2 py-0.5 rounded {% if account_status.tiktok.is_connected %}bg-pink-950 text-pink-300 border border-pink-800{% else %}bg-slate-800 text-slate-500{% endif %}">TikTok</span>
                                    </div>
                                </td>
                                <td class="py-3.5 px-4 text-right">
                                    <div class="flex items-center justify-end gap-2">
                                        <form action="/schedule/publish-now/{{ clip.clip_id }}" method="POST" class="inline">
                                            <button type="submit" class="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 font-bold text-xs rounded-lg text-white transition">
                                                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Jetzt posten
                                            </button>
                                        </form>
                                        <form action="/schedule/cancel/{{ clip.clip_id }}" method="POST" class="inline">
                                            <button type="submit" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 font-medium text-xs text-slate-300 rounded-lg transition" title="Zurück ins Studio">
                                                ↩️ Abbrechen
                                            </button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="5" class="py-8 text-center text-slate-500">Keine Clips im Veröffentlichungs-Zeitplan. Klicke im Studio auf „<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Zeitplan“!</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- 2. Historie (Bereits veröffentlicht) -->
            <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
                <div class="p-4 bg-slate-950/70 border-b border-slate-800">
                    <span class="text-sm font-bold text-emerald-400">✓ Bereits veröffentlichte Shorts ({{ published_clips|length }})</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-sm">
                        <thead>
                            <tr class="border-b border-slate-800 bg-slate-950/50 text-slate-400 text-xs uppercase font-semibold">
                                <th class="py-3.5 px-4">Streamer</th>
                                <th class="py-3.5 px-4">Veröffentlichter Titel</th>
                                <th class="py-3.5 px-4">Veröffentlicht am</th>
                                <th class="py-3.5 px-4">Status & Link</th>
                            </tr>
                        </thead>
                        <tbody id="published-tbody" class="divide-y divide-slate-800/80">
                            {% for clip in published_clips %}
                            <tr class="hover:bg-slate-800/40 transition">
                                <td class="py-3.5 px-4 font-bold text-amber-400">{{ clip.streamer }}</td>
                                <td class="py-3.5 px-4 font-medium text-slate-200">{{ clip.ai_title or clip.original_title }}</td>
                                <td class="py-3.5 px-4 font-mono text-slate-400 text-xs">{{ clip.published_at or '-' }}</td>
                                <td class="py-3.5 px-4">
                                    {% if clip.youtube_video_id %}
                                    <a href="https://youtube.com/shorts/{{ clip.youtube_video_id }}" target="_blank" class="text-xs font-bold text-red-400 hover:underline inline-flex items-center gap-1">
                                        <span>▶</span> YouTube Short ↗
                                    </a>
                                    {% else %}
                                    <span class="text-xs text-emerald-400 font-semibold">✓ Veröffentlicht</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="4" class="py-8 text-center text-slate-500">Noch keine Clips veröffentlicht.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 4: KONTEN VERKNÜPFEN -->
        <div id="tab-accounts" class="tab-content hidden space-y-6">
            <div class="bg-slate-900/90 border border-slate-800 rounded-lg p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="flex items-center gap-3">
                    <span class="text-3xl">🔗</span>
                    <div>
                        <h2 class="text-lg font-black text-white">Social Media Konten verknüpfen</h2>
                        <p class="text-xs text-slate-400">Verbinde deine Kanäle, damit gerenderte Shorts automatisch nach Zeitplan oder auf Knopfdruck veröffentlicht werden.</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-xs font-bold px-3 py-1.5 rounded {% if account_status.youtube.is_connected %}bg-emerald-950 text-emerald-400 border border-emerald-800{% else %}bg-slate-800 text-slate-400{% endif %}">
                        YouTube: {% if account_status.youtube.is_connected %}✓ Verbunden{% else %}✗ Getrennt{% endif %}
                    </span>
                    <span class="text-xs font-bold px-3 py-1.5 rounded {% if account_status.tiktok.is_connected %}bg-emerald-950 text-emerald-400 border border-emerald-800{% else %}bg-slate-800 text-slate-400{% endif %}">
                        TikTok: {% if account_status.tiktok.is_connected %}✓ Verbunden{% else %}✗ Getrennt{% endif %}
                    </span>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <!-- Card 1: YouTube Shorts -->
                <div class="bg-slate-900 border border-slate-800 rounded-lg p-6 shadow-xl flex flex-col justify-between">
                    <div class="space-y-4">
                        <div class="flex justify-between items-start">
                            <div class="flex items-center gap-3">
                                <span class="text-3xl">🔴</span>
                                <div>
                                    <h3 class="text-lg font-bold text-white">YouTube Shorts</h3>
                                    <span class="text-xs text-slate-400">Google YouTube Data API v3</span>
                                </div>
                            </div>
                            {% if account_status.youtube.is_connected %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                🟢 Verbunden
                            </span>
                            {% elif account_status.youtube.has_secrets %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800">
                                🟡 Secrets bereit
                            </span>
                            {% else %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-zinc-800 text-slate-400 border border-slate-700">
                                ⚪ Nicht eingerichtet
                            </span>
                            {% endif %}
                        </div>

                        {% if account_status.youtube.is_connected %}
                        <div class="p-4 bg-emerald-950/40 border border-emerald-800/50 rounded space-y-2">
                            <div class="text-xs text-slate-300">
                                <strong>Kanal:</strong> <span class="text-emerald-300 font-bold">{{ account_status.youtube.channel_name }}</span>
                            </div>
                            <div class="text-xs text-slate-400">
                                Upload-Status: <span class="uppercase font-mono text-white">{{ account_status.youtube.privacy_status }}</span>
                            </div>
                        </div>
                        {% endif %}

                        <!-- Login-Button immer prominent wenn Secrets vorhanden -->
                        {% if account_status.youtube.has_secrets and not account_status.youtube.is_connected %}
                        <div class="p-4 bg-red-950/40 border border-red-500/50 rounded space-y-3 text-center">
                            <span class="text-xs font-bold text-red-300 block">Secrets hinterlegt! Letzter Schritt:</span>
                            <button type="button" onclick="startYouTubeOAuthLogin()" id="btn-yt-login"
                                class="w-full py-3 bg-gradient-to-r from-red-600 via-rose-600 to-red-600 hover:from-red-500 hover:to-rose-500 font-bold text-sm rounded text-white flex items-center justify-center gap-2 shadow-lg shadow-red-500/25 transition transform active:scale-95">
                                <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Jetzt mit Google / YouTube einloggen
                            </button>
                            <div id="yt-login-status-box" class="hidden p-3 bg-slate-900/95 border border-red-500/60 rounded text-xs font-semibold text-red-200 flex items-center justify-center gap-2">
                                <span class="animate-spin text-base">⏳</span>
                                <span id="yt-login-status-text">Google-Login im neuen Tab geöffnet...</span>
                            </div>
                        </div>
                        {% endif %}

                        {% if not account_status.youtube.is_connected %}
                        <!-- Schnell-Einrichtung: Client-ID & Secret direkt einfügen -->
                        <div class="space-y-3 pt-2">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold text-slate-200">Google OAuth Zugangsdaten:</span>
                                <a href="https://console.cloud.google.com/apis/credentials/wizard" target="_blank" class="text-2xs text-amber-400 hover:text-amber-400 underline flex items-center gap-1">
                                    <span>↗</span> Google Cloud Wizard öffnen
                                </a>
                            </div>

                            <form action="/api/accounts/youtube/save-credentials" method="POST" class="space-y-2 bg-slate-950/70 p-3 rounded border border-slate-800">
                                <input type="text" name="client_id" placeholder="Google Client-ID (z. B. 123456...apps.googleusercontent.com)" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 font-mono">
                                <input type="password" name="client_secret" placeholder="Google Client-Secret (z. B. GOCSPX-...)" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 font-mono">
                                <button type="submit" class="w-full py-2 bg-slate-800 hover:bg-slate-700 text-xs font-bold rounded-lg text-slate-200 transition">
                                    💾 Zugangsdaten speichern
                                </button>
                            </form>

                            <!-- Alternative: Datei-Upload -->
                            <details class="text-2xs text-slate-400">
                                <summary class="cursor-pointer hover:text-slate-300 font-semibold mb-2">📁 Oder client_secrets.json Datei hochladen...</summary>
                                <form action="/api/accounts/youtube/save-secrets" method="POST" enctype="multipart/form-data" class="space-y-2 bg-slate-950/50 p-2.5 rounded-lg border border-slate-800">
                                    <input type="file" name="secrets_file" accept=".json" class="w-full text-xs text-slate-400 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-2xs file:font-bold file:bg-zinc-800 file:text-zinc-200 border-zinc-700 cursor-pointer">
                                    <button type="submit" class="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-2xs font-bold rounded text-slate-300">JSON speichern</button>
                                </form>
                            </details>

                            <!-- 3-Schritte Mini-Anleitung -->
                            <div class="text-2xs text-slate-400 bg-slate-950/40 p-2.5 rounded border border-slate-800/80 space-y-1">
                                <div class="font-bold text-slate-300">30-Sekunden Schnell-Anleitung:</div>
                                <div>1. In der <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" class="text-amber-400 underline">Google Cloud Console</a> die <strong>YouTube Data API v3</strong> aktivieren.</div>
                                <div>2. Unter Anmeldedaten eine <strong>OAuth-Client-ID</strong> (Typ: Desktop-App) erstellen.</div>
                                <div>3. Client-ID & Secret oben einfügen und einloggen!</div>
                            </div>
                        </div>
                        {% endif %}
                    </div>

                    {% if account_status.youtube.is_connected %}
                    <div class="pt-6 border-t border-slate-800 mt-6 space-y-3">
                        <form action="/api/accounts/youtube/settings" method="POST" class="flex items-center gap-2">
                            <span class="text-xs text-slate-400">Sichtbarkeit:</span>
                            <select name="privacy_status" onchange="this.form.submit()" class="bg-slate-800 border border-slate-700 text-xs text-white rounded-lg px-2.5 py-1.5 flex-1">
                                <option value="private" {% if account_status.youtube.privacy_status == 'private' %}selected{% endif %}>Privat (Sicher prüfen)</option>
                                <option value="unlisted" {% if account_status.youtube.privacy_status == 'unlisted' %}selected{% endif %}>Ungelistet</option>
                                <option value="public" {% if account_status.youtube.privacy_status == 'public' %}selected{% endif %}>Öffentlich (Direkt online)</option>
                            </select>
                        </form>
                        <form action="/api/accounts/youtube/disconnect" method="POST" onsubmit="return confirm('YouTube-Verbindung wirklich trennen?');">
                            <button type="submit" class="w-full py-2 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 font-bold text-xs text-rose-300 rounded-lg transition">
                                🔌 YouTube Verbindung trennen
                            </button>
                        </form>
                    </div>
                    {% endif %}
                </div>

                <!-- Card 2: TikTok -->
                <div class="bg-slate-900 border border-slate-800 rounded-lg p-6 shadow-xl flex flex-col justify-between">
                    <div class="space-y-4">
                        <div class="flex justify-between items-start">
                            <div class="flex items-center gap-3">
                                <span class="text-3xl">🎵</span>
                                <div>
                                    <h3 class="text-lg font-bold text-white">TikTok</h3>
                                    <span class="text-xs text-slate-400">Creator Session Upload</span>
                                </div>
                            </div>
                            {% if account_status.tiktok.is_connected %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                🟢 Session aktiv
                            </span>
                            {% else %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-zinc-800 text-slate-400 border border-slate-700">
                                ⚪ Nicht verknüpft
                            </span>
                            {% endif %}
                        </div>

                        {% if account_status.tiktok.is_connected %}
                        <!-- TikTok bereits verbunden -->
                        <div class="p-5 bg-emerald-950/40 border border-emerald-800/60 rounded-lg text-center space-y-2">
                            <div class="text-2xl text-emerald-400"><svg class="w-8 h-8 mx-auto" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg></div>
                            <div class="text-sm font-bold text-emerald-300">TikTok-Konto ist erfolgreich verknüpft!</div>
                            <div class="text-xs text-slate-300">Session aktiv • Bereit für automatische Uploads</div>
                            <div class="text-2xs font-mono text-slate-500 pt-1">Session-ID: {{ account_status.tiktok.session_id_preview }}</div>
                            <div class="pt-2">
                                <button type="button" onclick="startTikTokBrowserLogin()" class="text-2xs text-slate-400 hover:text-slate-200 underline">
                                    🔄 Erneut verbinden / Anderen Account wählen
                                </button>
                            </div>
                        </div>
                        {% else %}
                        <!-- ⭐ AUTOMATISCHER BROWSER LOGIN (MÖGLICHKEIT 1) -->
                        <div class="p-4 bg-gradient-to-r from-pink-950/70 via-purple-950/60 to-pink-950/70 border border-pink-500/50 rounded-lg text-center shadow-lg">
                            <span class="text-2xs font-black text-pink-300 uppercase tracking-wider block mb-1">⭐ Automatische 1-Klick Methode (Empfohlen):</span>
                            <p class="text-xs text-slate-300 mb-3">Öffnet automatisch ein Login-Fenster. Logge dich einfach ein (z. B. <strong>QR-Code mit deiner Handy-TikTok-App scannen</strong>). Das Tool verbindet sich dann automatisch!</p>
                            
                            <button type="button" onclick="startTikTokBrowserLogin()" id="btn-tt-browser-login"
                                class="w-full py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-100 font-bold text-xs rounded border border-zinc-700 transition flex items-center justify-center gap-2">
                                 TikTok im Browserfenster verbinden (QR-Code / Login)
                            </button>

                            <div id="tt-browser-status-box" class="hidden mt-3 p-3 bg-slate-900/95 border border-pink-500/60 rounded text-xs font-semibold text-pink-200 flex items-center justify-center gap-2">
                                <span class="animate-spin text-base">⏳</span>
                                <span id="tt-browser-status-text">Warte auf Browser-Login...</span>
                            </div>
                        </div>
                        {% endif %}

                        <!-- Collapsible: Manuelle Alternative -->
                        <details class="text-2xs text-slate-400">
                            <summary class="cursor-pointer hover:text-slate-300 font-semibold mb-2">⚙️ Alternative: Manuelle sessionid Eingabe (Entwicklertools F12)...</summary>
                            
                            <div class="space-y-3 bg-slate-950/70 p-3 rounded border border-slate-800">
                                <div class="text-2xs text-slate-400 space-y-1">
                                    <p class="text-slate-300 font-bold">So findest du das Cookie:</p>
                                    <ol class="list-decimal list-inside space-y-0.5">
                                        <li>Öffne <a href="https://www.tiktok.com" target="_blank" class="text-zinc-300 underline">tiktok.com</a> und logge dich ein.</li>
                                        <li>Drücke <strong>F12</strong> &rarr; Tab <strong>Anwendung / Cookies</strong>.</li>
                                        <li>Kopiere den Wert von <code>sessionid</code> und füge ihn unten ein:</li>
                                    </ol>
                                </div>

                                <form action="/api/accounts/tiktok/save-session" method="POST" class="space-y-2">
                                    <input type="password" name="session_id" placeholder="z. B. 7a8f9c0e1b2d3..." value="{{ account_status.tiktok.session_id_preview }}"
                                        class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-500 font-mono">
                                    <div class="flex items-center gap-2">
                                        <select name="upload_mode" class="flex-1 bg-slate-900 border border-slate-700 text-xs text-white rounded-lg px-2.5 py-1.5">
                                            <option value="draft" {% if account_status.tiktok.upload_mode == 'draft' %}selected{% endif %}>Entwurf (Draft)</option>
                                            <option value="public" {% if account_status.tiktok.upload_mode == 'public' %}selected{% endif %}>Öffentlich</option>
                                        </select>
                                        <button type="submit" class="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 font-bold text-xs rounded-lg text-slate-200 transition">
                                            💾 Speichern
                                        </button>
                                    </div>
                                </form>
                            </div>
                        </details>
                    </div>

                    {% if account_status.tiktok.is_connected %}
                    <div class="pt-6 border-t border-slate-800 mt-6 space-y-3">
                        <div class="text-xs text-slate-400 flex items-center justify-between">
                            <span>Modus: <strong>{{ account_status.tiktok.upload_mode|upper }}</strong></span>
                            <span class="font-mono text-2xs text-slate-500">{{ account_status.tiktok.session_id_preview }}</span>
                        </div>
                        <form action="/api/accounts/tiktok/disconnect" method="POST" onsubmit="return confirm('TikTok-Verbindung trennen?');">
                            <button type="submit" class="w-full py-2 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 font-bold text-xs text-rose-300 rounded-lg transition">
                                🔌 TikTok Verbindung trennen
                            </button>
                        </form>
                    </div>
                    {% endif %}
                </div>

            </div>
        </div>

    </div>

    <!-- POP-UP MODAL: Lokalen Rohclip vorab ansehen -->
    <div id="preview-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden items-center justify-center p-4" style="display: none !important;" onclick="if (event.target === this) closePreviewModal();">
        <div class="bg-slate-900 border border-slate-700/80 rounded-lg max-w-4xl w-full overflow-hidden shadow-2xl animate-fade-in flex flex-col max-h-[90vh]">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/60">
                <div>
                    <span id="modal-streamer" class="text-xs font-bold text-amber-400 uppercase tracking-wider block">STREAMER</span>
                    <h3 id="modal-title" class="text-base font-bold text-white truncate max-w-xl">Clip Titel</h3>
                </div>
                <button onclick="closePreviewModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>
            
            <div class="relative bg-black aspect-video w-full flex items-center justify-center overflow-hidden">
                <video id="modal-video-player" controls autoplay class="w-full h-full object-contain">
                    <source id="modal-video-source" src="" type="video/mp4">
                    Dein Browser unterstützt dieses Video nicht.
                </video>
            </div>
            
            <div class="p-4 bg-slate-950/90 border-t border-slate-800 flex flex-col sm:flex-row justify-between items-center gap-3">
                <span id="modal-stats" class="text-xs text-slate-400 font-medium">Views & Dauer</span>
                <div class="flex items-center gap-2">
                    <button id="modal-download-raw" type="button" onclick="downloadRawVideo(currentPreviewClipId, this, event)" class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-xs text-slate-200 rounded transition flex items-center gap-1.5 cursor-pointer" title="Speicherort wählen & Rohdatei sichern (Shift-Klick für Downloads-Ordner)">
                        <span>💾</span> <span>Rohdatei speichern unter...</span>
                    </button>
                    <button type="button" onclick="closePreviewModal(); openCropModal(currentPreviewClipId, currentPreviewStreamer, currentPreviewTitle);" class="px-4 py-2.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 font-medium text-xs text-zinc-200 hover:text-white rounded transition flex items-center gap-1.5 shadow" title="Cam & Gameplay Rahmen visuell festlegen">
                        <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg> Zuschnitt festlegen
                    </button>
                    <form id="modal-delete-form" action="" method="POST" class="inline" onsubmit="return confirm('Clip unwiderruflich löschen? Er wird NIE wieder von Twitch heruntergeladen.');">
                        <button type="submit" class="px-4 py-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 font-bold text-xs text-rose-300 rounded transition">
                            <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg> Clip löschen
                        </button>
                    </form>
                    <form id="modal-process-form" action="" method="POST" class="inline">
                        <button type="submit" class="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center gap-2 shadow-sm">
                            <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879a3 3 0 11-4.242-4.242 3 3 0 014.242 0L12 12zm0 0L9.121 9.121a3 3 0 10-4.242 4.242 3 3 0 004.242 0L12 12z"/></svg> Jetzt in Studio übernehmen
                        </button>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- POP-UP MODAL: Streamer verwalten & hinzufügen -->
    <div id="streamer-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden items-center justify-center p-4" style="display: none !important;" onclick="if (event.target === this) closeStreamerModal();">
        <div class="bg-slate-900 border border-slate-700/90 rounded-lg max-w-2xl w-full overflow-hidden shadow-2xl animate-fade-in flex flex-col max-h-[90vh]">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/70">
                <div class="flex items-center gap-2.5">
                    <span class="text-xl">👥</span>
                    <h3 class="text-base font-bold text-white">Überwachte Streamer verwalten ({{ streamers|length }})</h3>
                </div>
                <button onclick="closeStreamerModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>
            
            <div class="p-5 overflow-y-auto space-y-6">
                <!-- Neuer Streamer Formular -->
                <form action="/api/streamers/add" method="POST" onsubmit="event.preventDefault(); if (window.addStreamerFromForm) window.addStreamerFromForm(this); else this.submit();" class="bg-slate-950/80 border border-zinc-700 p-4 rounded space-y-3 shadow-inner">
                    <span class="text-xs font-bold text-amber-400 uppercase tracking-wider block">Neuen Streamer hinzufügen</span>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div class="sm:col-span-1">
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Twitch Kanalname:</label>
                            <input type="text" name="name" required placeholder="z. B. rewinside, xqc..." 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500 font-semibold">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Min. Views:</label>
                            <input type="number" name="min_views" value="30" min="5" 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Max Clips/Run:</label>
                            <input type="number" name="max_clips" value="2" min="1" max="10" 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500">
                        </div>
                    </div>
                    <button type="submit" class="w-full py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition shadow-sm">
                        ➕ Streamer hinzufügen & dauerhaft speichern
                    </button>
                </form>

                <!-- Aktive Streamer Liste -->
                <div class="space-y-2">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-bold text-slate-300 uppercase tracking-wider block">Aktuell überwachte Streamer</span>
                        <span class="text-xs text-slate-500 font-mono">{{ streamers|length }} aktiv</span>
                    </div>
                    <div id="streamer-modal-list" class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-64 overflow-y-auto pr-1">
                        {% for s in streamers %}
                        <div class="flex justify-between items-center bg-slate-800/80 border border-slate-700/80 px-3.5 py-2.5 rounded hover:border-slate-600 transition">
                            <div>
                                <span class="text-xs font-bold text-white block">{{ s.name }}</span>
                                <span class="text-2xs text-slate-400 font-mono">Min. {{ s.min_clip_views }} Views • Max {{ s.max_clips_per_run }} Clips</span>
                            </div>
                            <form action="/api/streamers/remove/{{ s.name }}" method="POST" onsubmit="return confirm('Streamer {{ s.name }} wirklich entfernen?');">
                                <button type="submit" class="p-1 px-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 text-rose-300 font-bold text-xs rounded-lg transition" title="Streamer aus Überwachung entfernen">
                                    <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                                </button>
                            </form>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- POP-UP MODAL: Visueller Zuschnitt (Cam & Gameplay Rahmen ziehen) -->
    <div id="crop-modal" class="fixed inset-0 bg-black/90 backdrop-blur-lg z-50 hidden items-center justify-center p-2 sm:p-4" style="display: none !important;" onclick="if (event.target === this) closeCropModal();">
        <div class="bg-slate-900 border border-slate-700/90 rounded-lg max-w-6xl w-full overflow-hidden shadow-2xl flex flex-col max-h-[96vh]">
            <!-- Header -->
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/80">
                <div class="flex items-center gap-3">
                    <span class="text-2xl">📐</span>
                    <div>
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>Visueller Zuschnitt: Cam & Gameplay Rahmen</span>
                            <span id="crop-modal-clip-badge" class="text-xs bg-zinc-800 text-amber-400 border border-zinc-700 px-2 py-0.5 rounded font-mono truncate max-w-[200px]">Clip</span>
                        </h3>
                        <p class="text-xs text-slate-400 mt-0.5">Ziehe den <span class="text-emerald-400 font-bold">grünen Rahmen über die Facecam</span> und den <span class="text-sky-400 font-bold">blauen Rahmen über das Gameplay</span>. Die 9:16 Smartphone-Vorschau aktualisiert sich live!</p>
                    </div>
                </div>
                <button onclick="closeCropModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>

            <!-- Main Content Area: 16:9 Editor (Left) & 9:16 Live Smartphone Preview (Right) -->
            <div class="p-4 overflow-y-auto flex-1 grid grid-cols-1 lg:grid-cols-12 gap-5">
                
                <!-- Left Column: 16:9 Raw Video + Draggable Overlay Boxes (8 cols) -->
                <div class="lg:col-span-8 flex flex-col gap-3">
                    
                    <!-- Mode Switcher: Split vs. Reines 9:16 IRL Vollbild -->
                    <div class="flex items-center gap-2 bg-slate-950/80 p-1.5 rounded border border-slate-800 shadow-inner">
                        <button type="button" onclick="switchCropMode('split')" id="btn-mode-split" 
                            class="flex-1 py-2 px-3 rounded text-xs font-semibold transition flex items-center justify-center gap-2 bg-zinc-700 text-zinc-100 border border-zinc-600">
                            <span>✂️</span> Split-Screen (Cam oben + Gameplay unten)
                        </button>
                        <button type="button" onclick="switchCropMode('single_916')" id="btn-mode-single" 
                            class="flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300">
                            <span>📱</span> Reines 9:16 Vollbild (IRL / Einzelfokus ohne Trennung)
                        </button>
                    </div>

                    <!-- Stage Container (Aspect 16:9) -->
                    <div id="crop-stage-container" class="relative w-full aspect-video bg-black rounded overflow-hidden border-2 border-slate-700 shadow-2xl flex items-center justify-center select-none">
                        <!-- Video element (muted for instant autoplay/frame decoding) -->
                        <video id="crop-stage-video" muted playsinline preload="auto" class="w-full h-full object-contain pointer-events-none select-none"></video>

                        <!-- Draggable Overlay Boxes Container (Feste Größen ohne Verzerrung) -->
                        <div id="crop-overlay-layer" class="absolute inset-0 select-none pointer-events-none">
                            <!-- 🟩 Facecam Box (Feste 3:2 Proportion, frei verschiebbar & stufenlos skalierbar) -->
                            <div id="crop-box-cam" class="absolute select-none border-2 border-emerald-400 bg-emerald-500/20 shadow-sm rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:border-zinc-500 pointer-events-auto" style="left: 68%; top: 58%; width: 28%; height: 35%; display: flex;" title="Verschieben (Ziehen) oder Größe ändern (Ecken ziehen / Mausrad)">
                                <div class="absolute -top-6 left-0 bg-emerald-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>📷 Facecam</span>
                                    <span class="text-emerald-200 text-2xs font-normal">(Festes 3:2 Format)</span>
                                </div>
                                <div class="w-5 h-5 rounded-full border border-white/70 bg-emerald-500/60 pointer-events-none flex items-center justify-center shadow">
                                    <span class="text-2xs text-white font-black">✚</span>
                                </div>
                                <!-- 4 Ecken zum stufenlosen Vergrößern/Verkleinern mit festem 3:2 Seitenverhältnis -->
                                <div class="crop-cam-handle absolute -top-1.5 -left-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="tl" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="tr" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -bottom-1.5 -left-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="bl" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -bottom-1.5 -right-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="br" title="Größe anpassen (3:2)"></div>
                            </div>

                            <!-- 🟦 Gameplay Box (Feste 9:10 Proportion, frei verschiebbar & stufenlos skalierbar) -->
                            <div id="crop-box-game" class="absolute select-none border-2 border-sky-400 bg-sky-500/20 shadow-sm rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:border-zinc-500 pointer-events-auto" style="left: 24%; top: 0%; width: 52%; height: 100%; display: flex;" title="Verschieben (Ziehen) oder Größe ändern (Ecken ziehen / Mausrad)">
                                <div class="absolute -top-6 left-0 bg-sky-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>🎮 Gameplay</span>
                                    <span id="crop-game-format-badge" class="text-sky-200 text-2xs font-normal">(Festes 9:10 Format)</span>
                                </div>
                                <div class="w-5 h-5 rounded-full border border-white/70 bg-sky-500/60 pointer-events-none flex items-center justify-center shadow">
                                    <span class="text-2xs text-white font-black">✚</span>
                                </div>
                                <!-- 4 Ecken zum stufenlosen Vergrößern/Verkleinern mit festem 9:10 Seitenverhältnis -->
                                <div class="crop-game-handle absolute -top-1.5 -left-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="tl" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="tr" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -bottom-1.5 -left-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="bl" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -bottom-1.5 -right-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 transition-transform pointer-events-auto" data-handle="br" title="Gameplay-Größe anpassen (9:10)"></div>
                            </div>

                            <!-- 🟪 Reiner 9:16 IRL Vollbild-Rahmen (Festes 9:16 Format, horizontal verschiebbar) -->
                            <div id="crop-box-single" class="absolute select-none border-2 border-emerald-400 bg-emerald-500/10 shadow-sm rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:border-zinc-500 pointer-events-auto" style="left: 34%; top: 0%; width: 32%; height: 100%; display: none;">
                                <div class="absolute -top-6 left-0 bg-emerald-600 text-[10px] font-bold text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>📱 9:16 IRL Bildausschnitt</span>
                                    <span class="text-fuchsia-200 text-2xs font-normal">(Festes 9:16 Vollbild)</span>
                                </div>
                                <div class="w-5 h-5 rounded-full border border-white/70 bg-emerald-500/60 pointer-events-none flex items-center justify-center">
                                    <span class="text-xs text-white font-black">↔</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Video Scrubber / Timeline Bar -->
                    <div class="bg-slate-950/90 border border-slate-800 rounded p-3 flex flex-col sm:flex-row items-center gap-3">
                        <div class="flex items-center gap-2">
                            <button onclick="seekCropVideo(-2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden zurück">⏪ -2s</button>
                            <button onclick="toggleCropVideoPlay()" id="crop-play-btn" class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-200 rounded-lg transition">⏯️ Pause</button>
                            <button onclick="seekCropVideo(2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden vor">⏩ +2s</button>
                        </div>
                        <input type="range" id="crop-time-slider" min="0" max="30" step="0.1" value="0" class="flex-1 accent-amber-500 cursor-pointer" oninput="onCropSliderInput(this.value)">
                        <span id="crop-time-display" class="text-xs font-mono font-bold text-slate-300 min-w-[90px] text-right">00:00 / 00:00</span>
                    </div>

                    <!-- Presets & Quick Action Toolbar (Split vs Single 9:16) -->
                    <div class="bg-slate-950/60 border border-slate-800/80 rounded p-3 space-y-2.5">
                        <!-- Toolbar für Split-Screen Modus -->
                        <div id="toolbar-split" class="space-y-2.5">
                            <div class="space-y-1.5">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="text-xs font-bold text-emerald-400 min-w-[100px]">📷 Cam-Position:</span>
                                    <button onclick="applyPreset('cam_br')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Unten Rechts</button>
                                    <button onclick="applyPreset('cam_tl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Oben Links</button>
                                    <button onclick="applyPreset('cam_tr')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Oben Rechts</button>
                                    <button onclick="applyPreset('cam_bl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Unten Links</button>
                                    <button onclick="detectFacecamInCropModal()" id="btn-crop-detect" class="px-3 py-1 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 hover:text-white text-xs font-bold rounded-lg transition shadow flex items-center gap-1">
                                         KI Auto-Erkennen
                                    </button>
                                    <button type="button" onclick="switchCropMode('single_916')" id="btn-crop-toggle-cam" class="px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition" title="Facecam entfernen und zu reinem 9:16 Vollbild (1 Rahmen) wechseln">
                                        🚫 Keine Cam (Vollbild / 1 Rahmen)
                                    </button>
                                </div>
                                <!-- Stufenlose Cam-Größenregelung mit festem 3:2 Seitenverhältnis -->
                                <div class="flex flex-wrap items-center gap-3 bg-slate-900/70 p-2.5 rounded border border-slate-800/80">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs font-bold text-emerald-400 min-w-[90px] flex items-center gap-1">
                                             Cam-Größe:
                                        </span>
                                        <input type="range" id="crop-cam-size-slider" min="200" max="1100" step="5" value="540" 
                                            class="w-36 sm:w-48 accent-emerald-500 cursor-pointer" 
                                            oninput="setCamPixelWidth(this.value)"
                                            title="Stufenlose Größenregelung (3:2 bleibt immer gesperrt)">
                                        <span id="crop-cam-size-display" class="font-mono text-xs text-emerald-300 font-bold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800/60 min-w-[95px] text-center shadow-inner">
                                            540 x 360 px
                                        </span>
                                    </div>
                                    <div class="flex items-center gap-1.5 ml-auto sm:ml-0">
                                        <span class="text-2xs text-slate-400">Schnellwahl:</span>
                                        <button type="button" onclick="setCamPixelWidth(420)" id="btn-size-small" class="px-2 py-0.5 bg-slate-800 hover:bg-emerald-900/50 border border-slate-700 hover:border-emerald-500 text-2xs rounded text-slate-200 transition">Kompakt (420px)</button>
                                        <button type="button" onclick="setCamPixelWidth(540)" id="btn-size-normal" class="px-2 py-0.5 bg-emerald-900/80 border border-emerald-500 text-2xs font-bold rounded text-emerald-200 shadow transition">Standard (540px)</button>
                                        <button type="button" onclick="setCamPixelWidth(680)" id="btn-size-large" class="px-2 py-0.5 bg-slate-800 hover:bg-emerald-900/50 border border-slate-700 hover:border-emerald-500 text-2xs rounded text-slate-200 transition">Groß (680px)</button>
                                        <span class="text-2xs text-slate-500 hidden md:inline ml-1">3:2 fest • Mausrad / Ecken ziehen</span>
                                    </div>
                                </div>
                                <div class="flex flex-wrap items-center gap-2 pt-1.5 border-t border-slate-800/60">
                                    <span class="text-xs font-semibold text-emerald-400 min-w-[100px] flex items-center gap-1">
                                         Snapchat-Filter:
                                    </span>
                                    <select id="crop-cam-filter-select" onchange="draw916Preview()" class="bg-slate-800 border border-slate-700 text-xs text-white rounded-lg px-2.5 py-1 focus:border-emerald-500 flex-1 max-w-sm">
                                        {% for f_key, f_label in cam_filters.items() %}
                                        <option value="{{ f_key }}">{{ f_label }}</option>
                                        {% endfor %}
                                    </select>
                                </div>
                            </div>

                            <!-- Gameplay-Bereich: Position & Stufenlose Größe mit festem 9:10 Seitenverhältnis -->
                            <div class="space-y-2 pt-2 border-t border-slate-800/80">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="text-xs font-bold text-sky-400 min-w-[100px] flex items-center gap-1">
                                         Game-Position:
                                    </span>
                                    <button onclick="applyPreset('game_center')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">Mitte (Zentriert)</button>
                                    <button onclick="applyPreset('game_left')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">⬅️ Links</button>
                                    <button onclick="applyPreset('game_right')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">➡️ Rechts</button>
                                </div>
                                <div class="flex flex-wrap items-center gap-3 bg-slate-900/70 p-2.5 rounded border border-slate-800/80">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs font-bold text-sky-400 min-w-[90px] flex items-center gap-1">
                                             Game-Größe:
                                        </span>
                                        <input type="range" id="crop-game-size-slider" min="360" max="1200" step="5" value="972" 
                                            class="w-36 sm:w-48 accent-sky-500 cursor-pointer" 
                                            oninput="setGamePixelWidth(this.value)"
                                            title="Stufenlose Größenregelung (9:10 bleibt immer gesperrt)">
                                        <span id="crop-game-size-display" class="font-mono text-xs text-sky-300 font-bold bg-sky-950/80 px-2 py-0.5 rounded border border-sky-800/60 min-w-[95px] text-center shadow-inner">
                                            972 x 1080 px
                                        </span>
                                    </div>
                                    <div class="flex items-center gap-1.5 ml-auto sm:ml-0">
                                        <span class="text-2xs text-slate-400">Schnellwahl:</span>
                                        <button type="button" onclick="setGamePixelWidth(648)" id="btn-game-size-small" class="px-2 py-0.5 bg-slate-800 hover:bg-sky-900/50 border border-slate-700 hover:border-sky-500 text-2xs rounded text-slate-200 transition">Zoom (648px)</button>
                                        <button type="button" onclick="setGamePixelWidth(810)" id="btn-game-size-medium" class="px-2 py-0.5 bg-slate-800 hover:bg-sky-900/50 border border-slate-700 hover:border-sky-500 text-2xs rounded text-slate-200 transition">Mittel (810px)</button>
                                        <button type="button" onclick="setGamePixelWidth(972)" id="btn-game-size-max" class="px-2 py-0.5 bg-sky-900/80 border border-sky-500 text-2xs font-bold rounded text-sky-200 shadow transition">Voll (972px)</button>
                                        <span id="crop-game-hint-text" class="text-2xs text-slate-500 hidden md:inline ml-1">9:10 fest (Split) • Mausrad / Ecken ziehen</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Toolbar für Reines 9:16 IRL Vollbild -->
                        <div id="toolbar-single" class="hidden flex flex-wrap items-center gap-2.5">
                            <span class="text-xs font-bold text-emerald-400 min-w-[110px]">📱 9:16 Vollbild:</span>
                            <button type="button" onclick="applyPreset('single_center')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">Mitte (Zentriert)</button>
                            <button type="button" onclick="applyPreset('single_left')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">⬅️ Links</button>
                            <button type="button" onclick="applyPreset('single_right')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">➡️ Rechts</button>
                            <button type="button" onclick="switchCropMode('split')" class="px-3 py-1.5 bg-emerald-950/90 hover:bg-emerald-900 border border-emerald-600/80 text-xs font-bold rounded-lg text-emerald-300 hover:text-white transition flex items-center gap-1.5 shadow" title="Zurück zu 2 Rahmen (Facecam oben + Gameplay unten)">
                                <span>✂️</span> Facecam hinzufügen (Split-Screen)
                            </button>
                            <span class="text-2xs text-zinc-400 ml-auto bg-zinc-800 px-2 py-1 rounded border border-zinc-700">1 Rahmen (608x1080 px Vollbild)</span>
                        </div>
                    </div>
                </div>

                <!-- Right Column: 9:16 Live Smartphone Mockup Preview (4 cols) -->
                <div class="lg:col-span-4 flex flex-col items-center justify-between bg-slate-950/70 border border-slate-800 rounded-lg p-4">
                    <div class="text-center mb-2">
                        <span class="text-xs font-bold uppercase tracking-wider text-amber-400 block">Live 9:16 Vorschau</span>
                        <span class="text-2xs text-slate-400">Aktualisiert in Echtzeit beim Verschieben</span>
                    </div>

                    <!-- Smartphone Bezel Mockup -->
                    <div class="relative bg-slate-950 p-3 rounded-[38px] border-4 border-slate-700 shadow-2xl flex flex-col items-center">
                        <!-- Top Notch -->
                        <div class="w-16 h-3 bg-slate-800 rounded-full mb-2"></div>
                        <!-- Canvas Screen (270x480 -> 9:16) -->
                        <canvas id="crop-preview-canvas" width="270" height="480" class="w-[225px] h-[400px] bg-black rounded-[22px] overflow-hidden shadow-inner border border-slate-800"></canvas>
                        <!-- Bottom Bar -->
                        <div class="w-24 h-1 bg-slate-700 rounded-full mt-2"></div>
                    </div>

                    <!-- Coordinates Readout & Info -->
                    <div class="mt-3 text-center w-full">
                        <div id="crop-coords-readout" class="text-2xs font-mono text-slate-400 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800 truncate">
                            Cam: 480x360 • Game: 972x1080
                        </div>
                    </div>
                </div>

            </div>

            <!-- Footer Action Buttons -->
            <div class="flex flex-col sm:flex-row justify-between items-center p-4 border-t border-slate-800 bg-slate-950/80 gap-3">
                <button onclick="closeCropModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded transition">
                    Abbrechen
                </button>
                <div class="flex items-center gap-2">
                    <button onclick="saveCropCoordinates(false)" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-bold text-xs rounded transition">
                        Nur Speichern
                    </button>
                    <button onclick="saveCropCoordinates(true)" class="px-5 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center gap-2 shadow-sm">
                        <svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/></svg> Zuschnitt speichern & Jetzt Rendern
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script src="/app.js"></script>
</body>
</html>
"""


@app.route("/app.js")
def serve_app_js():
    import os
    from flask import send_file
    ui_app_js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.js")
    return send_file(ui_app_js, mimetype="application/javascript")

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
            "created_ago": created_ago,
            "created_full": created_full
        })

    streamer_counts = {}
    for c in ready_clips:
        st = c["streamer"]
        streamer_counts[st] = streamer_counts.get(st, 0) + 1

    account_status = account_manager.get_status()
    all_streamers = get_streamers()
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
        "account_status": account_status,
        "streamers": all_streamers,
        "streamer_counts": streamer_counts,
        "cam_filters": AVAILABLE_CAM_FILTERS,
        "initial_logs": initial_logs,
        "current_status": current_status,
        "current_task": current_task,
        "is_running": is_running,
    }

@app.route("/")
def index():
    d = get_dashboard_dict()
    return render_template_string(HTML_DASHBOARD, **d)

@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(get_dashboard_dict())

@app.route("/api/status")
def get_status():
    return jsonify(status_manager.get_state())

@app.route("/api/run", methods=["POST"])
def trigger_run_api():
    """Startet das Suchen & Herunterladen auf Twitch."""
    if not status_manager.get_state().get("is_running", False):
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

        thread = threading.Thread(target=run_harvest_background, daemon=True)
        thread.start()
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
    if not status_manager.get_state().get("is_running", False):
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

@app.route("/raw-video/<clip_id>")
def serve_raw_video(clip_id):
    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    if raw_path.exists():
        return send_file(raw_path, mimetype="video/mp4")
    return "Rohdatei nicht gefunden", 404

@app.route("/thumbnail/<clip_id>")
def serve_thumbnail(clip_id):
    """Liefert ein gecachtes JPEG-Vorschaubild (Poster) für das Video."""
    thumb_dir = DATA_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{clip_id}.jpg"

    if not thumb_path.exists():
        video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
        if not video_path.exists():
            video_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        
        if video_path.exists():
            try:
                cap = cv2.VideoCapture(str(video_path))
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                    ret, frame = cap.read()
                if ret:
                    cv2.imwrite(str(thumb_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                cap.release()
            except Exception:
                pass

    if thumb_path.exists():
        response = send_file(thumb_path, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    return "", 404

@app.route("/video/<clip_id>")
def serve_video(clip_id):
    video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if video_path.exists():
        return send_file(video_path, mimetype="video/mp4")
    return "Video nicht gefunden", 404

@app.route("/download/short/<clip_id>")
def download_short_route(clip_id):
    """Ermöglicht den direkten Download des gerenderten 9:16 Shorts in HQ."""
    video_path = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
    if not video_path.exists():
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
    raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
    if raw_path.exists():
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

    try:
        res = subprocess.run(
            [sys.executable, "-m", "src.save_dialog", filename, str(init_dir), f"HQ Video speichern unter ({streamer})"],
            capture_output=True,
            timeout=180
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Dialog-Fehler: {e}"}), 500

    if res.returncode != 0 or not res.stdout:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    selected_path_str = res.stdout.decode("utf-8", errors="replace").strip()
    if not selected_path_str:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    dest_path = Path(selected_path_str)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, dest_path)
        set_last_export_dir(dest_path.parent)

        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer.exe", f"/select,{str(dest_path)}"])
            except Exception:
                pass

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

    try:
        res = subprocess.run(
            [sys.executable, "-m", "src.save_dialog", filename, str(init_dir), f"Rohdatei speichern unter ({streamer})"],
            capture_output=True,
            timeout=180
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Dialog-Fehler: {e}"}), 500

    if res.returncode != 0 or not res.stdout:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    selected_path_str = res.stdout.decode("utf-8", errors="replace").strip()
    if not selected_path_str:
        return jsonify({"success": False, "cancelled": True, "message": "Export abgebrochen"})

    dest_path = Path(selected_path_str)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, dest_path)
        set_last_export_dir(dest_path.parent)

        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer.exe", f"/select,{str(dest_path)}"])
            except Exception:
                pass

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
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", f"/select,{str(dest_path)}"])
        except Exception:
            pass

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

    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", f"/select,{str(dest_path)}"])
        except Exception:
            pass

    return jsonify({"success": True, "filename": filename, "path": str(dest_path), "folder": str(dest_path.parent)})

@app.route("/save/<clip_id>", methods=["POST"])
def save_clip(clip_id):
    action = request.form.get("action")
    sticker_text = request.form.get("sticker_text", "").strip()
    title = request.form.get("title", "").strip()
    sub_position = request.form.get("sub_position", "bottom")
    layout_mode = request.form.get("layout_mode", "auto")
    cam_filter = request.form.get("cam_filter", "none")
    edited_transcript = request.form.get("transcript", "").strip()

    meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
    meta = {}
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    meta["sticker_text"] = sticker_text
    meta["title"] = title
    meta["sub_position"] = sub_position
    meta["layout_mode"] = layout_mode
    meta["cam_filter"] = cam_filter
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    update_clip_status(clip_id, "ready", ai_title=title)

    if action == "delete":
        cancel_active_render(clip_id)
        short_file = SHORTS_OUTPUT_DIR / f"short_{clip_id}.mp4"
        if short_file.exists():
            short_file.unlink()
        update_clip_status(clip_id, "deleted")
        return redirect(url_for("index"))

    elif action == "publish_now":
        publish_clip_now(clip_id)
        return redirect(url_for("index"))

    elif action == "schedule":
        # Einzelnen Clip in Zeitplan einreihen
        schedule_single_clip(clip_id)
        return redirect(url_for("index"))

    elif action == "rerender":
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

            composer.render_short(
                raw_video_path=raw_path,
                clip_id=clip_id,
                ass_subtitle_path=active_sub_path,
                header_sticker_text=sticker_text,
                layout_mode=layout_mode,
                custom_crops=meta.get("custom_crops"),
                cam_filter=cam_filter,
                on_progress=on_rerender_progress
            )
            status_manager.reset_progress()
            status_manager.set_task("idle", f"Neu-Rendern von '{title}' fertiggestellt.")

    return redirect(url_for("index"))

def schedule_single_clip(clip_id: str, interval_minutes: int = None):
    """Reiht einen Clip in die automatische Veröffentlichungs-Warteschlange ein."""
    with schedule_lock:
        if interval_minutes is None:
            interval_minutes = account_manager.get_status().get("publishing_interval", 30)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(scheduled_publish_at) as max_time FROM clips WHERE status = 'scheduled'")
            row = cursor.fetchone()
            now = datetime.now()
            
            last_time = None
            if row and row["max_time"]:
                try:
                    parsed = datetime.strptime(row["max_time"], "%Y-%m-%d %H:%M:%S")
                    if parsed > now:
                        last_time = parsed
                except Exception:
                    pass

            if last_time:
                next_time = last_time + timedelta(minutes=interval_minutes)
            else:
                next_time = now + timedelta(minutes=interval_minutes)

            time_str = next_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("UPDATE clips SET status = 'scheduled', scheduled_publish_at = ? WHERE clip_id = ?", (time_str, clip_id))
            conn.commit()

        status_manager.log(f"Clip {clip_id} für automatische Veröffentlichung eingeplant um {time_str} (+{interval_minutes}m).")

@app.route("/schedule/cancel/<clip_id>", methods=["POST"])
def cancel_schedule_route(clip_id):
    """Nimmt einen Clip aus dem Zeitplan zurück ins Studio."""
    update_clip_status(clip_id, "ready", scheduled_publish_at=None)
    status_manager.log(f"Zeitplan für Clip {clip_id} abgebrochen, zurück im Studio.")
    return redirect(url_for("index"))

@app.route("/schedule/publish-now/<clip_id>", methods=["POST"])
def publish_now_route(clip_id):
    """Veröffentlicht einen eingeplanten Clip sofort."""
    publish_clip_now(clip_id)
    return redirect(url_for("index"))

@app.route("/api/schedule-all", methods=["POST"])
def schedule_all_route():
    """Reiht alle fertigen Studio-Clips gestaffelt nach Intervall ein."""
    interval = int(request.form.get("interval_minutes", 30))
    account_manager.set_publishing_interval(interval)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clip_id FROM clips WHERE status IN ('ready', 'completed') ORDER BY rowid ASC")
        clips = cursor.fetchall()

    for c in clips:
        schedule_single_clip(c["clip_id"], interval_minutes=interval)

    return redirect(url_for("index"))

@app.route("/api/schedule/set-interval", methods=["POST"])
def set_schedule_interval():
    interval = int(request.form.get("interval_minutes", 30))
    account_manager.set_publishing_interval(interval)
    status_manager.log(f"Standard-Veröffentlichungsintervall auf {interval} Minuten gesetzt.")
    return redirect(url_for("index"))

# ==================== KONTEN-VERKNÜPFUNG ENDPOINTS ====================

@app.route("/api/accounts/youtube/save-secrets", methods=["POST"])
def youtube_save_secrets():
    file = request.files.get("secrets_file")
    if file and file.filename:
        content = file.read().decode("utf-8", errors="replace")
        if account_manager.save_youtube_secrets(content):
            status_manager.log("YouTube client_secrets.json erfolgreich hochgeladen.")
        else:
            status_manager.log("Fehler beim Verarbeiten der client_secrets.json.")
    return redirect(url_for("index"))

@app.route("/api/accounts/youtube/save-credentials", methods=["POST"])
def youtube_save_credentials():
    cid = request.form.get("client_id", "").strip()
    secret = request.form.get("client_secret", "").strip()
    if cid and secret:
        if account_manager.save_youtube_client_credentials(cid, secret):
            status_manager.log("YouTube Client-ID & Secret erfolgreich gespeichert.")
        else:
            status_manager.log("Fehler beim Speichern der YouTube-Zugangsdaten.")
    return redirect(url_for("index"))

@app.route("/api/accounts/status")
def accounts_status():
    return jsonify(account_manager.get_status())

@app.route("/api/accounts/youtube/authorize", methods=["GET", "POST"])
def youtube_authorize():
    res = account_manager.authorize_youtube()
    status_manager.log(res.get("message", "YouTube Autorisierung ausgeführt."))
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.method == "POST":
        return jsonify(res)
    if res.get("success") and res.get("auth_url"):
        return redirect(res["auth_url"])
    return redirect(url_for("index"))

@app.route("/api/accounts/youtube/disconnect", methods=["POST"])
def youtube_disconnect():
    account_manager.disconnect_youtube()
    status_manager.log("YouTube-Verbindung getrennt.")
    return redirect(url_for("index"))

@app.route("/api/accounts/youtube/settings", methods=["POST"])
def youtube_settings():
    privacy = request.form.get("privacy_status", "private")
    account_manager.update_youtube_settings(enabled=True, privacy_status=privacy)
    status_manager.log(f"YouTube Sichtbarkeit auf '{privacy}' gesetzt.")
    return redirect(url_for("index"))

@app.route("/api/accounts/tiktok/browser-login", methods=["POST"])
def tiktok_browser_login():
    res = start_tiktok_browser_login()
    return jsonify(res)

@app.route("/api/accounts/tiktok/browser-login/status")
def tiktok_browser_login_status():
    return jsonify(get_browser_login_status())

@app.route("/api/accounts/tiktok/save-session", methods=["POST"])
def tiktok_save_session():
    sid = request.form.get("session_id", "").strip()
    mode = request.form.get("upload_mode", "draft")
    if sid:
        account_manager.save_tiktok_session(session_id=sid, upload_mode=mode, enabled=True)
        status_manager.log("TikTok Session-ID erfolgreich gespeichert.")
    return redirect(url_for("index"))

@app.route("/api/accounts/tiktok/disconnect", methods=["POST"])
def tiktok_disconnect():
    account_manager.disconnect_tiktok()
    status_manager.log("TikTok-Verbindung getrennt.")
    return redirect(url_for("index"))

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

    return jsonify({
        "clip_id": clip_id,
        "streamer": clip["streamer"] if clip else meta.get("streamer", ""),
        "title": (clip["ai_title"] or clip["original_title"] if clip else "") or meta.get("title", ""),
        "sticker_text": meta.get("sticker_text", ""),
        "sub_position": meta.get("sub_position", "bottom"),
        "layout_mode": meta.get("layout_mode", "auto"),
        "custom_crops": meta.get("custom_crops", None),
        "cam_filter": meta.get("cam_filter", "none"),
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
    
    if "title" in data and data["title"]:
        meta["title"] = data["title"]
    if "sticker_text" in data and data["sticker_text"]:
        meta["sticker_text"] = data["sticker_text"]
    if "sub_position" in data and data["sub_position"]:
        meta["sub_position"] = data["sub_position"]
    if "cam_filter" in data:
        meta["cam_filter"] = data["cam_filter"]

    with open(meta_file, "w", encoding="utf-8") as mf:
        json.dump(meta, mf, indent=2, ensure_ascii=False)

    update_clip_status(clip_id, "ready", ai_title=meta.get("title"))

    if render_now:
        cancel_active_render(clip_id)
        raw_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
        words_path = RAW_CLIPS_DIR / f"{clip_id}_words.json"
        title = meta.get("title") or clip_id
        sticker_text = meta.get("sticker_text") or title
        sub_position = meta.get("sub_position", "bottom")

        def render_worker():
            try:
                status_manager.set_task("rendering", f"Rendere Short mit Zuschnitt: '{title}'...", clip_title=title)
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

                    if "transcript" in data and data["transcript"].strip():
                        ed_transcript = data["transcript"].strip()
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
                    layout_mode=layout_mode,
                    custom_crops=custom_crops,
                    cam_filter=meta.get("cam_filter", "none"),
                    on_progress=on_progress
                )
                status_manager.reset_progress()
                if rendered_path and rendered_path.exists():
                    status_manager.set_task("idle", f"Zuschnitt-Rendering für '{title}' fertiggestellt.")
                    update_clip_status(clip_id, "ready", rendered_path=str(rendered_path), ai_title=title)
            except Exception as e:
                status_manager.reset_progress()
                status_manager.log(f"Fehler beim Rendern von {clip_id}: {e}")

        t = threading.Thread(target=render_worker, daemon=True)
        t.start()
        return jsonify({"success": True, "message": "Rendering mit manuellem Zuschnitt gestartet"})

    return jsonify({"success": True, "message": "Zuschnitt gespeichert"})

def start_studio(port: int = 5000):
    print("\n" + "="*70)
    print(f"  CLIP-FARMING STUDIO GESTARTET!")
    print(f"  👉 Öffne im Browser: http://localhost:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

if __name__ == "__main__":
    start_studio()
