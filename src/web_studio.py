import os
import sys
import json
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
from src.database import get_db_connection, update_clip_status
from src.video.layout import VideoComposer, cancel_active_render, generate_thumbnail
from src.video.filters import AVAILABLE_CAM_FILTERS
from src.uploaders.youtube import YouTubeUploader
from src.uploaders.tiktok import TikTokUploader
from src.uploaders.account_manager import account_manager
from src.uploaders.browser_login import start_tiktok_browser_login, get_browser_login_status
from src.state import status_manager
from src.version import APP_VERSION, GITHUB_REPO
from src.updater import check_for_updates, download_and_run_installer

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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { 
            background-color: #090d16; 
            color: #f1f5f9; 
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        :focus-visible { outline: 2px solid #f59e0b; outline-offset: 2px; }
        @media (prefers-reduced-motion: reduce) {
            *, ::before, ::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }
        .tab-btn.active { border-bottom-color: #f59e0b; color: #ffffff; font-weight: 600; }
        .tab-content.hidden { display: none !important; }
        #preview-modal.hidden, #streamer-modal.hidden, #crop-modal.hidden, #settings-modal.hidden, #streamer-config-modal.hidden {
            display: none !important;
            pointer-events: none !important;
            visibility: hidden !important;
        }
        #preview-modal:not(.hidden), #streamer-modal:not(.hidden), #crop-modal:not(.hidden), #settings-modal:not(.hidden), #streamer-config-modal:not(.hidden) {
            display: flex !important;
            pointer-events: auto !important;
            visibility: visible !important;
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #090d16; }
        ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #334155; }
        #crop-stage-container {
            position: relative;
            width: 100%;
            aspect-ratio: 16 / 9;
            background: #000000;
            overflow: hidden;
            border-radius: 8px;
            min-height: 260px;
        }
        #crop-overlay-layer {
            position: absolute;
            inset: 0;
            pointer-events: none;
            width: 100%;
            height: 100%;
        }
        .crop-cam-handle, .crop-game-handle {
            position: absolute;
            width: 16px;
            height: 16px;
            border: 2px solid #0f172a;
            border-radius: 50%;
            box-shadow: 0 0 8px rgba(0,0,0,0.8);
            z-index: 30;
            transition: transform 0.15s;
            pointer-events: auto;
        }
        .crop-cam-handle:hover, .crop-game-handle:hover {
            transform: scale(1.3);
        }
    </style>
    <script>
        // Immediate Zero-Delay Handlers (execute on initial paint before any async script)
        function openStreamerModal() {
            if (typeof switchTab === 'function') {
                switchTab('streamers');
            } else if (window.switchTab) {
                window.switchTab('streamers');
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
        function openStreamerConfigModal(streamerName) {
            if (window.__realOpenStreamerConfigModal) {
                return window.__realOpenStreamerConfigModal(streamerName);
            }
            var m = document.getElementById('streamer-config-modal');
            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
                if (window.loadStreamerConfigIntoForm) window.loadStreamerConfigIntoForm(streamerName);
            }
        }
        function closeStreamerConfigModal() {
            var m = document.getElementById('streamer-config-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }
        function saveStreamerConfig(event) {
            if (window.__realSaveStreamerConfig) return window.__realSaveStreamerConfig(event);
            if (window.saveStreamerConfig && window.saveStreamerConfig !== saveStreamerConfig) return window.saveStreamerConfig(event);
        }
        function loadSampleClipDirect(name, btnEl) {
            if (!name) return;
            if (window.__realLoadSampleClipDirect) return window.__realLoadSampleClipDirect(name, btnEl);
            var oldHtml = btnEl ? btnEl.innerHTML : '';
            if (btnEl) {
                btnEl.disabled = true;
                btnEl.classList.add('opacity-70', 'cursor-not-allowed');
                btnEl.innerHTML = '<span class="inline-block w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mr-1"></span><span>Lade Test-Clip...</span>';
            }
            if (window.showToast) window.showToast('Lade Test-Clip für ' + name + ' von Twitch...', 'info');
            fetch('/api/streamers/' + encodeURIComponent(name) + '/sample-clip', { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.success && data.clip_id) {
                        closeStreamerConfigModal();
                        closeStreamerModal();
                        if (window.showToast) window.showToast('Test-Clip für ' + name + ' bereit! Rahmen jetzt anpassen.', 'success');
                        openCropModal(data.clip_id, name, data.title || ('Test-Clip Vorlage (' + name + ')'));
                    } else {
                        var err = (data && data.error) ? data.error : 'Konnte keinen Test-Clip laden';
                        if (window.showToast) window.showToast('Fehler: ' + err, 'error');
                        else alert('Fehler: ' + err);
                    }
                })
                .catch(function(err) {
                    if (window.showToast) window.showToast('Fehler: ' + err, 'error');
                    else alert('Fehler beim Laden des Test-Clips: ' + err);
                })
                .finally(function() {
                    if (btnEl) {
                        btnEl.disabled = false;
                        btnEl.classList.remove('opacity-70', 'cursor-not-allowed');
                        btnEl.innerHTML = oldHtml;
                    }
                });
        }
        window.loadSampleClipDirect = loadSampleClipDirect;
        function loadSampleClipForStreamer() {
            if (window.__realLoadSampleClipForStreamer) return window.__realLoadSampleClipForStreamer();
            var hiddenName = document.getElementById('cfg-streamer-hidden-name');
            var name = hiddenName ? hiddenName.value.trim() : '';
            if (!name) return;
            var spinner = document.getElementById('btn-sample-spinner');
            var btnText = document.getElementById('btn-sample-text');
            var btn = document.getElementById('btn-load-streamer-sample');
            if (spinner) spinner.classList.remove('hidden');
            if (btnText) btnText.innerText = 'Lade Test-Clip von Twitch herunter...';
            if (btn) {
                btn.disabled = true;
                btn.classList.add('opacity-60', 'cursor-not-allowed');
            }
            if (window.showToast) window.showToast('Lade Test-Clip für ' + name + '...', 'info');
            fetch('/api/streamers/' + encodeURIComponent(name) + '/sample-clip', { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.success && data.clip_id) {
                        closeStreamerConfigModal();
                        closeStreamerModal();
                        if (window.showToast) window.showToast('Test-Clip geladen! Rahmen anpassen.', 'success');
                        openCropModal(data.clip_id, name, data.title || ('Test-Clip Vorlage (' + name + ')'));
                    } else {
                        var err = (data && data.error) ? data.error : 'Konnte keinen Clip laden.';
                        if (window.showToast) window.showToast('Fehler: ' + err, 'error');
                        else alert('Fehler: ' + err);
                    }
                })
                .catch(function(err) {
                    if (window.showToast) window.showToast('Fehler: ' + err, 'error');
                    else alert('Fehler beim Laden: ' + err);
                })
                .finally(function() {
                    if (spinner) spinner.classList.add('hidden');
                    if (btnText) btnText.innerText = 'Test-Clip laden & Rahmen visuell einstellen';
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('opacity-60', 'cursor-not-allowed');
                    }
                });
        }
        window.loadSampleClipForStreamer = loadSampleClipForStreamer;
        function openSettingsModal() {
            if (window.openSettingsModal && window.openSettingsModal !== openSettingsModal) {
                return window.openSettingsModal();
            }
            var m = document.getElementById('settings-modal');
            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
            }
        }
        function closeSettingsModal() {
            if (window.closeSettingsModal && window.closeSettingsModal !== closeSettingsModal) {
                return window.closeSettingsModal();
            }
            var m = document.getElementById('settings-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }
        function switchTab(tabId) {
            if (!tabId) return;
            try {
                localStorage.setItem('clip_farming_active_tab', tabId);
            } catch(e) {}
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
            if (tabId === 'studio') {
                document.querySelectorAll('#studio-grid video').forEach(function(v) {
                    try {
                        if (v.paused && v.currentTime === 0) {
                            v.currentTime = 0.001;
                        }
                    } catch(e) {}
                });
            }
        }
        (function restoreActiveTabOnLoad() {
            function applySavedTab() {
                try {
                    var urlParams = new URLSearchParams(window.location.search);
                    var tabFromUrl = urlParams.get('tab') || window.location.hash.replace('#', '');
                    var savedTab = tabFromUrl || localStorage.getItem('clip_farming_active_tab');
                    if (savedTab && document.getElementById('tab-' + savedTab)) {
                        switchTab(savedTab);
                    }
                } catch(e) {}
            }
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', applySavedTab);
            } else {
                applySavedTab();
            }
        })();
                function openRawPreviewFromRow(row) {
            if (!row) return;
            var d = row.dataset;
            openRawPreview(d.clipId, d.streamer, d.title, d.views, d.duration, d.createdAgo, d.createdFull);
        }
        window.openRawPreviewFromRow = openRawPreviewFromRow;

        function openCropModalFromButton(btn) {
            if (!btn) return;
            var d = btn.dataset;
            openCropModal(d.clipId, d.streamer, d.title);
        }
        window.openCropModalFromButton = openCropModalFromButton;

        function startStudioVideoPlay(clipId, overlay) {
            if (overlay) overlay.style.display = 'none';
            var vid = document.getElementById('studio-video-' + clipId);
            if (vid) {
                vid.play().catch(function() {});
            }
        }
        window.startStudioVideoPlay = startStudioVideoPlay;

        var currentCropClipId = '';
        var currentCropStreamer = '';
        var currentCropTitle = '';
        var currentCropMode = 'split'; // 'split' oder 'single_916'
        var cropState = {
            cam: { x: 0.68, y: 0.58, w: 0.28, h: 0.35, enabled: true },
            game: { x: 0.24, y: 0.0, w: 0.51, h: 1.0, enabled: true },
            single: { x: 0.34, y: 0.0, w: 0.316, h: 1.0, enabled: true }
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

            // 1. Sofortiges Vorladen des 16:9 Rohbildes als sichtbarer Hintergrund (verhindert schwarzen Kasten)
            var stageImg = document.getElementById('crop-stage-img');
            if (stageImg) {
                stageImg.src = '/thumbnail/raw/' + encodeURIComponent(clipId) + '?t=' + Date.now();
                stageImg.onload = function() {
                    draw916Preview();
                };
            }

            // 2. Fallback-Image für den rechten 9:16 Preview Canvas
            cropFallbackImg.src = '/thumbnail/raw/' + encodeURIComponent(clipId) + '?t=' + Date.now();
            cropFallbackImg.onload = function() {
                draw916Preview();
            };

            // 3. Setup Video-Element für Zeitleiste & Playback
            var vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.poster = '/thumbnail/raw/' + encodeURIComponent(clipId);
                vid.muted = true;
                vid.src = '/raw-video/' + encodeURIComponent(clipId);
                vid.onloadedmetadata = function() {
                    try {
                        vid.currentTime = Math.min(0.5, (vid.duration || 1) / 2);
                        var playPromise = vid.play();
                        if (playPromise !== undefined) {
                            playPromise.then(function() {
                                vid.pause();
                                draw916Preview();
                            }).catch(function() {
                                draw916Preview();
                            });
                        }
                    } catch(e) {
                        draw916Preview();
                    }
                };
                vid.onseeked = function() {
                    draw916Preview();
                };
                vid.load();
            }

            // 4. Default Boxen sofort anzeigen
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');
            draw916Preview();

            // 5. Gespeicherte Schnitt-Metadaten laden
            fetch('/api/clip/' + encodeURIComponent(clipId) + '/meta')
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
            currentCropMode = (mode === 'single_916') ? 'single_916' : 'split';
            var btnSplit = document.getElementById('btn-mode-split');
            var btnSingle = document.getElementById('btn-mode-single');
            var tbSplit = document.getElementById('toolbar-split');
            var tbSingle = document.getElementById('toolbar-single');
            var boxCam = document.getElementById('crop-box-cam');
            var boxGame = document.getElementById('crop-box-game');
            var boxSingle = document.getElementById('crop-box-single');

            if (currentCropMode === 'single_916') {
                if (boxCam) boxCam.style.setProperty('display', 'none', 'important');
                if (boxGame) boxGame.style.setProperty('display', 'none', 'important');
                if (boxSingle) boxSingle.style.setProperty('display', 'flex', 'important');

                if (tbSplit) tbSplit.style.setProperty('display', 'none', 'important');
                if (tbSingle) {
                    tbSingle.classList.remove('hidden');
                    tbSingle.style.setProperty('display', 'flex', 'important');
                }

                if (btnSplit) {
                    btnSplit.className = "flex-1 py-2 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white border border-slate-700 cursor-pointer";
                }
                if (btnSingle) {
                    btnSingle.className = "flex-1 py-2 px-3 rounded text-xs font-bold transition flex items-center justify-center gap-2 bg-emerald-600 text-white shadow-lg border border-emerald-400 cursor-pointer";
                }
                updateBoxDom('single');
            } else {
                if (boxCam) boxCam.style.setProperty('display', 'flex', 'important');
                if (boxGame) boxGame.style.setProperty('display', 'flex', 'important');
                if (boxSingle) boxSingle.style.setProperty('display', 'none', 'important');

                if (tbSplit) {
                    tbSplit.classList.remove('hidden');
                    tbSplit.style.setProperty('display', 'block', 'important');
                }
                if (tbSingle) tbSingle.style.setProperty('display', 'none', 'important');

                if (btnSplit) {
                    btnSplit.className = "flex-1 py-2 px-3 rounded text-xs font-bold transition flex items-center justify-center gap-2 bg-amber-500 text-zinc-950 shadow-lg border border-amber-400 cursor-pointer";
                }
                if (btnSingle) {
                    btnSingle.className = "flex-1 py-2 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white border border-slate-700 cursor-pointer";
                }
                updateBoxDom('cam');
                updateBoxDom('game');
            }
            draw916Preview();
        }
        window.switchCropMode = switchCropMode;

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

            // Strict sanitization against NaN / undefined / collapse
            if (typeof s.x !== 'number' || isNaN(s.x)) s.x = (type === 'cam' ? 0.68 : (type === 'game' ? 0.24 : 0.34));
            if (typeof s.y !== 'number' || isNaN(s.y)) s.y = (type === 'cam' ? 0.58 : 0.0);
            if (typeof s.w !== 'number' || isNaN(s.w) || s.w < 0.05) s.w = (type === 'cam' ? 0.28 : (type === 'game' ? 0.51 : 0.316));
            if (typeof s.h !== 'number' || isNaN(s.h) || s.h < 0.05) s.h = (type === 'cam' ? 0.35 : 1.0);

            // Clamp bounds
            s.x = Math.max(0, Math.min(1 - s.w, s.x));
            s.y = Math.max(0, Math.min(1 - s.h, s.y));

            box.style.left = (s.x * 100) + '%';
            box.style.top = (s.y * 100) + '%';
            box.style.width = (s.w * 100) + '%';
            box.style.height = (s.h * 100) + '%';

            var readout = document.getElementById('crop-coords-readout');
            if (readout) {
                if (currentCropMode === 'single_916') {
                    readout.innerText = 'Vollbild 9:16: ' + Math.round(cropState.single.w * 1920) + 'x1080 px (1 Rahmen • Keine Cam)';
                } else {
                    var camW = Math.round(cropState.cam.w * 1920);
                    var camH = Math.round(cropState.cam.h * 1080);
                    var gameW = Math.round(cropState.game.w * 1920);
                    var gameH = Math.round(cropState.game.h * 1080);
                    readout.innerText = 'Cam: ' + camW + 'x' + camH + ' • Game: ' + gameW + 'x' + gameH + ' (2 Rahmen)';
                }
            }
        }

        function draw916Preview() {
            var canvas = document.getElementById('crop-preview-canvas');
            if (!canvas) return;
            var ctx = canvas.getContext('2d');
            var vid = document.getElementById('crop-stage-video');
            var stageImg = document.getElementById('crop-stage-img');
            
            var source = (vid && vid.readyState >= 2) ? vid : 
                         ((stageImg && stageImg.complete && stageImg.naturalWidth > 0) ? stageImg : 
                         ((cropFallbackImg && cropFallbackImg.complete && cropFallbackImg.naturalWidth > 0) ? cropFallbackImg : null));

            ctx.fillStyle = '#0b0f19';
            ctx.fillRect(0, 0, 270, 480);

            if (!source) {
                ctx.fillStyle = '#1e293b';
                ctx.fillRect(8, 8, 254, 464);
                ctx.fillStyle = '#94a3b8';
                ctx.font = 'bold 12px system-ui, sans-serif';
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
                // 1. Gameplay in lower portion
                var gx = cropState.game.x * vw;
                var gy = cropState.game.y * vh;
                var gw = Math.max(16, cropState.game.w * vw);
                var gh = Math.max(16, cropState.game.h * vh);

                try {
                    ctx.drawImage(source, gx, gy, gw, gh, 0, 160, 270, 320);
                } catch(e) {}

                // 2. Facecam in top portion
                var cx = cropState.cam.x * vw;
                var cy = cropState.cam.y * vh;
                var cw = Math.max(16, cropState.cam.w * vw);
                var ch = Math.max(16, cropState.cam.h * vh);

                try {
                    ctx.drawImage(source, cx, cy, cw, ch, 0, 0, 270, 160);
                } catch(e) {}

                // Trennlinie zwischen Facecam und Gameplay
                ctx.strokeStyle = '#38bdf8';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.moveTo(0, 160);
                ctx.lineTo(270, 160);
                ctx.stroke();
            }

            // Hook Sticker simulation (title badge)
            if (currentCropTitle) {
                ctx.save();
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.7)';
                ctx.shadowBlur = 6;
                var stickerW = 230;
                var stickerH = 26;
                var stickerY = (currentCropMode === 'split') ? 172 : 110;
                var stickerX = (270 - stickerW) / 2;
                ctx.fillRect(stickerX, stickerY, stickerW, stickerH);
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 10px system-ui, sans-serif';
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

        function saveAsDefaultStreamerLayout() {
            if (window.__realSaveAsDefaultStreamerLayout) {
                return window.__realSaveAsDefaultStreamerLayout();
            }
            if (!currentCropStreamer) {
                alert('Kein Streamer ermittelt.');
                return;
            }
            var payload = {
                mode: currentCropMode === 'single_916' ? 'single_916' : 'split',
                cam: {
                    x_pct: cropState.cam.x,
                    y_pct: cropState.cam.y,
                    w_pct: cropState.cam.w,
                    h_pct: cropState.cam.h,
                    enabled: cropState.cam.enabled
                },
                game: {
                    x_pct: cropState.game.x,
                    y_pct: 0,
                    w_pct: cropState.game.w,
                    h_pct: 1.0,
                    enabled: true
                }
            };
            fetch('/api/streamers/' + encodeURIComponent(currentCropStreamer) + '/layout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ layout: currentCropMode === 'single_916' ? 'single_916' : 'custom', custom_crops: payload })
            }).then(function() {
                if (window.showToast) window.showToast('✓ Standard-Layout für ' + currentCropStreamer + ' gespeichert!', 'success');
                else alert('Standard-Layout gespeichert!');
            }).catch(function(err) {
                alert('Fehler beim Speichern: ' + err);
            });
        }

        function detectFacecamInCropModal() {
            if (!currentCropClipId) return;
            var badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = 'KI scannt Facecam...';
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
                    if (c.single && c.single.x_pct !== undefined && c.single.x_pct > 0) cropState.single.x = c.single.x_pct;
                } else {
                    currentCropMode = 'split';
                    if (c.cam) {
                        if (c.cam.x_pct !== undefined) cropState.cam.x = c.cam.x_pct;
                        if (c.cam.y_pct !== undefined) cropState.cam.y = c.cam.y_pct;
                        if (c.cam.w_pct !== undefined && c.cam.w_pct > 0.05) cropState.cam.w = c.cam.w_pct;
                        if (c.cam.h_pct !== undefined && c.cam.h_pct > 0.05) cropState.cam.h = c.cam.h_pct;
                        if (c.cam.enabled !== undefined) cropState.cam.enabled = c.cam.enabled;
                    }
                    if (c.game) {
                        if (c.game.x_pct !== undefined) cropState.game.x = c.game.x_pct;
                        if (c.game.w_pct !== undefined && c.game.w_pct > 0.05) cropState.game.w = c.game.w_pct;
                    }
                }
            }
            if (!cropState.cam.w || cropState.cam.w < 0.05) cropState.cam.w = 540 / 1920;
            if (!cropState.cam.h || cropState.cam.h < 0.05) cropState.cam.h = 360 / 1080;
            if (!cropState.game.w || cropState.game.w < 0.05) cropState.game.w = 972 / 1920;
            if (!cropState.single.w || cropState.single.w < 0.05) cropState.single.w = 608 / 1920;
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

            document.querySelectorAll('.crop-game-handle').forEach(function(h) {
                h.addEventListener('pointerdown', function(e) {
                    onPointerDown(e, 'game', true, h.getAttribute('data-handle'));
                });
            });

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
                    var scaleDelta = (d.handle && d.handle.includes('r') ? dx : -dx);
                    var newW = Math.max(280 / 1920, Math.min(800 / 1920, d.initW + scaleDelta));
                    var newH = (newW * 1920 * (2 / 3)) / 1080;
                    cropState.cam.w = newW;
                    cropState.cam.h = newH;
                    if (cropState.cam.x + cropState.cam.w > 1) cropState.cam.x = 1 - cropState.cam.w;
                    if (cropState.cam.y + cropState.cam.h > 1) cropState.cam.y = 1 - cropState.cam.h;
                } else if (d.target === 'game') {
                    var scaleDelta = (d.handle && d.handle.includes('r') ? dx : -dx);
                    var newW = Math.max(480 / 1920, Math.min(1200 / 1920, d.initW + scaleDelta));
                    cropState.game.w = newW;
                    cropState.game.h = 1.0;
                    if (cropState.game.x + cropState.game.w > 1) cropState.game.x = 1 - cropState.game.w;
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
                    var err = (data && data.error) ? data.error : 'Konnte Speicher-Dialog nicht öffnen.';
                    showToast('Fehler: ' + err, 'error');
                }
            } catch (err) {
                console.warn('Export endpoint failed:', err);
                showToast('Fehler beim Exportieren: ' + err, 'error');
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
                    var err = (data && data.error) ? data.error : 'Konnte Speicher-Dialog nicht öffnen.';
                    showToast('Fehler: ' + err, 'error');
                }
            } catch (err) {
                console.warn('Export raw endpoint failed:', err);
                showToast('Fehler beim Exportieren: ' + err, 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origContent;
                }
            }
        }

                var currentUpdateData = null;

        function checkForUpdates() {
            fetch('/api/check-update')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.update_available) {
                        currentUpdateData = data;
                        var badge = document.getElementById('update-badge');
                        var badgeV = document.getElementById('update-badge-v');
                        if (badge && badgeV) {
                            badgeV.innerText = 'v' + data.latest_version;
                            badge.style.display = 'inline-flex';
                        }
                    }
                })
                .catch(function() {});
        }

        function openUpdateModal() {
            if (!currentUpdateData) return;
            var m = document.getElementById('update-modal');
            var vEl = document.getElementById('modal-update-ver');
            var notesEl = document.getElementById('modal-update-notes-body');
            var ghLink = document.getElementById('modal-github-link');

            if (vEl) vEl.innerText = 'v' + currentUpdateData.latest_version;
            if (notesEl) {
                var notes = currentUpdateData.release_notes || 'Neue Fehlerbehebungen & Leistungsoptimierungen.';
                notesEl.innerText = notes;
            }
            if (ghLink && currentUpdateData.download_url) {
                ghLink.href = 'https://github.com/xNotLikex/clip-farming/releases/latest';
            }

            if (m) {
                m.classList.remove('hidden');
                m.classList.add('flex');
                m.style.setProperty('display', 'flex', 'important');
            }
        }

        function closeUpdateModal() {
            var m = document.getElementById('update-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.setProperty('display', 'none', 'important');
            }
        }

        function performUpdate(btn) {
            if (!currentUpdateData || !currentUpdateData.download_url) {
                window.open('https://github.com/xNotLikex/clip-farming/releases/latest', '_blank');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="inline-block animate-spin mr-1">⌛</span> <span>Lade Installer...</span>';
            }
            var statusMsg = document.getElementById('update-status-msg');
            if (statusMsg) {
                statusMsg.innerHTML = '<span class="text-amber-400">Lade Installer von GitHub herunter... Bitte kurz warten.</span>';
            }

            fetch('/api/apply-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ download_url: currentUpdateData.download_url })
            })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res && res.success) {
                    if (statusMsg) statusMsg.innerHTML = '<span class="text-emerald-400 font-bold">✓ Installer gestartet! Setup wird ausgeführt...</span>';
                    setTimeout(closeUpdateModal, 3000);
                } else {
                    if (statusMsg) statusMsg.innerHTML = '<span class="text-rose-400">Fehler beim Update: ' + (res.error || 'Download fehlgeschlagen') + '</span>';
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<span>Erneut versuchen</span>';
                    }
                }
            })
            .catch(function(err) {
                if (statusMsg) statusMsg.innerHTML = '<span class="text-rose-400">Download fehlgeschlagen. Öffne GitHub...</span>';
                window.open('https://github.com/xNotLikex/clip-farming/releases/latest', '_blank');
            });
        }

        window.checkForUpdates = checkForUpdates;
        window.openUpdateModal = openUpdateModal;
        window.closeUpdateModal = closeUpdateModal;
        window.performUpdate = performUpdate;

        window.addEventListener('DOMContentLoaded', function() {
            setTimeout(checkForUpdates, 1500);
        });

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
            var poster = document.getElementById('modal-video-poster');
            if (poster) {
                poster.src = '/thumbnail/raw/' + encodeURIComponent(clipId) + '?t=' + Date.now();
                poster.style.display = 'block';
            }
            var player = document.getElementById('modal-video-player');
            if (player) {
                player.poster = '/thumbnail/raw/' + encodeURIComponent(clipId);
                player.src = '/raw-video/' + encodeURIComponent(clipId);
                player.onplaying = function() {
                    if (poster) poster.style.display = 'none';
                };
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

                        // Bei Uebergang von aktiv -> idle: Studio-Vorschaukarten & Videos aktualisieren
                        if (window.gLiveStudioPrevRunning) {
                            if (typeof window.refreshDashboard === 'function') {
                                window.refreshDashboard();
                            } else {
                                var ts = Date.now();
                                document.querySelectorAll('img[id^="poster-img-"]').forEach(function(img) {
                                    var base = img.src.split('?')[0];
                                    img.src = base + '?v=' + ts;
                                });
                                document.querySelectorAll('video[id^="studio-video-"]').forEach(function(vid) {
                                    var pBase = (vid.getAttribute('poster') || '').split('?')[0];
                                    if (pBase) vid.setAttribute('poster', pBase + '?v=' + ts);
                                    var s = vid.querySelector('source');
                                    if (s) {
                                        s.src = s.src.split('?')[0] + '?v=' + ts;
                                        vid.load();
                                    }
                                });
                            }
                        }
                    }
                    window.gLiveStudioPrevRunning = data.is_running;

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
                        <span class="text-2xs font-mono text-slate-400 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded font-semibold tracking-wider">v{{ app_version }}</span>
                    </h1>
                    <button id="update-badge" style="display: none;" onclick="openUpdateModal()" class="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40 hover:bg-amber-500/30 transition shadow-sm animate-pulse cursor-pointer">
                        <span>Update <span id="update-badge-v"></span> verfügbar</span>
                    </button>
                    <span id="live-indicator" class="flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold uppercase tracking-wider bg-slate-800 text-slate-300 border border-slate-700 shadow-sm">
                        <span class="w-2 h-2 rounded-full {% if is_running %}bg-emerald-400 animate-ping{% else %}bg-slate-400{% endif %}" id="live-dot"></span>
                        <span id="live-status-text">{% if is_running %}AKTIV: {{ current_status|upper }}{% else %}STANDBY{% endif %}</span>
                    </span>
                </div>
                <p id="live-task-desc" class="text-slate-400 text-sm mt-1">{{ current_task }}</p>
            </div>

            <!-- Quick Action Buttons -->
            <div class="flex flex-wrap items-center gap-3">
                <button onclick="switchTab('streamers')" class="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm rounded transition text-slate-200 shadow">
                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg> Streamer verwalten ({{ streamers|length }})
                </button>
                <button onclick="openSettingsModal()" class="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm rounded transition text-slate-200 shadow">
                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg> Einstellungen
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

        <!-- Modern Unified Navigation Bar -->
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-800 gap-3">
            <div class="flex items-center gap-1 text-sm font-medium overflow-x-auto w-full sm:w-auto -mb-px">
                <button onclick="switchTab('queue')" id="tab-queue-btn" class="tab-btn px-4 py-3 flex items-center gap-2 border-b-2 border-amber-500 text-white font-semibold transition whitespace-nowrap">
                    <span>Warteschlange</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">{{ counts.harvested }}</span>
                </button>
                <button onclick="switchTab('studio')" id="tab-studio-btn" class="tab-btn px-4 py-3 flex items-center gap-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition whitespace-nowrap">
                    <span>Studio & Freigabe</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">{{ counts.ready }}</span>
                </button>
                <button onclick="switchTab('planner')" id="tab-planner-btn" class="tab-btn px-4 py-3 flex items-center gap-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition whitespace-nowrap">
                    <span>Planer</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">{{ counts.scheduled }}</span>
                </button>
                <button onclick="switchTab('accounts')" id="tab-accounts-btn" class="tab-btn px-4 py-3 flex items-center gap-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition whitespace-nowrap">
                    <span>Konten</span>
                    <span class="w-2 h-2 rounded-full {% if account_status.youtube.is_connected or account_status.tiktok.is_connected %}bg-emerald-400{% else %}bg-slate-600{% endif %}"></span>
                </button>
                <button onclick="switchTab('streamers')" id="tab-streamers-btn" class="tab-btn px-4 py-3 flex items-center gap-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition whitespace-nowrap">
                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg>
                    <span>Streamer</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-mono" id="tab-count-streamers">{{ streamers|length }}</span>
                </button>
            </div>

            <!-- Compact Drawer Ticker -->
            <div class="flex items-center gap-2 pb-2 sm:pb-0 text-xs">
                <button type="button" onclick="toggleLogs()" class="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5 font-mono">
                    <span id="log-count" class="text-slate-400">{{ initial_logs|length }} Logs</span>
                    <span id="log-toggle-icon" class="text-[10px] text-slate-500">▼</span>
                </button>
            </div>
        </div>

        <!-- Collapsible Log Drawer (Hidden by default) -->
        <div id="log-drawer-container" class="space-y-2">
            <div id="log-box" class="hidden bg-slate-950 p-3.5 rounded-lg font-mono text-xs text-slate-300 max-h-48 overflow-y-auto space-y-1 border border-slate-800">
                {% if initial_logs %}
                    {% for log in initial_logs[-40:] %}
                        <div class="text-slate-300 leading-relaxed font-mono">{{ log }}</div>
                    {% endfor %}
                {% else %}
                    <div class="text-slate-500">Warte auf Aktionen...</div>
                {% endif %}
            </div>
        </div>

        <!-- TAB 1: WARTESCHLANGE -->
        <div id="tab-queue" class="tab-content space-y-4">
            <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center p-4 bg-slate-950/80 border-b border-slate-800 gap-3">
                    <div>
                        <div class="text-sm font-semibold text-slate-100 flex items-center gap-2">
                            <span>Warteschlange</span>
                            <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">{{ counts.harvested }} Rohdateien</span>
                        </div>
                        <span class="text-xs text-slate-400 mt-0.5 block">Klicke auf eine Zeile für die Videovorschau vor dem Zuschnitt.</span>
                    </div>
                    {% if counts.harvested > 0 %}
                    <div class="flex flex-wrap items-center gap-2.5">
                        {% if older_queue_count > 0 %}
                        <form action="/queue/delete-older" method="POST" class="inline" onsubmit="return confirm('Wirklich alle {{ older_queue_count }} Roh-Clips von gestern und älter löschen?');">
                            <button type="submit" class="px-3 py-1.5 text-xs text-slate-400 hover:text-rose-300 hover:bg-rose-950/40 border border-slate-700/80 rounded transition font-medium" title="Löscht alle {{ older_queue_count }} Roh-Clips von gestern & älter">
                                Gestern & älter löschen ({{ older_queue_count }})
                            </button>
                        </form>
                        {% endif %}
                        <button onclick="processAll()" id="btn-process-all" class="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-xs rounded transition flex items-center gap-2 shadow-sm">
                            <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Alle ins Studio übernehmen
                        </button>
                    </div>
                    {% endif %}
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-sm">
                        <thead>
                            <tr class="border-b border-slate-800/80 bg-slate-950/60 text-slate-400 text-xs font-semibold">
                                <th class="py-3 px-4 w-12 text-center"></th>
                                <th class="py-3 px-4 whitespace-nowrap">Streamer</th>
                                <th class="py-3 px-4">Clip</th>
                                <th class="py-3 px-4 whitespace-nowrap">Dauer & Views</th>
                                <th class="py-3 px-4 whitespace-nowrap">Erstellt</th>
                                <th class="py-3 px-4 text-right whitespace-nowrap">Aktion</th>
                            </tr>
                        </thead>
                        <tbody id="queue-tbody" class="divide-y divide-slate-800/60">
                            {% for clip in queue_clips %}
                            <tr data-clip-id="{{ clip.clip_id }}" data-streamer="{{ clip.streamer|e }}" data-title="{{ clip.original_title|e }}" data-views="{{ clip.view_count }}" data-duration="{{ '%.0f'|format(clip.duration) }}" data-created-ago="{{ clip.created_ago|e }}" data-created-full="{{ clip.created_full|e }}" onclick="openRawPreviewFromRow(this)"
                                class="hover:bg-slate-800/40 cursor-pointer transition group">
                                <td class="py-3 px-4 text-center whitespace-nowrap">
                                    <div class="w-7 h-7 rounded bg-slate-800 group-hover:bg-amber-500 group-hover:text-slate-950 text-slate-400 flex items-center justify-center text-xs transition">
                                        ▶
                                    </div>
                                </td>
                                <td class="py-3 px-4 whitespace-nowrap">
                                    <span class="font-semibold text-slate-200 text-sm block">{{ clip.streamer }}</span>
                                </td>
                                <td class="py-3 px-4">
                                    <div class="font-medium text-slate-100 group-hover:text-amber-400 transition text-sm">{{ clip.original_title }}</div>
                                </td>
                                <td class="py-3 px-4 text-slate-400 text-xs whitespace-nowrap">
                                    <span class="font-mono text-slate-300">{{ "%.0f"|format(clip.duration) }}s</span>
                                    <span class="text-slate-600 mx-1.5">•</span>
                                    <span class="font-mono text-slate-300">{{ clip.view_count }} Views</span>
                                </td>
                                <td class="py-3 px-4 text-slate-400 text-xs whitespace-nowrap" title="{{ clip.created_full }}">
                                    <span>{{ clip.created_ago }}</span>
                                </td>
                                <td class="py-3 px-4 text-right whitespace-nowrap" onclick="event.stopPropagation()">
                                    <div class="flex items-center justify-end gap-1.5 opacity-80 group-hover:opacity-100 transition">
                                        <form action="/process-one/{{ clip.clip_id }}" method="POST" class="inline">
                                            <button type="submit" class="px-3 py-1.5 bg-slate-800 hover:bg-amber-500 hover:text-slate-950 text-slate-200 font-semibold text-xs rounded border border-slate-700/80 hover:border-amber-500 transition shadow-sm">
                                                In Studio
                                            </button>
                                        </form>
                                        <form action="/queue/delete/{{ clip.clip_id }}" method="POST" class="inline" onsubmit="return confirm('Clip unwiderruflich löschen?');">
                                            <button type="submit" class="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-950/40 rounded transition" title="Löschen">
                                                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                                            </button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="6" class="py-12 text-center text-slate-500">Keine Clips in der Warteschlange.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 2: STUDIO & FREIGABE -->
        <div id="tab-studio" class="tab-content hidden space-y-6">
            <!-- Manuelle Streamer-Suche & Clip-Explorer -->
            <div class="bg-slate-900 border border-slate-800 rounded-lg p-4 shadow-xl space-y-4">
                <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                    <div>
                        <h3 class="text-sm font-bold text-white flex items-center gap-2">
                            <svg class="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                            Twitch Clip-Explorer (Manuelle Streamer-Suche)
                        </h3>
                        <p class="text-xs text-slate-400 mt-0.5">Durchsuche beliebige Twitch-Streamer nach Zeitfenster und importiere Wunsch-Clips direkt ins Studio.</p>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                        <div class="relative">
                            <input type="text" id="manual-search-streamer" list="manual-search-datalist"
                                onkeydown="if(event.key==='Enter'){event.preventDefault(); searchManualStreamerClips();}"
                                placeholder="Streamer-Name (z. B. eliasn97)..."
                                class="w-56 sm:w-64 bg-slate-950 border border-slate-700 focus:border-amber-500 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 outline-none transition">
                            <datalist id="manual-search-datalist">
                                {% for s in streamers %}
                                <option value="{{ s.name }}">{{ s.name }}</option>
                                {% endfor %}
                            </datalist>
                        </div>
                        <div class="inline-flex rounded-lg bg-slate-950 border border-slate-800 p-0.5" role="group" aria-label="Zeitfenster">
                            <button type="button" onclick="selectManualTimeframe('LAST_DAY')" id="manual-tf-LAST_DAY" data-tf="LAST_DAY" class="manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold bg-amber-500 text-zinc-950 transition">24h</button>
                            <button type="button" onclick="selectManualTimeframe('LAST_WEEK')" id="manual-tf-LAST_WEEK" data-tf="LAST_WEEK" class="manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-white transition">7 Tage</button>
                            <button type="button" onclick="selectManualTimeframe('LAST_MONTH')" id="manual-tf-LAST_MONTH" data-tf="LAST_MONTH" class="manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-white transition">30 Tage</button>
                            <button type="button" onclick="selectManualTimeframe('ALL_TIME')" id="manual-tf-ALL_TIME" data-tf="ALL_TIME" class="manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-white transition">All-Time</button>
                        </div>
                        <button type="button" id="btn-manual-search" onclick="searchManualStreamerClips()" class="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs rounded-lg transition flex items-center gap-1.5 shadow-sm">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                            <span>Clips suchen</span>
                        </button>
                    </div>
                </div>

                <!-- Suchergebnisse -->
                <div id="manual-search-results" class="hidden pt-3 border-t border-slate-800/80 space-y-3">
                    <div id="manual-search-header" class="flex flex-wrap items-center justify-between gap-2 bg-slate-950/70 px-3.5 py-2.5 rounded-lg border border-slate-800/80">
                        <div class="flex items-center gap-2.5" id="manual-search-streamer-info"></div>
                        <button type="button" onclick="closeManualSearchResults()" class="text-xs text-slate-400 hover:text-white px-2.5 py-1 rounded bg-slate-800/80 hover:bg-slate-700 transition">
                            ✕ Ergebnisse schließen
                        </button>
                    </div>
                    <div id="manual-search-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"></div>
                </div>
            </div>

            {% if ready_clips %}
            <!-- Sammel-Aktionen Header -->
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-lg gap-3">
                <div>
                    <span class="text-sm font-bold text-white">{{ counts.ready }} Shorts bereit zur Bearbeitung & Veröffentlichung</span>
                    <span class="text-xs text-slate-400 block">Du kannst jeden Clip einzeln anpassen oder alle gestaffelt im Zeitplan veröffentlichen.</span>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                    <button type="button" onclick="exportAllReadyClips(this)" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs rounded transition flex items-center gap-2 shadow-sm" title="Alle fertigen Videos in einen gewählten Ordner exportieren">
                        <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/></svg> Alle fertigen Shorts exportieren
                    </button>
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
            </div>

            <!-- Streamer Filter Bar (Sortiert nach Streamer) -->
            <div id="streamer-pills-container" class="flex flex-wrap items-center gap-2 bg-slate-900/80 border border-slate-800 p-3.5 rounded-lg shadow">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">Filter nach Streamer:</span>
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
                    <div class="relative bg-black aspect-[9/16] w-full max-h-[480px] flex items-center justify-center overflow-hidden group">
                        {% if clip.has_video %}
                        <!-- Instant Visible Poster Overlay to guarantee frame is never black -->
                        <div id="poster-overlay-{{ clip.clip_id }}" class="absolute inset-0 z-10 flex items-center justify-center cursor-pointer transition-opacity duration-300" onclick="startStudioVideoPlay('{{ clip.clip_id }}', this)">
                            <img id="poster-img-{{ clip.clip_id }}" src="/thumbnail/{{ clip.clip_id }}?v={{ clip.updated_at }}" alt="Vorschau" class="absolute inset-0 w-full h-full object-cover">
                            <div class="w-14 h-14 rounded-full bg-slate-900/80 border-2 border-amber-400/90 text-amber-400 flex items-center justify-center text-xl shadow-2xl backdrop-blur transition-transform group-hover:bg-amber-500">
                                ▶
                            </div>
                        </div>
                        <video id="studio-video-{{ clip.clip_id }}" controls preload="metadata" poster="/thumbnail/{{ clip.clip_id }}?v={{ clip.updated_at }}" class="w-full h-full object-contain relative z-0" onplay="var p = document.getElementById('poster-overlay-{{ clip.clip_id }}'); if (p) p.style.display = 'none';">
                            <source src="/video/{{ clip.clip_id }}?v={{ clip.updated_at }}" type="video/mp4">
                        </video>
                        {% else %}
                        <div class="text-center p-6 text-slate-500">
                            <div class="w-8 h-8 mx-auto mb-2 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></div>
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
                    <form id="form-{{ clip.clip_id }}" action="/save/{{ clip.clip_id }}" method="POST" class="p-5 flex-1 flex flex-col justify-between gap-4">
                        <div class="space-y-3">
                            <!-- Sticker Hook Text -->
                            <div>
                                <label class="block text-xs font-medium text-slate-300 mb-1 flex justify-between">
                                    <span>TikTok / Shorts Hook</span>
                                    <span class="text-slate-500 font-normal">Mitte</span>
                                </label>
                                <input type="text" name="sticker_text" value="{{ clip.sticker_text }}" 
                                    placeholder="z. B. Gtastys ki hittet double mace"
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                            </div>

                            <!-- Video Title -->
                            <div>
                                <label class="block text-xs font-medium text-slate-300 mb-1">
                                    Titel (YouTube / TikTok)
                                </label>
                                <input type="text" name="title" value="{{ clip.title }}" 
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                            </div>

                            <!-- Untertitel-Platzierung -->
                            <div>
                                <label class="block text-xs font-medium text-slate-300 mb-1">
                                    Untertitel-Platzierung
                                </label>
                                <select name="sub_position" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                                    <option value="bottom" {% if clip.sub_position == 'bottom' %}selected{% endif %}>Unten (Standard, über Shorts-UI)</option>
                                    <option value="center" {% if clip.sub_position == 'center' %}selected{% endif %}>Mitte (Unteres Drittel über Game)</option>
                                    <option value="top" {% if clip.sub_position == 'top' %}selected{% endif %}>Oben (Über Facecam)</option>
                                    <option value="none" {% if clip.sub_position == 'none' %}selected{% endif %}>Keine Untertitel (z.B. Trymacs bereits im Stream)</option>
                                </select>
                            </div>

                            <!-- Video-Layout & Aufteilung (Split-Screen vs. Blur vs. IRL 9:16) -->
                            <div>
                                <label class="block text-xs font-medium text-slate-300 mb-1">
                                    Video-Layout & Aufteilung
                                </label>
                                <select name="layout_mode" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                                    <option value="auto" {% if clip.layout_mode == 'auto' %}selected{% endif %}>Automatisch (KI erkennt Facecam vs. IRL)</option>
                                    <option value="custom" {% if clip.layout_mode == 'custom' %}selected{% endif %}>Benutzerdefiniert (Visuelle Schnittrahmen)</option>
                                    <option value="single_916" {% if clip.layout_mode == 'single_916' %}selected{% endif %}>Reines 9:16 Vollbild (IRL / Einzelfokus)</option>
                                    <option value="split_cam_top" {% if clip.layout_mode == 'split_cam_top' %}selected{% endif %}>Split-Screen (Cam oben, Gameplay unten)</option>
                                    <option value="blur_stack" {% if clip.layout_mode == 'blur_stack' %}selected{% endif %}>Blur-Stack (IRL / Vollbild mit unscharfem Hintergrund)</option>
                                </select>
                                <button type="button" data-clip-id="{{ clip.clip_id }}" data-streamer="{{ clip.streamer|e }}" data-title="{{ clip.title|e }}" onclick="openCropModalFromButton(this)" 
                                    class="w-full mt-2 py-2 px-3 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-200 hover:text-white rounded text-xs font-medium transition flex items-center justify-center gap-2">
                                    <svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg> Bildausschnitt anpassen (Split-Cam oder 9:16)
                                </button>
                            </div>

                            <!-- Cam-Filter / Effekte (Snapchat / TikTok Style) -->
                            <div>
                                <label class="block text-xs font-medium text-slate-300 mb-1 flex justify-between">
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
                                <label class="block text-xs font-medium text-slate-300 mb-1 flex justify-between">
                                    <span>Untertiteltext (hier bearbeiten & korrigieren)</span>
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
                                <span>HQ Video speichern unter... (.mp4)</span>
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
                <div class="w-12 h-12 mx-auto mb-3 text-slate-600 flex items-center justify-center"><svg class="w-10 h-10" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"/></svg></div>
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
                    <svg class="w-8 h-8 text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
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
                                <svg class="w-8 h-8 text-red-500" fill="currentColor" viewBox="0 0 24 24"><path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/></svg>
                                <div>
                                    <h3 class="text-lg font-bold text-white">YouTube Shorts</h3>
                                    <span class="text-xs text-slate-400">Google YouTube Data API v3</span>
                                </div>
                            </div>
                            {% if account_status.youtube.is_connected %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 mr-1.5"></span>Aktiv
                            </span>
                            {% elif account_status.youtube.has_secrets %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800">
                                <span class="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1.5"></span>Bereit
                            </span>
                            {% else %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-zinc-800 text-slate-400 border border-slate-700">
                                <span class="inline-block w-2 h-2 rounded-full bg-slate-500 mr-1.5"></span>Inaktiv
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
                                    Zugangsdaten speichern
                                </button>
                            </form>

                            <!-- Alternative: Datei-Upload -->
                            <details class="text-2xs text-slate-400">
                                <summary class="cursor-pointer hover:text-slate-300 font-semibold mb-2">Oder client_secrets.json Datei hochladen...</summary>
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
                                YouTube Verbindung trennen
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
                                <svg class="w-8 h-8 text-cyan-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.24 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>
                                <div>
                                    <h3 class="text-lg font-bold text-white">TikTok</h3>
                                    <span class="text-xs text-slate-400">Creator Session Upload</span>
                                </div>
                            </div>
                            {% if account_status.tiktok.is_connected %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 mr-1.5"></span>Aktiv
                            </span>
                            {% else %}
                            <span class="px-2.5 py-1 rounded text-xs font-semibold bg-zinc-800 text-slate-400 border border-slate-700">
                                <span class="inline-block w-2 h-2 rounded-full bg-slate-500 mr-1.5"></span>Inaktiv
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
                                    Erneut verbinden / Anderen Account wählen
                                </button>
                            </div>
                        </div>
                        {% else %}
                        <!-- ⭐ AUTOMATISCHER BROWSER LOGIN (MÖGLICHKEIT 1) -->
                        <div class="p-4 bg-gradient-to-r from-pink-950/70 via-slate-900 to-slate-900 border border-slate-800 rounded-lg text-center shadow-lg">
                            <span class="text-2xs font-black text-pink-300 uppercase tracking-wider block mb-1">Automatische 1-Klick Methode (Empfohlen):</span>
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
                            <summary class="cursor-pointer hover:text-slate-300 font-semibold mb-2">Alternative: Manuelle sessionid Eingabe (Entwicklertools F12)...</summary>
                            
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
                                            Speichern
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
                                TikTok Verbindung trennen
                            </button>
                        </form>
                    </div>
                    {% endif %}
                </div>

            </div>
        </div>

        <!-- TAB 5: STREAMER VERWALTEN (FULL PAGE) -->
        <div id="tab-streamers" class="tab-content hidden space-y-6">
            <!-- Header Banner -->
            <div class="bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center text-amber-400 shrink-0">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg>
                    </div>
                    <div>
                        <div class="flex items-center gap-3">
                            <h2 class="text-lg font-bold text-white">Überwachte Streamer verwalten</h2>
                            <span class="text-xs font-mono font-medium px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                                <span id="fullpage-streamer-count">{{ streamers|length }}</span> Kanäle aktiv
                            </span>
                        </div>
                        <p class="text-xs text-slate-400 mt-1 max-w-2xl">
                            Passe Mindest-Views und Clip-Limits gezielt an und definiere visuelle Cam- & Gameplay-Zuschnitte. Profilbilder werden automatisch live von Twitch geladen.
                        </p>
                    </div>
                </div>

                <!-- Schnellsuche -->
                <div class="w-full md:w-72">
                    <div class="relative">
                        <span class="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none text-slate-500 text-xs"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg></span>
                        <input type="text" id="streamer-search-input" oninput="if (window.filterStreamersList) window.filterStreamersList(this.value);" placeholder="Streamer suchen..." 
                               class="w-full bg-slate-950/80 border border-slate-700/80 rounded-md pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-500 transition">
                    </div>
                </div>
            </div>

            <!-- Top Grid: Neuen Streamer hinzufügen & Massen-Einstellungen -->
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">
                
                <!-- Card 1: Neuen Streamer hinzufügen (7 cols) -->
                <div class="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-sm flex flex-col justify-between">
                    <form action="/api/streamers/add" method="POST" onsubmit="event.preventDefault(); if (window.addStreamerFromForm) window.addStreamerFromForm(this); else this.submit();" class="space-y-4">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-semibold text-slate-200 flex items-center gap-2">
                                <span>Neuen Twitch-Streamer hinzufügen</span>
                            </span>
                            <span class="text-2xs text-slate-500">Profilbild wird automatisch von Twitch bezogen</span>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div class="sm:col-span-1">
                                <label class="block text-2xs font-semibold text-slate-300 mb-1">Twitch Kanalname:</label>
                                <input type="text" name="name" required placeholder="z. B. rewinside, trymacs..." 
                                    class="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500 font-semibold shadow-inner">
                            </div>
                            <div>
                                <label class="block text-2xs font-semibold text-slate-300 mb-1">Min. Views:</label>
                                <input type="number" name="min_views" value="30" min="5" max="100000"
                                    class="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-amber-300 font-bold focus:outline-none focus:border-amber-500 shadow-inner">
                            </div>
                            <div>
                                <label class="block text-2xs font-semibold text-slate-300 mb-1">Max Clips/Run:</label>
                                <input type="number" name="max_clips" value="2" min="1" max="10"
                                    class="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-white font-bold focus:outline-none focus:border-amber-500 shadow-inner">
                            </div>
                        </div>
                        <button type="submit" class="w-full py-2.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded-md transition shadow-sm flex items-center justify-center gap-2">
                            <span>Streamer hinzufügen & überwachen</span>
                        </button>
                    </form>
                </div>

                <!-- Card 2: Globale Mindest-Views für alle (5 cols) -->
                <div class="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-sm flex flex-col justify-between">
                    <div>
                        <div class="flex items-center gap-2.5 mb-1.5">
                            <span class="text-xs font-semibold text-slate-200">Mindest-Views für alle Streamer</span>
                        </div>
                        <p class="text-2xs text-slate-400 leading-relaxed">
                            Überschreibt die Mindestanzahl Views für alle aktuell überwachten Streamer auf einen festen Wert.
                        </p>
                    </div>

                    <div class="flex items-center gap-3 pt-3">
                        <div class="flex items-center gap-2 bg-slate-950 border border-slate-700 rounded-md px-3 py-2 flex-1 shadow-inner">
                            <span class="text-2xs text-slate-400 font-mono">Views:</span>
                            <input type="number" id="bulk-min-views-input-fullpage" value="25" min="1" max="100000" class="w-full bg-transparent text-xs text-amber-300 font-bold text-center focus:outline-none">
                        </div>
                        <button type="button" onclick="if (window.applyBulkMinViewsFromInput) window.applyBulkMinViewsFromInput('bulk-min-views-input-fullpage'); else applyBulkMinViews();" class="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold text-xs rounded-md transition whitespace-nowrap shadow-sm">
                            Für alle setzen
                        </button>
                    </div>
                </div>

            </div>

            <!-- Streamers Grid (Spacious Full Page Grid) -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider block">Aktive Kanäle</span>
                    <span id="streamer-filter-count" class="text-2xs text-slate-500 font-mono">{{ streamers|length }} angezeigt</span>
                </div>
                
                <div id="streamer-grid-list" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {% for s in streamers %}
                    <div class="streamer-card bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-lg p-4 shadow-sm transition flex flex-col justify-between gap-3.5" data-streamer="{{ s.name|lower }}">
                        <div class="flex items-start justify-between gap-3">
                            <div class="flex items-center gap-3 min-w-0">
                                <div class="relative shrink-0">
                                    <img src="{{ s.avatar_url or 'https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png' }}" 
                                         alt="{{ s.name }}" 
                                         onerror="this.src='https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png'"
                                         class="w-12 h-12 rounded-full border border-slate-700 object-cover shadow-sm bg-slate-950">
                                    <span class="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 border-2 border-slate-900 rounded-full" title="Überwachung aktiv"></span>
                                </div>
                                <div class="min-w-0">
                                    <span class="font-semibold text-sm text-white truncate block">{{ s.display_name or s.name }}</span>
                                    <a href="https://twitch.tv/{{ s.name }}" target="_blank" class="text-2xs text-slate-400 hover:text-slate-200 font-mono flex items-center gap-1 hover:underline">
                                        <span>twitch.tv/{{ s.name }}</span>
                                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                                    </a>
                                    <div class="mt-1">
                                        {% if s.custom_crops %}
                                        <span class="inline-flex items-center gap-1 text-2xs font-semibold text-emerald-300 bg-emerald-950/70 border border-emerald-800/80 px-2 py-0.5 rounded">
                                            <span>Eigener Rahmen gespeichert</span>
                                        </span>
                                        {% else %}
                                        <span class="inline-flex items-center gap-1 text-2xs font-medium text-slate-400 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded">
                                            <span>Layout:</span> {{ s.layout or 'auto' }}
                                        </span>
                                        {% endif %}
                                    </div>
                                </div>
                            </div>
                            <button onclick="removeStreamer('{{ s.name }}')" class="text-slate-500 hover:text-rose-400 p-1.5 hover:bg-rose-950/40 rounded-md transition shrink-0" title="Streamer entfernen">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                            </button>
                        </div>

                        <div class="grid grid-cols-2 gap-2 bg-slate-950/60 p-2.5 rounded-md border border-slate-800/80 text-xs">
                            <div>
                                <label class="block text-2xs font-medium text-slate-400 mb-1">Min. Views:</label>
                                <input type="number" value="{{ s.min_clip_views }}" min="1" max="100000"
                                       onchange="updateStreamerMinViews('{{ s.name }}', this.value)"
                                       class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded-md px-2 py-1 text-xs text-amber-300 font-semibold focus:outline-none">
                            </div>
                            <div>
                                <label class="block text-2xs font-medium text-slate-400 mb-1">Max Clips/Run:</label>
                                <input type="number" value="{{ s.max_clips_per_run }}" min="1" max="10"
                                       onchange="updateStreamerMaxClips('{{ s.name }}', this.value)"
                                       class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded-md px-2 py-1 text-xs text-white font-semibold focus:outline-none">
                            </div>
                            <div class="col-span-2 mt-0.5">
                                <label class="block text-2xs font-medium text-slate-400 mb-1">Standard Clip-Layout:</label>
                                <select onchange="updateStreamerLayout('{{ s.name }}', this.value)"
                                        class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded-md px-2 py-1 text-xs text-amber-300 font-semibold focus:outline-none">
                                    <option value="auto" {% if s.layout == 'auto' or not s.layout %}selected{% endif %}>Auto (KI Facecam-Scan)</option>
                                    <option value="split_cam_top" {% if s.layout == 'split_cam_top' %}selected{% endif %}>Split-Screen (Cam oben + Game unten)</option>
                                    <option value="blur_stack" {% if s.layout == 'blur_stack' %}selected{% endif %}>Keine Cam (Gameplay mit Blur)</option>
                                    <option value="single_916" {% if s.layout == 'single_916' %}selected{% endif %}>9:16 Vollbild (IRL)</option>
                                    <option value="custom" {% if s.layout == 'custom' %}selected{% endif %}>Eigener gespeicherter Rahmen</option>
                                    <option value="top_left" {% if s.layout == 'top_left' %}selected{% endif %}>Cam: Oben Links</option>
                                    <option value="top_right" {% if s.layout == 'top_right' %}selected{% endif %}>Cam: Oben Rechts</option>
                                    <option value="bottom_left" {% if s.layout == 'bottom_left' %}selected{% endif %}>Cam: Unten Links</option>
                                    <option value="bottom_right" {% if s.layout == 'bottom_right' %}selected{% endif %}>Cam: Unten Rechts</option>
                                </select>
                            </div>
                        </div>

                        <div class="flex items-center gap-2 pt-1 border-t border-slate-800/80">
                            <button type="button" onclick="loadSampleClipDirect('{{ s.name }}', this)" class="flex-1 py-1.5 px-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-amber-500/50 text-amber-300 font-semibold text-xs rounded-md transition flex items-center justify-center gap-1.5 shadow-sm" title="Lädt automatisch einen Test-Clip herunter und öffnet den visuellen 16:9 zu 9:16 Rahmen-Editor">
                                <span>Test-Clip & Rahmen einstellen</span>
                            </button>
                            <button type="button" onclick="openStreamerConfigModal('{{ s.name }}')" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-semibold rounded-md transition shrink-0" title="Erweiterte Einstellungen">
                                <svg class="w-3.5 h-3.5 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            </button>
                        </div>
                    </div>
                    {% endfor %}
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
            
            <div class="relative bg-black aspect-video w-full flex items-center justify-center overflow-hidden group">
                <img id="modal-video-poster" src="" class="absolute inset-0 w-full h-full object-cover z-0 pointer-events-none" alt="" style="display: none;">
                <video id="modal-video-player" controls autoplay class="w-full h-full object-contain relative z-10">
                    <source id="modal-video-source" src="" type="video/mp4">
                    Dein Browser unterstützt dieses Video nicht.
                </video>
            </div>
            
            <div class="p-4 bg-slate-950/90 border-t border-slate-800 flex flex-col sm:flex-row justify-between items-center gap-3">
                <span id="modal-stats" class="text-xs text-slate-400 font-medium">Views & Dauer</span>
                <div class="flex items-center gap-2">
                    <button id="modal-download-raw" type="button" onclick="downloadRawVideo(currentPreviewClipId, this, event)" class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-xs text-slate-200 rounded transition flex items-center gap-1.5 cursor-pointer" title="Speicherort wählen & Rohdatei sichern (Shift-Klick für Downloads-Ordner)">
                        <span>Rohdatei speichern unter...</span>
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
                    <svg class="w-5 h-5 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
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
                        Streamer hinzufügen & dauerhaft speichern
                    </button>
                </form>

                <!-- Massen-Einstellung für alle Streamer -->
                <div class="bg-gradient-to-r from-amber-950/40 via-slate-900 to-amber-950/30 border border-amber-500/30 rounded-lg p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-md">
                    <div class="flex items-center gap-2.5">
                        
                        <div>
                            <span class="text-xs font-bold text-amber-300 block">Mindest-Views für ALLE Streamer setzen</span>
                            <span class="text-2xs text-slate-400">Überschreibt die Mindest-Views für alle derzeit aktiven Streamer mit einem Klick</span>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 w-full sm:w-auto">
                        <div class="flex items-center gap-1.5 bg-slate-950 border border-slate-700 rounded px-2 py-1">
                            <span class="text-2xs text-slate-400 font-mono">Views:</span>
                            <input type="number" id="bulk-min-views-input" value="25" min="1" max="10000" class="w-20 bg-slate-800 border border-slate-600 rounded px-2 py-0.5 text-xs text-amber-300 font-bold text-center focus:border-amber-500 focus:outline-none">
                        </div>
                        <button type="button" onclick="applyBulkMinViews()" class="px-3.5 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs rounded transition whitespace-nowrap shadow-sm">
                            Für alle übernehmen
                        </button>
                    </div>
                </div>

                <!-- Aktive Streamer Liste -->
                <div class="space-y-2">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-bold text-slate-300 uppercase tracking-wider block">Aktuell überwachte Streamer</span>
                        <span class="text-xs text-slate-500 font-mono">{{ streamers|length }} aktiv</span>
                    </div>
                    <div id="streamer-modal-list" class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-64 overflow-y-auto pr-1">
                        {% for s in streamers %}
                        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-800/80 border border-slate-700/80 p-3 rounded-lg hover:border-slate-600 transition gap-3">
                            <div class="min-w-0">
                                <span class="font-bold text-sm text-amber-400 block truncate">{{ s.name }}</span>
                                <span class="text-2xs text-slate-400 font-mono">Twitch</span>
                            </div>
                            <div class="flex items-center gap-2 flex-wrap">
                                <button type="button" onclick="openStreamerConfigModal('{{ s.name }}')" class="px-2.5 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/50 text-amber-300 text-xs font-bold rounded-lg transition flex items-center gap-1.5" title="Streamer-Einstellungen & Rahmen konfigurieren">
                                    <svg class="w-3.5 h-3.5 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg> <span>Konfigurieren</span>
                                </button>
                                <div class="flex items-center gap-1.5 bg-slate-900/90 border border-slate-700/80 rounded px-2 py-1">
                                    <span class="text-2xs text-slate-400 font-medium whitespace-nowrap">Layout:</span>
                                    <select onchange="updateStreamerLayout('{{ s.name }}', this.value)"
                                            class="bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 text-2xs text-amber-300 font-semibold focus:border-amber-500 focus:outline-none">
                                        <option value="auto" {% if s.layout == 'auto' or not s.layout %}selected{% endif %}>Auto (KI)</option>
                                        <option value="split_cam_top" {% if s.layout == 'split_cam_top' %}selected{% endif %}>Split-Cam (Oben)</option>
                                        <option value="blur_stack" {% if s.layout == 'blur_stack' %}selected{% endif %}>Keine Cam (Blur)</option>
                                        <option value="single_916" {% if s.layout == 'single_916' %}selected{% endif %}>9:16 Vollbild</option>
                                        <option value="custom" {% if s.layout == 'custom' %}selected{% endif %}>Eigener Rahmen {% if s.custom_crops %}(Gespeichert){% endif %}</option>
                                        <option value="top_left" {% if s.layout == 'top_left' %}selected{% endif %}>Cam: Oben Links</option>
                                        <option value="top_right" {% if s.layout == 'top_right' %}selected{% endif %}>Cam: Oben Rechts</option>
                                        <option value="bottom_left" {% if s.layout == 'bottom_left' %}selected{% endif %}>Cam: Unten Links</option>
                                        <option value="bottom_right" {% if s.layout == 'bottom_right' %}selected{% endif %}>Cam: Unten Rechts</option>
                                    </select>
                                </div>
                                <div class="flex items-center gap-1.5 bg-slate-900/90 border border-slate-700/80 rounded px-2 py-1">
                                    <span class="text-2xs text-slate-400 font-medium whitespace-nowrap">Min. Views:</span>
                                    <input type="number" value="{{ s.min_clip_views }}" min="1" max="10000"
                                           onchange="updateStreamerMinViews('{{ s.name }}', this.value)"
                                           class="w-14 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 text-xs text-amber-300 font-bold text-center focus:border-amber-500 focus:outline-none">
                                </div>
                                <div class="flex items-center gap-1.5 bg-slate-900/90 border border-slate-700/80 rounded px-2 py-1">
                                    <span class="text-2xs text-slate-400 font-medium whitespace-nowrap">Max Clips:</span>
                                    <input type="number" value="{{ s.max_clips_per_run }}" min="1" max="10"
                                           onchange="updateStreamerMaxClips('{{ s.name }}', this.value)"
                                           class="w-12 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 text-xs text-white font-bold text-center focus:border-amber-500 focus:outline-none">
                                </div>
                                <button onclick="removeStreamer('{{ s.name }}')" class="p-1 px-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 text-rose-300 font-bold text-xs rounded-lg transition" title="Streamer aus Überwachung entfernen">
                                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                                </button>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- POP-UP MODAL: Streamer Konfiguration & Test-Clip Rahmen -->
    <div id="streamer-config-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden items-center justify-center p-4" style="display: none !important;" onclick="if (event.target === this) closeStreamerConfigModal();">
        <div class="bg-slate-900 border border-slate-700/90 rounded-lg max-w-lg w-full overflow-hidden shadow-2xl flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-200">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/80">
                <div class="flex items-center gap-2.5">
                    <svg class="w-5 h-5 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                    <div>
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>Streamer Konfiguration:</span>
                            <span id="cfg-modal-streamer-name" class="text-amber-400 font-mono"></span>
                        </h3>
                        <p class="text-2xs text-slate-400">Filter, Limits und visuelle Standard-Rahmen anpassen</p>
                    </div>
                </div>
                <button onclick="closeStreamerConfigModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>

            <form id="streamer-config-form" onsubmit="saveStreamerConfig(event)" class="p-5 overflow-y-auto space-y-4">
                <input type="hidden" id="cfg-streamer-hidden-name" name="name">
                
                <!-- Views & Clip Limits -->
                <div class="grid grid-cols-2 gap-3 bg-slate-950/70 p-3.5 rounded-md border border-slate-800">
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Min. Views Clips:</label>
                        <input type="number" id="cfg-streamer-min-views" name="min_clip_views" min="1" max="10000" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-amber-300 font-bold focus:border-amber-500 focus:outline-none">
                        <span class="text-2xs text-slate-500 mt-1 block">Clips unter diesem Wert werden übersprungen.</span>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Max Clips/Run:</label>
                        <input type="number" id="cfg-streamer-max-clips" name="max_clips_per_run" min="1" max="10" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-bold focus:border-amber-500 focus:outline-none">
                        <span class="text-2xs text-slate-500 mt-1 block">Maximale Clips pro Durchlauf.</span>
                    </div>
                </div>

                <!-- Layout Schnellwahl -->
                <div class="bg-slate-950/70 p-3.5 rounded-md border border-slate-800 space-y-2">
                    <label class="block text-xs font-semibold text-slate-300">Standard Clip-Layout:</label>
                    <select id="cfg-streamer-layout" name="layout" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-amber-300 font-semibold focus:border-amber-500 focus:outline-none">
                        <option value="auto">Auto (KI Facecam-Scan)</option>
                        <option value="split_cam_top">Split-Screen (Cam oben + Gameplay unten)</option>
                        <option value="blur_stack">Keine Cam (Gameplay mit Blur-Hintergrund)</option>
                        <option value="single_916">Reines 9:16 Vollbild (IRL)</option>
                        <option value="custom">Eigener gespeicherter Rahmen</option>
                        <option value="top_left">Cam: Oben Links</option>
                        <option value="top_right">Cam: Oben Rechts</option>
                        <option value="bottom_left">Cam: Unten Links</option>
                        <option value="bottom_right">Cam: Unten Rechts</option>
                    </select>
                    <div id="cfg-streamer-custom-badge" class="hidden text-2xs text-emerald-400 bg-emerald-950/60 border border-emerald-800/60 px-2.5 py-1 rounded-md font-mono items-center gap-1.5">
                        <span>✓</span> <span>Eigener visueller Rahmen für diesen Streamer hinterlegt</span>
                    </div>
                </div>

                <!-- Test-Clip & Rahmenkonfiguration -->
                <div class="bg-gradient-to-br from-amber-950/40 via-slate-950 to-slate-900 border border-amber-500/40 p-4 rounded-md space-y-2.5 shadow-md">
                    <div class="flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg>
                        <div>
                            <span class="text-xs font-bold text-amber-300 block">Visueller Rahmen-Editor für diesen Streamer</span>
                            <span class="text-2xs text-slate-400">Lädt automatisch einen Test-Clip des Streamers herunter. Du richtest Cam und Gameplay ein und das Tool merkt sich die Rahmen dauerhaft.</span>
                        </div>
                    </div>
                    <button type="button" id="btn-load-streamer-sample" onclick="loadSampleClipForStreamer()" class="w-full py-2.5 px-4 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-zinc-950 font-bold text-xs rounded-lg transition flex items-center justify-center gap-2 shadow">
                        <span id="btn-sample-spinner" class="hidden w-3.5 h-3.5 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin inline-block"></span>
                        <span id="btn-sample-text">Test-Clip laden & Rahmen visuell einstellen</span>
                    </button>
                </div>

                <!-- Footer Actions -->
                <div class="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-800">
                    <button type="button" onclick="closeStreamerConfigModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition">Abbrechen</button>
                    <button type="submit" class="px-5 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs rounded-lg transition shadow">Speichern</button>
                </div>
            </form>
        </div>
    </div>

    <!-- POP-UP MODAL: Einstellungen & Autopilot -->
    <div id="settings-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden items-center justify-center p-4" style="display: none !important;" onclick="if (event.target === this) closeSettingsModal();">
        <div class="bg-slate-900 border border-slate-700/90 rounded-lg max-w-xl w-full overflow-hidden shadow-2xl flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-200">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/80">
                <div class="flex items-center gap-2.5">
                    <svg class="w-5 h-5 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                    <div>
                        <h3 class="text-base font-bold text-white">System & Autopilot Einstellungen</h3>
                        <p class="text-2xs text-slate-400">Prüfintervalle, Clip-Filter und Hardware anpassen</p>
                    </div>
                </div>
                <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>

            <form id="settings-form" onsubmit="return saveSettingsFromForm(event)" class="p-5 overflow-y-auto space-y-5">
                <!-- Autopilot Intervall Sektion -->
                <div class="bg-slate-950/70 border border-slate-800 p-4 rounded-md space-y-4">
                    <div class="flex items-center justify-between">
                        <div>
                            <span class="text-xs font-bold text-amber-400 uppercase tracking-wider block">Automatischer Autopilot</span>
                            <span class="text-2xs text-slate-400">Sucht im Hintergrund selbstständig nach neuen Clips</span>
                        </div>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" name="autopilot_enabled" class="sr-only peer" {% if settings.enabled %}checked{% endif %}>
                            <div class="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-500"></div>
                        </label>
                    </div>

                    <!-- Prüfintervall -->
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1.5">Prüf-Intervall der automatischen Prüfung:</label>
                        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
                            <button type="button" onclick="document.getElementById('setting-interval').value = 15" class="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 text-center font-mono">15 Min</button>
                            <button type="button" onclick="document.getElementById('setting-interval').value = 30" class="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 text-center font-mono">30 Min (Empf.)</button>
                            <button type="button" onclick="document.getElementById('setting-interval').value = 60" class="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 text-center font-mono">1 Stunde</button>
                            <button type="button" onclick="document.getElementById('setting-interval').value = 120" class="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 text-center font-mono">2 Stunden</button>
                        </div>
                        <div class="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2">
                            <span class="text-xs text-slate-400">Genaues Intervall:</span>
                            <input type="number" id="setting-interval" name="interval_minutes" value="{{ settings.interval_minutes }}" min="5" max="1440" class="w-20 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-amber-300 font-bold text-center">
                            <span class="text-xs text-slate-400">Minuten</span>
                        </div>
                    </div>
                </div>

                <!-- Zeitfenster & Fallback Sektion -->
                <div class="bg-slate-950/70 border border-slate-800 p-4 rounded-md space-y-3.5">
                    <span class="text-xs font-bold text-amber-400 uppercase tracking-wider block">Clip-Suche & Zeitfenster</span>

                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Standard-Zeitfenster auf Twitch:</label>
                        <select name="time_filter" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-amber-500 font-medium">
                            <option value="LAST_DAY" {% if settings.time_filter == 'LAST_DAY' %}selected{% endif %}>Letzte 24 Stunden (LAST_DAY) - Frischeste Clips</option>
                            <option value="LAST_WEEK" {% if settings.time_filter == 'LAST_WEEK' %}selected{% endif %}>Letzte 7 Tage (LAST_WEEK) - Große Auswahl</option>
                        </select>
                    </div>

                    <div class="flex items-start gap-3 pt-1">
                        <input type="checkbox" id="setting-fallback" name="fallback_to_week" class="mt-0.5 rounded bg-slate-800 border-slate-700 text-amber-500 focus:ring-0 w-4 h-4" {% if settings.fallback_to_week %}checked{% endif %}>
                        <label for="setting-fallback" class="text-xs text-slate-300 cursor-pointer">
                            <span class="font-bold text-white block">Intelligenter Wochen-Fallback</span>
                            <span class="text-slate-400 block text-2xs mt-0.5">Falls in den letzten 24h nicht genug Clips die Mindest-Views erreichen, restliche Plätze mit Top-Clips der Woche auffüllen. Frische Clips haben immer Vorrang!</span>
                        </label>
                    </div>

                    <div class="flex items-start gap-3 pt-1 border-t border-slate-800/80">
                        <input type="checkbox" id="setting-autorender" name="auto_render" class="mt-0.5 rounded bg-slate-800 border-slate-700 text-amber-500 focus:ring-0 w-4 h-4" {% if settings.auto_render %}checked{% endif %}>
                        <label for="setting-autorender" class="text-xs text-slate-300 cursor-pointer">
                            <span class="font-bold text-white block">Vollautomatisches Rendering</span>
                            <span class="text-slate-400 block text-2xs mt-0.5">Neu gefundene Clips sofort transkribieren & schneiden, statt sie nur in der Warteschlange abzulegen.</span>
                        </label>
                    </div>
                </div>

                <!-- Hardware & Video-Encoder Sektion -->
                <div class="bg-slate-950/70 border border-slate-800 p-4 rounded-md space-y-3">
                    <span class="text-xs font-bold text-amber-400 uppercase tracking-wider block">Hardware & Engine</span>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Video-Encoder:</label>
                            <select name="hardware_encoder" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-amber-500">
                                <option value="auto" {% if settings.hardware_encoder == 'auto' %}selected{% endif %}>Automatische Erkennung (Empfohlen)</option>
                                <option value="nvenc" {% if settings.hardware_encoder == 'nvenc' %}selected{% endif %}>NVIDIA NVENC (RTX/GTX)</option>
                                <option value="amf" {% if settings.hardware_encoder == 'amf' %}selected{% endif %}>AMD AMF (Radeon)</option>
                                <option value="qsv" {% if settings.hardware_encoder == 'qsv' %}selected{% endif %}>Intel QuickSync (QSV)</option>
                                <option value="cpu" {% if settings.hardware_encoder == 'cpu' %}selected{% endif %}>Software / CPU (libx264)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Whisper KI-Modell:</label>
                            <select name="whisper_model" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-amber-500">
                                <option value="tiny" {% if settings.whisper_model == 'tiny' %}selected{% endif %}>Tiny (Ultraschnell)</option>
                                <option value="base" {% if settings.whisper_model == 'base' %}selected{% endif %}>Base (Schnell)</option>
                                <option value="small" {% if settings.whisper_model == 'small' %}selected{% endif %}>Small (Empfohlen - Beste Balance)</option>
                                <option value="medium" {% if settings.whisper_model == 'medium' %}selected{% endif %}>Medium (Hohe Genauigkeit)</option>
                                <option value="large-v3" {% if settings.whisper_model in ['large', 'large-v3'] %}selected{% endif %}>Large v3 (Maximale Präzision)</option>
                                <option value="turbo" {% if settings.whisper_model == 'turbo' %}selected{% endif %}>Turbo (Schnell & Präzise)</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Footer Buttons -->
                <div class="flex items-center justify-end gap-3 pt-2">
                    <button type="button" onclick="closeSettingsModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition">
                        Abbrechen
                    </button>
                    <button type="submit" class="px-5 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold rounded-lg transition shadow-md flex items-center gap-2">
                        <span>Einstellungen speichern</span>
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- POP-UP MODAL: Update Assistent -->
    <div id="update-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden items-center justify-center p-4 select-none" style="display: none !important;">
        <div class="bg-slate-900 border border-amber-500/50 rounded-lg max-w-lg w-full overflow-hidden shadow-2xl flex flex-col p-6 animate-in fade-in zoom-in-95 duration-200">
            <div class="flex items-start justify-between mb-4 pb-3 border-b border-slate-800">
                <div class="flex items-center gap-3">
                    <svg class="w-7 h-7 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                    <div>
                        <h3 class="text-lg font-bold text-white flex items-center gap-2">
                            <span>Neues Update verfügbar!</span>
                            <span id="modal-update-ver" class="text-xs font-mono bg-amber-500/20 text-amber-400 border border-amber-500/40 px-2 py-0.5 rounded font-bold">v0.1.x</span>
                        </h3>
                        <p class="text-xs text-slate-400 mt-0.5">Aktuelle Version: <span class="font-mono text-slate-300">v{{ app_version }}</span></p>
                    </div>
                </div>
                <button onclick="closeUpdateModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-2 py-0.5 rounded hover:bg-slate-800 transition">&times;</button>
            </div>

            <div class="space-y-3 mb-5">
                <div class="bg-slate-950 p-3.5 rounded-md border border-slate-800/90 text-xs text-slate-300 max-h-48 overflow-y-auto space-y-1.5" id="modal-update-notes">
                    <p class="font-bold text-amber-400">Änderungen in dieser Version:</p>
                    <p class="text-slate-400 whitespace-pre-line" id="modal-update-notes-body">Lade Release-Details von GitHub...</p>
                </div>
                <div id="update-status-msg" class="text-xs text-center font-semibold text-slate-400"></div>
            </div>

            <div class="flex items-center justify-between gap-3 pt-2">
                <a id="modal-github-link" href="https://github.com/xNotLikex/clip-farming/releases/latest" target="_blank" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-bold text-slate-300 rounded-lg transition flex items-center gap-1.5">
                    <span>Auf GitHub ansehen</span>
                </a>
                <div class="flex items-center gap-2">
                    <button onclick="closeUpdateModal()" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-400 rounded-lg transition">Später</button>
                    <button onclick="performUpdate(this)" id="btn-perform-update" class="px-5 py-2 bg-gradient-to-r from-amber-500 to-amber-400 hover:from-amber-400 hover:to-amber-300 text-zinc-950 font-bold text-xs rounded-lg transition flex items-center gap-2 shadow-lg cursor-pointer">
                        <span>Jetzt 1-Klick aktualisieren</span>
                    </button>
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
                    <svg class="w-6 h-6 inline-block text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg>
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
                            <span>Split-Screen</span> (Cam oben + Gameplay unten)
                        </button>
                        <button type="button" onclick="switchCropMode('single_916')" id="btn-mode-single" 
                            class="flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300">
                            <span>Reines 9:16 Vollbild</span> (IRL / Einzelfokus ohne Trennung)
                        </button>
                    </div>

                    <!-- Stage Container (Aspect 16:9) -->
                    <div id="crop-stage-container" class="relative w-full aspect-video bg-black rounded overflow-hidden border-2 border-slate-700 shadow-2xl flex items-center justify-center select-none">
                        <!-- Instant Visible 16:9 Stage Image to guarantee frame is never black -->
                        <img id="crop-stage-img" src="" class="absolute inset-0 w-full h-full object-contain pointer-events-none select-none z-0" alt="">

                        <!-- Video element (muted for instant scrubbing) -->
                        <video id="crop-stage-video" muted playsinline preload="auto" class="absolute inset-0 w-full h-full object-contain pointer-events-none select-none z-10"></video>

                        <!-- Draggable Overlay Boxes Container -->
                        <div id="crop-overlay-layer" class="absolute inset-0 select-none pointer-events-none z-20">
                            <!-- 🟩 Facecam Box (Feste 3:2 Proportion, frei verschiebbar & stufenlos skalierbar) -->
                            <div id="crop-box-cam" class="absolute select-none border-2 border-emerald-400 bg-emerald-500/20 shadow-sm rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:border-zinc-500 pointer-events-auto" style="left: 68%; top: 58%; width: 28%; height: 35%; display: flex;" title="Verschieben (Ziehen) oder Größe ändern (Ecken ziehen / Mausrad)">
                                <div class="absolute -top-6 left-0 bg-emerald-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>Facecam</span>
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
                                    <span>Gameplay</span>
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
                                    <span>9:16 IRL Bildausschnitt</span>
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
                            <button onclick="seekCropVideo(-2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden zurück">-2s</button>
                            <button onclick="toggleCropVideoPlay()" id="crop-play-btn" class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-200 rounded-lg transition">Pause</button>
                            <button onclick="seekCropVideo(2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden vor">+2s</button>
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
                                    <span class="text-xs font-bold text-emerald-400 min-w-[100px]">Cam-Position:</span>
                                    <button onclick="applyPreset('cam_br')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">Unten Rechts</button>
                                    <button onclick="applyPreset('cam_tl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">Oben Links</button>
                                    <button onclick="applyPreset('cam_tr')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">Oben Rechts</button>
                                    <button onclick="applyPreset('cam_bl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">Unten Links</button>
                                    <button onclick="detectFacecamInCropModal()" id="btn-crop-detect" class="px-3 py-1 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 hover:text-white text-xs font-bold rounded-lg transition shadow flex items-center gap-1">
                                         KI Auto-Erkennen
                                    </button>
                                    <button type="button" onclick="switchCropMode('single_916')" id="btn-crop-toggle-cam" class="px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition" title="Facecam entfernen und zu reinem 9:16 Vollbild (1 Rahmen) wechseln">
                                        Keine Cam (Vollbild / 1 Rahmen)
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
                                    <button onclick="applyPreset('game_left')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">Links</button>
                                    <button onclick="applyPreset('game_right')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">Rechts</button>
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
                            <span class="text-xs font-bold text-emerald-400 min-w-[110px]">9:16 Vollbild:</span>
                            <button type="button" onclick="applyPreset('single_center')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">Mitte (Zentriert)</button>
                            <button type="button" onclick="applyPreset('single_left')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">Links</button>
                            <button type="button" onclick="applyPreset('single_right')" class="px-3 py-1.5 bg-slate-800 hover:bg-zinc-700 border border-slate-700 hover:border-zinc-500 text-xs font-bold rounded-lg text-slate-200 transition">Rechts</button>
                            <button type="button" onclick="switchCropMode('split')" class="px-3 py-1.5 bg-emerald-950/90 hover:bg-emerald-900 border border-emerald-600/80 text-xs font-bold rounded-lg text-emerald-300 hover:text-white transition flex items-center gap-1.5 shadow" title="Zurück zu 2 Rahmen (Facecam oben + Gameplay unten)">
                                <span>Facecam hinzufügen</span> (Split-Screen)
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
                <div class="flex flex-wrap items-center gap-2">
                    <button type="button" onclick="if (window.saveAsDefaultStreamerLayout) window.saveAsDefaultStreamerLayout();" class="px-3.5 py-2 bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-600/80 text-emerald-300 font-bold text-xs rounded transition flex items-center gap-1.5 shadow" title="Speichert diesen Zuschnitt als Standard-Layout für alle zukünftigen Clips dieses Streamers">
                        <span>Als Standard für Streamer merken</span>
                    </button>
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

    <script src="/app.js?v={{ app_version }}"></script>
</body>
</html>
"""


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
        mtime = 0
        if thumb_file.exists():
            mtime = int(thumb_file.stat().st_mtime)
        elif short_file.exists():
            mtime = int(short_file.stat().st_mtime)
        else:
            mtime = int(time.time())

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

    account_status = account_manager.get_status()
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
        "account_status": account_status,
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
                    except Exception:
                        pass
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
            time.sleep(20)

autopilot_thread = threading.Thread(target=autopilot_background_worker, daemon=True)
autopilot_thread.start()

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
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    return make_svg_poster("Twitch Rohdatei", clip_id)

@app.route("/video/<clip_id>")
def serve_video(clip_id):
    video_path = _safe_resolve_clip_path(SHORTS_OUTPUT_DIR, f"short_{clip_id}", ".mp4")
    if video_path and video_path.exists():
        return send_file(video_path, mimetype="video/mp4", conditional=True)
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
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", str(target_dir)])
        except Exception:
            pass

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

    if "transcript" in request.form:
        txt_path = RAW_CLIPS_DIR / f"{clip_id}_transcript.txt"
        txt_path.write_text(edited_transcript, encoding="utf-8")

    update_clip_status(clip_id, "ready", ai_title=title)

    if action == "publish_now":
        publish_clip_now(clip_id)
        return _finish_save("studio")

    elif action == "schedule":
        # Einzelnen Clip in Zeitplan einreihen
        schedule_single_clip(clip_id)
        return _finish_save("planner")

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
    print("\n" + "="*70)
    print(f"  CLIP-FARMING STUDIO GESTARTET!")
    print(f"  👉 Öffne im Browser: http://localhost:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

if __name__ == "__main__":
    start_studio()
