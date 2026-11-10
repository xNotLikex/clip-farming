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
    SHORTS_OUTPUT_DIR, RAW_CLIPS_DIR, METADATA_OUTPUT_DIR, load_config,
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
    <title>Clip-Farming Mission Control</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0b0f19; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
        .tab-btn.active { border-bottom: 2px solid #a855f7; color: #c084fc; font-weight: 700; }
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
</head>
<body class="p-4 md:p-8">
    <div class="max-w-7xl mx-auto space-y-6">
        
        <!-- Header & Live Status Bar -->
        <header class="flex flex-col lg:flex-row justify-between items-start lg:items-center pb-6 border-b border-slate-800 gap-4">
            <div>
                <div class="flex items-center gap-3">
                    <h1 class="text-3xl font-black tracking-tight bg-gradient-to-r from-purple-400 via-pink-400 to-indigo-400 bg-clip-text text-transparent">
                        🎬 CLIP-FARMING MISSION CONTROL
                    </h1>
                    <span id="live-indicator" class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-slate-800 text-slate-300 border border-slate-700 shadow-sm">
                        <span class="w-2 h-2 rounded-full bg-slate-400" id="live-dot"></span>
                        <span id="live-status-text">Standby</span>
                    </span>
                </div>
                <p id="live-task-desc" class="text-slate-400 text-sm mt-1">Bereit zur Ausführung</p>
            </div>

            <!-- Quick Action Buttons -->
            <div class="flex flex-wrap items-center gap-3">
                <button onclick="openStreamerModal()" class="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm rounded-xl transition text-slate-200 shadow">
                    <span>👥</span> Streamer verwalten ({{ streamers|length }})
                </button>
                <button onclick="triggerRun()" id="btn-trigger" class="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 font-bold text-sm rounded-xl shadow-lg shadow-purple-500/20 transition transform active:scale-95 text-white">
                    <span>⚡</span> Neue Clips auf Twitch suchen
                </button>
            </div>
        </header>

        <!-- LIVE RENDER PROGRESS CARD (Wird eingeblendet wenn aktiv) -->
        <div id="render-progress-card" class="hidden bg-gradient-to-r from-purple-950/70 via-slate-900 to-indigo-950/70 border border-purple-500/50 rounded-2xl p-5 shadow-2xl animate-pulse-subtle">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-3">
                <div class="flex items-center gap-2.5">
                    <span class="w-3 h-3 rounded-full bg-pink-500 animate-ping"></span>
                    <span id="render-progress-title" class="text-sm font-bold text-white tracking-wide">Rendern aktiv...</span>
                </div>
                <div class="flex items-center gap-3 font-mono">
                    <span id="render-speed-badge" class="text-xs bg-purple-900/80 text-purple-200 px-2.5 py-0.5 rounded-full border border-purple-700">NVENC</span>
                    <span id="render-eta-text" class="text-xs font-semibold text-amber-300 bg-amber-950/60 px-2.5 py-0.5 rounded-full border border-amber-800/60">Noch ca. --s</span>
                    <span id="render-percent-text" class="text-lg font-black text-white">0%</span>
                </div>
            </div>
            <!-- Progress Bar -->
            <div class="w-full bg-slate-950 rounded-full h-3.5 overflow-hidden p-0.5 border border-slate-700/80 shadow-inner">
                <div id="render-progress-bar" class="bg-gradient-to-r from-purple-500 via-pink-500 to-emerald-400 h-full rounded-full transition-all duration-300 shadow-lg" style="width: 0%"></div>
            </div>
        </div>

        <!-- KPI Cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl cursor-pointer hover:border-amber-500/50 transition" onclick="switchTab('queue')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">1. Warteschlange</span>
                <span class="text-3xl font-black text-amber-400 mt-1 block">{{ counts.harvested }}</span>
                <span class="text-xs text-slate-500 mt-1 block">Rohdateien gespeichert</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl cursor-pointer hover:border-purple-500/50 transition" onclick="switchTab('studio')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">2. Studio & Freigabe</span>
                <span class="text-3xl font-black text-purple-400 mt-1 block">{{ counts.ready }}</span>
                <span class="text-xs text-slate-500 mt-1 block">9:16 Shorts bereit</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl cursor-pointer hover:border-sky-500/50 transition" onclick="switchTab('planner')">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider block">3. Veröffentlichungs-Plan</span>
                <div class="flex items-baseline gap-2 mt-1">
                    <span class="text-3xl font-black text-sky-400">{{ counts.scheduled }}</span>
                    <span class="text-sm font-bold text-emerald-400">/ {{ counts.published }} online</span>
                </div>
                <span class="text-xs text-slate-500 mt-1 block">Zeitgesteuerte Veröffentlichung</span>
            </div>
            <div class="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl cursor-pointer hover:border-pink-500/50 transition" onclick="switchTab('accounts')">
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
        <div class="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4">
            <div class="flex justify-between items-center cursor-pointer" onclick="toggleLogs()">
                <div class="flex items-center gap-2">
                    <span class="text-xs font-bold uppercase tracking-wider text-purple-400">📡 Live Activity Feed</span>
                    <span id="log-count" class="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full">0 Einträge</span>
                </div>
                <span id="log-toggle-icon" class="text-slate-400 text-xs">▼ Anzeigen</span>
            </div>
            <div id="log-box" class="mt-3 hidden bg-slate-950 p-4 rounded-xl font-mono text-xs text-slate-300 max-h-48 overflow-y-auto space-y-1 border border-slate-800/50">
                <div class="text-slate-500">Warte auf Aktionen...</div>
            </div>
        </div>

        <!-- Tabs Navigation -->
        <div class="flex flex-wrap gap-4 border-b border-slate-800 text-sm font-semibold">
            <button onclick="switchTab('queue')" id="tab-queue-btn" class="tab-btn pb-3 active flex items-center gap-2">
                📥 1. Warteschlange ({{ counts.harvested }})
            </button>
            <button onclick="switchTab('studio')" id="tab-studio-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                🎬 2. Studio & Freigabe ({{ counts.ready }})
            </button>
            <button onclick="switchTab('planner')" id="tab-planner-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                🚀 3. Veröffentlichungs-Planer ({{ counts.scheduled }})
            </button>
            <button onclick="switchTab('accounts')" id="tab-accounts-btn" class="tab-btn pb-3 text-slate-400 hover:text-slate-200 flex items-center gap-2">
                🔗 4. Konten verknüpfen
            </button>
        </div>

        <!-- TAB 1: WARTESCHLANGE -->
        <div id="tab-queue" class="tab-content space-y-4">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center p-4 bg-slate-950/70 border-b border-slate-800 gap-3">
                    <div>
                        <span class="text-sm font-bold text-slate-200">📥 {{ counts.harvested }} Roh-Clips lokal auf der Festplatte</span>
                        <span class="text-xs text-slate-400 block">💡 Klicke auf eine Zeile, um das Video vor dem Schneiden abzuspielen.</span>
                    </div>
                    {% if counts.harvested > 0 %}
                    <div class="flex flex-wrap items-center gap-2.5">
                        {% if older_queue_count > 0 %}
                        <form action="/queue/delete-older" method="POST" class="inline" onsubmit="return confirm('Wirklich alle {{ older_queue_count }} Roh-Clips von gestern und älter aus der Warteschlange löschen?\n\n(Clips von heute bleiben vollständig erhalten)');">
                            <button type="submit" class="px-4 py-2.5 bg-rose-950/80 hover:bg-rose-900 border border-rose-800/80 font-bold text-xs rounded-xl shadow-lg shadow-rose-950/40 text-rose-300 hover:text-white flex items-center gap-2 transition active:scale-95" title="Löscht alle {{ older_queue_count }} Roh-Clips von gestern & älter">
                                <span>🗑️</span> Gestern & älter löschen ({{ older_queue_count }})
                            </button>
                        </form>
                        {% endif %}
                        <button onclick="processAll()" id="btn-process-all" class="px-4 py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 font-bold text-xs rounded-xl shadow-lg shadow-purple-500/20 text-white flex items-center gap-2">
                            <span>⚡</span> Alle Warteschlangen-Clips ins Studio übernehmen
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
                        <tbody class="divide-y divide-slate-800/80">
                            {% for clip in queue_clips %}
                            <tr onclick="openRawPreview('{{ clip.clip_id }}', '{{ clip.streamer|e }}', '{{ clip.original_title|e }}', '{{ clip.view_count }}', '{{ '%.0f'|format(clip.duration) }}', '{{ clip.created_ago|e }}', '{{ clip.created_full|e }}')"
                                class="hover:bg-slate-800/60 cursor-pointer transition group">
                                <td class="py-3.5 px-4 text-center whitespace-nowrap">
                                    <span class="w-8 h-8 rounded-full bg-slate-800 group-hover:bg-purple-600 flex items-center justify-center text-xs text-white transition shadow">
                                        ▶
                                    </span>
                                </td>
                                <td class="py-3.5 px-4 font-bold text-purple-400 whitespace-nowrap">{{ clip.streamer }}</td>
                                <td class="py-3.5 px-4 font-semibold text-slate-200 group-hover:text-purple-300 transition">
                                    <div>{{ clip.original_title }}</div>
                                    <span class="text-xs text-slate-500 font-normal">Klicken zum Vorschauen</span>
                                </td>
                                <td class="py-3.5 px-4 whitespace-nowrap" title="{{ clip.created_full }}">
                                    <div class="flex items-center gap-1.5 text-xs text-slate-300 font-medium">
                                        <span>📅</span> {{ clip.created_ago }}
                                    </div>
                                    {% if clip.created_full %}
                                    <span class="text-[11px] text-slate-500 block">{{ clip.created_full }}</span>
                                    {% endif %}
                                </td>
                                <td class="py-3.5 px-4 text-slate-300 font-semibold whitespace-nowrap">👁️ {{ clip.view_count }}</td>
                                <td class="py-3.5 px-4 text-slate-400 whitespace-nowrap">{{ "%.0f"|format(clip.duration) }}s</td>
                                <td class="py-3.5 px-4 whitespace-nowrap">
                                    <span class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 font-medium whitespace-nowrap shadow-sm">
                                        ✓ Lokal geladen
                                    </span>
                                </td>
                                <td class="py-3.5 px-4 text-right whitespace-nowrap" onclick="event.stopPropagation()">
                                    <div class="flex items-center justify-end gap-2">
                                        <form action="/process-one/{{ clip.clip_id }}" method="POST" class="inline">
                                            <button type="submit" class="px-3.5 py-1.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 font-bold text-xs rounded-lg shadow text-white transition active:scale-95 whitespace-nowrap">
                                                ✂️ In Studio übernehmen
                                            </button>
                                        </form>
                                        <form action="/queue/delete/{{ clip.clip_id }}" method="POST" class="inline" onsubmit="return confirm('Clip unwiderruflich löschen? Er wird NIE wieder von Twitch heruntergeladen.');">
                                            <button type="submit" class="p-1.5 px-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 text-rose-300 font-bold text-xs rounded-lg transition" title="Clip löschen & dauerhaft ignorieren">
                                                🗑️
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
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-2xl gap-3">
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
                    <button type="submit" class="px-4 py-2 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white font-bold text-xs rounded-xl shadow transition">
                        📅 Alle gestaffelt einplanen
                    </button>
                </form>
            </div>

            <!-- Streamer Filter Bar (Sortiert nach Streamer) -->
            <div class="flex flex-wrap items-center gap-2 bg-slate-900/80 border border-slate-800 p-3.5 rounded-2xl shadow">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">🔍 Filter nach Streamer:</span>
                <button onclick="filterStudioByStreamer('all')" id="pill-all" class="streamer-pill active px-3.5 py-1.5 rounded-xl text-xs font-bold bg-purple-600 text-white transition shadow">
                    Alle ({{ ready_clips|length }})
                </button>
                {% for st_name, count in streamer_counts.items() %}
                <button onclick="filterStudioByStreamer('{{ st_name|lower }}')" id="pill-{{ st_name|lower }}" class="streamer-pill px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition">
                    {{ st_name }} ({{ count }})
                </button>
                {% endfor %}
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
                {% for clip in ready_clips %}
                <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col hover:border-slate-700 transition-all duration-300 studio-clip-card {% if clip.is_manually_published %}opacity-40 grayscale hover:grayscale-0 hover:opacity-95 border-emerald-900/80 bg-slate-950/90{% endif %}" id="card-{{ clip.clip_id }}" data-streamer="{{ clip.streamer|lower }}">
                    <!-- Card Header: Streamer & Veröffentlicht-Checkbox -->
                    <div class="flex justify-between items-center bg-slate-950/90 px-4 py-2.5 border-b border-slate-800">
                        <div class="flex items-center gap-2">
                            <span class="bg-purple-600/90 text-xs font-bold px-2.5 py-1 rounded-md shadow text-white">
                                {{ clip.streamer }}
                            </span>
                            {% if clip.created_ago %}
                            <span class="text-[11px] text-slate-400 font-medium whitespace-nowrap" title="{{ clip.created_full }}">
                                📅 {{ clip.created_ago }}
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
                        <video controls preload="metadata" class="w-full h-full object-contain">
                            <source src="/video/{{ clip.clip_id }}" type="video/mp4">
                        </video>
                        {% else %}
                        <div class="text-center p-6 text-slate-500">
                            <span class="text-4xl block mb-2 animate-bounce">⏳</span>
                            Video wird gerendert...
                        </div>
                        {% endif %}
                        
                        <span class="absolute top-3 right-3 bg-slate-900/80 text-xs text-slate-300 font-semibold px-2 py-1 rounded-md backdrop-blur">
                            👁️ {{ clip.view_count }}
                        </span>

                        {% if clip.has_video %}
                        <a href="/download/short/{{ clip.clip_id }}" 
                            class="absolute bottom-3 right-3 bg-slate-900/90 hover:bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-lg border border-slate-700/80 backdrop-blur transition flex items-center gap-1.5"
                            title="Fertiges 9:16 Short in HQ auf deinen PC herunterladen">
                            <span>💾</span> HQ Download
                        </a>
                        {% endif %}
                    </div>

                    <!-- Edit Form -->
                    <form action="/save/{{ clip.clip_id }}" method="POST" class="p-5 flex-1 flex flex-col justify-between gap-4">
                        <div class="space-y-3">
                            <!-- Sticker Hook Text -->
                            <div>
                                <label class="block text-xs font-semibold text-pink-400 uppercase tracking-wider mb-1 flex justify-between">
                                    <span>💬 TikTok / Shorts Sprechblasen-Hook</span>
                                    <span class="text-slate-500 font-normal">Mitte</span>
                                </label>
                                <input type="text" name="sticker_text" value="{{ clip.sticker_text }}" 
                                    placeholder="z. B. Gtastys ki hittet double mace"
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-pink-500">
                            </div>

                            <!-- Video Title -->
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                                    📝 Titel (YouTube / TikTok)
                                </label>
                                <input type="text" name="title" value="{{ clip.title }}" 
                                    class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500">
                            </div>

                            <!-- Untertitel-Platzierung -->
                            <div>
                                <label class="block text-xs font-semibold text-amber-400 uppercase tracking-wider mb-1">
                                    💬 Untertitel-Platzierung
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
                                <label class="block text-xs font-semibold text-purple-400 uppercase tracking-wider mb-1">
                                    📐 Video-Layout & Aufteilung
                                </label>
                                <select name="layout_mode" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500">
                                    <option value="auto" {% if clip.layout_mode == 'auto' %}selected{% endif %}>🤖 Automatisch (KI erkennt Facecam vs. IRL)</option>
                                    <option value="custom" {% if clip.layout_mode == 'custom' %}selected{% endif %}>🎯 Benutzerdefiniert (Visuelle Rahmen)</option>
                                    <option value="single_916" {% if clip.layout_mode == 'single_916' %}selected{% endif %}>📱 Reines 9:16 Vollbild (IRL / Einzelfokus)</option>
                                    <option value="split_cam_top" {% if clip.layout_mode == 'split_cam_top' %}selected{% endif %}>✂️ Split-Screen (Cam oben, Gameplay unten)</option>
                                    <option value="blur_stack" {% if clip.layout_mode == 'blur_stack' %}selected{% endif %}>🌫️ Blur-Stack (IRL / Vollbild mit unscharfem Hintergrund)</option>
                                </select>
                                <button type="button" onclick="openCropModal('{{ clip.clip_id }}', '{{ clip.streamer }}', '{{ clip.title }}')" 
                                    class="w-full mt-2 py-2 px-3 bg-gradient-to-r from-purple-900/70 to-indigo-900/70 hover:from-purple-800 hover:to-indigo-800 border border-purple-500/60 hover:border-purple-400 text-purple-200 hover:text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow">
                                    <span>🎯</span> Bildausschnitt anpassen (Split-Cam oder IRL 9:16)
                                </button>
                            </div>

                            <!-- Cam-Filter / Effekte (Snapchat / TikTok Style) -->
                            <div>
                                <label class="block text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1 flex justify-between">
                                    <span>🎭 Cam-Filter / Effekt (Snapchat-Style)</span>
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
                                class="w-full py-2.5 px-4 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 font-bold text-sm rounded-lg shadow-md transition flex items-center justify-center gap-2 text-white active:scale-95">
                                <span>⚡</span> Speichern & Neu Rendern
                            </button>

                            {% if clip.has_video %}
                            <a href="/download/short/{{ clip.clip_id }}" 
                                class="w-full py-2.5 px-4 bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-700/60 font-bold text-xs rounded-lg transition flex items-center justify-center gap-2 text-emerald-300 hover:text-white shadow">
                                <span>💾</span> HQ Video herunterladen (.mp4)
                            </a>
                            {% endif %}

                            <div class="grid grid-cols-2 gap-2">
                                <button type="submit" name="action" value="schedule" 
                                    class="py-2 px-3 bg-sky-700 hover:bg-sky-600 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                                    📅 Zeitplan
                                </button>
                                <button type="submit" name="action" value="publish_now" 
                                    class="py-2 px-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                                    🚀 Sofort Posten
                                </button>
                            </div>
                            <div class="text-right">
                                <button type="submit" name="action" value="delete" 
                                    onclick="return confirm('Clip wirklich löschen?');"
                                    class="text-xs text-rose-400 hover:text-rose-300 transition">
                                    🗑️ Löschen & Ignorieren
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center">
                <span class="text-5xl block mb-3">🎬</span>
                <h3 class="text-lg font-bold text-slate-300">Noch keine fertig gerenderten Shorts im Studio</h3>
                <p class="text-sm text-slate-500 mt-1 max-w-md mx-auto">
                    Klicke im Reiter <strong>„1. Warteschlange“</strong> bei deinen Wunsch-Clips auf <strong>„✂️ In Studio übernehmen“</strong>!
                </p>
            </div>
            {% endif %}
        </div>

        <!-- TAB 3: VERÖFFENTLICHUNGS-PLANER & HISTORIE -->
        <div id="tab-planner" class="tab-content hidden space-y-6">
            
            <!-- Planer Einstellungen Card -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h3 class="text-base font-bold text-white flex items-center gap-2">
                        <span>⏰</span> Automatische Veröffentlichungs-Warteschlange (Drip-Feed)
                    </h3>
                    <p class="text-xs text-slate-400 mt-1">
                        Verhindert Spam: Eingeplante Clips werden automatisch im gewählten Zeitabstand nacheinander auf YouTube Shorts & TikTok hochgeladen.
                    </p>
                </div>
                <form action="/api/schedule/set-interval" method="POST" class="flex items-center gap-2">
                    <span class="text-xs font-semibold text-slate-300">Standard-Intervall:</span>
                    <select name="interval_minutes" onchange="this.form.submit()" class="bg-slate-800 border border-slate-700 text-xs text-white rounded-lg px-3 py-2 font-semibold">
                        <option value="15" {% if account_status.publishing_interval == 15 %}selected{% endif %}>⏱️ 15 Minuten</option>
                        <option value="30" {% if account_status.publishing_interval == 30 %}selected{% endif %}>⏱️ 30 Minuten (Empfohlen)</option>
                        <option value="45" {% if account_status.publishing_interval == 45 %}selected{% endif %}>⏱️ 45 Minuten</option>
                        <option value="60" {% if account_status.publishing_interval == 60 %}selected{% endif %}>⏱️ 1 Stunde</option>
                        <option value="120" {% if account_status.publishing_interval == 120 %}selected{% endif %}>⏱️ 2 Stunden</option>
                    </select>
                </form>
            </div>

            <!-- 1. Geplante Clips (Warteschlange) -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
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
                        <tbody class="divide-y divide-slate-800/80">
                            {% for clip in scheduled_clips %}
                            <tr class="hover:bg-slate-800/40 transition">
                                <td class="py-3.5 px-4 font-bold text-purple-400">{{ clip.streamer }}</td>
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
                                                🚀 Jetzt posten
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
                                <td colspan="5" class="py-8 text-center text-slate-500">Keine Clips im Veröffentlichungs-Zeitplan. Klicke im Studio auf „📅 Zeitplan“!</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- 2. Historie (Bereits veröffentlicht) -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
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
                        <tbody class="divide-y divide-slate-800/80">
                            {% for clip in published_clips %}
                            <tr class="hover:bg-slate-800/40 transition">
                                <td class="py-3.5 px-4 font-bold text-purple-400">{{ clip.streamer }}</td>
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
            <div class="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="flex items-center gap-3">
                    <span class="text-3xl">🔗</span>
                    <div>
                        <h2 class="text-lg font-black text-white">Social Media Konten verknüpfen</h2>
                        <p class="text-xs text-slate-400">Verbinde deine Kanäle, damit gerenderte Shorts automatisch nach Zeitplan oder auf Knopfdruck veröffentlicht werden.</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-xs font-bold px-3 py-1.5 rounded-xl {% if account_status.youtube.is_connected %}bg-emerald-950 text-emerald-400 border border-emerald-800{% else %}bg-slate-800 text-slate-400{% endif %}">
                        YouTube: {% if account_status.youtube.is_connected %}✓ Verbunden{% else %}✗ Getrennt{% endif %}
                    </span>
                    <span class="text-xs font-bold px-3 py-1.5 rounded-xl {% if account_status.tiktok.is_connected %}bg-emerald-950 text-emerald-400 border border-emerald-800{% else %}bg-slate-800 text-slate-400{% endif %}">
                        TikTok: {% if account_status.tiktok.is_connected %}✓ Verbunden{% else %}✗ Getrennt{% endif %}
                    </span>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <!-- Card 1: YouTube Shorts -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
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
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                🟢 Verbunden
                            </span>
                            {% elif account_status.youtube.has_secrets %}
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-amber-950 text-amber-400 border border-amber-800">
                                🟡 Secrets bereit
                            </span>
                            {% else %}
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-slate-800 text-slate-400 border border-slate-700">
                                ⚪ Nicht eingerichtet
                            </span>
                            {% endif %}
                        </div>

                        {% if account_status.youtube.is_connected %}
                        <div class="p-4 bg-emerald-950/40 border border-emerald-800/50 rounded-xl space-y-2">
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
                        <div class="p-4 bg-red-950/40 border border-red-500/50 rounded-xl space-y-3 text-center">
                            <span class="text-xs font-bold text-red-300 block">Secrets hinterlegt! Letzter Schritt:</span>
                            <button type="button" onclick="startYouTubeOAuthLogin()" id="btn-yt-login"
                                class="w-full py-3 bg-gradient-to-r from-red-600 via-rose-600 to-red-600 hover:from-red-500 hover:to-rose-500 font-bold text-sm rounded-xl text-white flex items-center justify-center gap-2 shadow-lg shadow-red-500/25 transition transform active:scale-95">
                                <span>🚀</span> Jetzt mit Google / YouTube einloggen
                            </button>
                            <div id="yt-login-status-box" class="hidden p-3 bg-slate-900/95 border border-red-500/60 rounded-xl text-xs font-semibold text-red-200 flex items-center justify-center gap-2">
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
                                <a href="https://console.cloud.google.com/apis/credentials/wizard" target="_blank" class="text-2xs text-purple-400 hover:text-purple-300 underline flex items-center gap-1">
                                    <span>↗</span> Google Cloud Wizard öffnen
                                </a>
                            </div>

                            <form action="/api/accounts/youtube/save-credentials" method="POST" class="space-y-2 bg-slate-950/70 p-3 rounded-xl border border-slate-800">
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
                                    <input type="file" name="secrets_file" accept=".json" class="w-full text-xs text-slate-400 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-2xs file:font-bold file:bg-purple-600 file:text-white cursor-pointer">
                                    <button type="submit" class="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-2xs font-bold rounded text-slate-300">JSON speichern</button>
                                </form>
                            </details>

                            <!-- 3-Schritte Mini-Anleitung -->
                            <div class="text-2xs text-slate-400 bg-slate-950/40 p-2.5 rounded-xl border border-slate-800/80 space-y-1">
                                <div class="font-bold text-slate-300">30-Sekunden Schnell-Anleitung:</div>
                                <div>1. In der <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" class="text-purple-400 underline">Google Cloud Console</a> die <strong>YouTube Data API v3</strong> aktivieren.</div>
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
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
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
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                🟢 Session aktiv
                            </span>
                            {% else %}
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-slate-800 text-slate-400 border border-slate-700">
                                ⚪ Nicht verknüpft
                            </span>
                            {% endif %}
                        </div>

                        {% if account_status.tiktok.is_connected %}
                        <!-- TikTok bereits verbunden -->
                        <div class="p-5 bg-emerald-950/40 border border-emerald-800/60 rounded-2xl text-center space-y-2">
                            <div class="text-3xl">✅</div>
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
                        <div class="p-4 bg-gradient-to-r from-pink-950/70 via-purple-950/60 to-pink-950/70 border border-pink-500/50 rounded-2xl text-center shadow-lg">
                            <span class="text-2xs font-black text-pink-300 uppercase tracking-wider block mb-1">⭐ Automatische 1-Klick Methode (Empfohlen):</span>
                            <p class="text-xs text-slate-300 mb-3">Öffnet automatisch ein Login-Fenster. Logge dich einfach ein (z. B. <strong>QR-Code mit deiner Handy-TikTok-App scannen</strong>). Das Tool verbindet sich dann automatisch!</p>
                            
                            <button type="button" onclick="startTikTokBrowserLogin()" id="btn-tt-browser-login"
                                class="w-full py-3 bg-gradient-to-r from-pink-600 via-rose-600 to-purple-600 hover:from-pink-500 hover:to-purple-500 text-white font-black text-xs sm:text-sm rounded-xl shadow-lg shadow-pink-500/30 transition transform active:scale-95 flex items-center justify-center gap-2">
                                <span>🌐</span> TikTok im Browserfenster verbinden (QR-Code / Login)
                            </button>

                            <div id="tt-browser-status-box" class="hidden mt-3 p-3 bg-slate-900/95 border border-pink-500/60 rounded-xl text-xs font-semibold text-pink-200 flex items-center justify-center gap-2">
                                <span class="animate-spin text-base">⏳</span>
                                <span id="tt-browser-status-text">Warte auf Browser-Login...</span>
                            </div>
                        </div>
                        {% endif %}

                        <!-- Collapsible: Manuelle Alternative -->
                        <details class="text-2xs text-slate-400">
                            <summary class="cursor-pointer hover:text-slate-300 font-semibold mb-2">⚙️ Alternative: Manuelle sessionid Eingabe (Entwicklertools F12)...</summary>
                            
                            <div class="space-y-3 bg-slate-950/70 p-3 rounded-xl border border-slate-800">
                                <div class="text-2xs text-slate-400 space-y-1">
                                    <p class="text-slate-300 font-bold">So findest du das Cookie:</p>
                                    <ol class="list-decimal list-inside space-y-0.5">
                                        <li>Öffne <a href="https://www.tiktok.com" target="_blank" class="text-pink-400 underline">tiktok.com</a> und logge dich ein.</li>
                                        <li>Drücke <strong>F12</strong> &rarr; Tab <strong>Anwendung / Cookies</strong>.</li>
                                        <li>Kopiere den Wert von <code>sessionid</code> und füge ihn unten ein:</li>
                                    </ol>
                                </div>

                                <form action="/api/accounts/tiktok/save-session" method="POST" class="space-y-2">
                                    <input type="password" name="session_id" placeholder="z. B. 7a8f9c0e1b2d3..." value="{{ account_status.tiktok.session_id_preview }}"
                                        class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-pink-500 font-mono">
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
    <div id="preview-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-4xl w-full overflow-hidden shadow-2xl animate-fade-in flex flex-col max-h-[90vh]">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/60">
                <div>
                    <span id="modal-streamer" class="text-xs font-bold text-purple-400 uppercase tracking-wider block">STREAMER</span>
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
                    <a id="modal-download-raw" href="" class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-xs text-slate-200 rounded-xl transition flex items-center gap-1.5" title="Rohdatei direkt herunterladen">
                        <span>💾</span> Rohdatei laden
                    </a>
                    <button type="button" onclick="closePreviewModal(); openCropModal(currentPreviewClipId, currentPreviewStreamer, currentPreviewTitle);" class="px-4 py-2.5 bg-indigo-900/80 hover:bg-indigo-800 border border-indigo-600 font-bold text-xs text-indigo-200 hover:text-white rounded-xl transition flex items-center gap-1.5 shadow" title="Cam & Gameplay Rahmen visuell festlegen">
                        <span>🎯</span> Zuschnitt festlegen
                    </button>
                    <form id="modal-delete-form" action="" method="POST" class="inline" onsubmit="return confirm('Clip unwiderruflich löschen? Er wird NIE wieder von Twitch heruntergeladen.');">
                        <button type="submit" class="px-4 py-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 font-bold text-xs text-rose-300 rounded-xl transition">
                            🗑️ Clip löschen
                        </button>
                    </form>
                    <form id="modal-process-form" action="" method="POST" class="inline">
                        <button type="submit" class="px-5 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 font-bold text-xs rounded-xl shadow-lg shadow-purple-500/20 text-white flex items-center gap-2 transition active:scale-95">
                            ✂️ Jetzt in Studio übernehmen & schneiden
                        </button>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- POP-UP MODAL: Streamer verwalten & hinzufügen -->
    <div id="streamer-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md z-50 hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 border border-slate-700/90 rounded-2xl max-w-2xl w-full overflow-hidden shadow-2xl animate-fade-in flex flex-col max-h-[90vh]">
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/70">
                <div class="flex items-center gap-2.5">
                    <span class="text-xl">👥</span>
                    <h3 class="text-base font-bold text-white">Überwachte Streamer verwalten ({{ streamers|length }})</h3>
                </div>
                <button onclick="closeStreamerModal()" class="text-slate-400 hover:text-white text-2xl font-bold px-3 py-1 rounded-lg hover:bg-slate-800 transition">&times;</button>
            </div>
            
            <div class="p-5 overflow-y-auto space-y-6">
                <!-- Neuer Streamer Formular -->
                <form action="/api/streamers/add" method="POST" class="bg-slate-950/80 border border-purple-500/40 p-4 rounded-xl space-y-3 shadow-inner">
                    <span class="text-xs font-bold text-purple-400 uppercase tracking-wider block">➕ Neuen Streamer hinzufügen</span>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div class="sm:col-span-1">
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Twitch Kanalname:</label>
                            <input type="text" name="name" required placeholder="z. B. rewinside, xqc..." 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 font-semibold">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Min. Views:</label>
                            <input type="number" name="min_views" value="30" min="5" 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Max Clips/Run:</label>
                            <input type="number" name="max_clips" value="2" min="1" max="10" 
                                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500">
                        </div>
                    </div>
                    <button type="submit" class="w-full py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white font-bold text-xs rounded-lg transition shadow active:scale-95">
                        ➕ Streamer hinzufügen & dauerhaft speichern
                    </button>
                </form>

                <!-- Aktive Streamer Liste -->
                <div class="space-y-2">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-bold text-slate-300 uppercase tracking-wider block">Aktuell überwachte Streamer</span>
                        <span class="text-xs text-slate-500 font-mono">{{ streamers|length }} aktiv</span>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-64 overflow-y-auto pr-1">
                        {% for s in streamers %}
                        <div class="flex justify-between items-center bg-slate-800/80 border border-slate-700/80 px-3.5 py-2.5 rounded-xl hover:border-slate-600 transition">
                            <div>
                                <span class="text-xs font-bold text-white block">{{ s.name }}</span>
                                <span class="text-2xs text-slate-400 font-mono">Min. {{ s.min_clip_views }} Views • Max {{ s.max_clips_per_run }} Clips</span>
                            </div>
                            <form action="/api/streamers/remove/{{ s.name }}" method="POST" onsubmit="return confirm('Streamer {{ s.name }} wirklich entfernen?');">
                                <button type="submit" class="p-1 px-2.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800/60 text-rose-300 font-bold text-xs rounded-lg transition" title="Streamer aus Überwachung entfernen">
                                    🗑️
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
    <div id="crop-modal" class="fixed inset-0 bg-black/90 backdrop-blur-lg z-50 hidden flex items-center justify-center p-2 sm:p-4">
        <div class="bg-slate-900 border border-slate-700/90 rounded-2xl max-w-6xl w-full overflow-hidden shadow-2xl flex flex-col max-h-[96vh]">
            <!-- Header -->
            <div class="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-950/80">
                <div class="flex items-center gap-3">
                    <span class="text-2xl">📐</span>
                    <div>
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>Visueller Zuschnitt: Cam & Gameplay Rahmen</span>
                            <span id="crop-modal-clip-badge" class="text-xs bg-purple-900/80 text-purple-200 px-2 py-0.5 rounded font-mono truncate max-w-[200px]">Clip</span>
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
                    <div class="flex items-center gap-2 bg-slate-950/80 p-1.5 rounded-xl border border-slate-800 shadow-inner">
                        <button type="button" onclick="switchCropMode('split')" id="btn-mode-split" 
                            class="flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-purple-700 text-white shadow">
                            <span>✂️</span> Split-Screen (Cam oben + Gameplay unten)
                        </button>
                        <button type="button" onclick="switchCropMode('single_916')" id="btn-mode-single" 
                            class="flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300">
                            <span>📱</span> Reines 9:16 Vollbild (IRL / Einzelfokus ohne Trennung)
                        </button>
                    </div>

                    <!-- Stage Container (Aspect 16:9) -->
                    <div id="crop-stage-container" class="relative w-full aspect-video bg-black rounded-xl overflow-hidden border-2 border-slate-700 shadow-2xl flex items-center justify-center select-none">
                        <!-- Video element -->
                        <video id="crop-stage-video" crossorigin="anonymous" playsinline preload="auto" class="w-full h-full object-contain pointer-events-none select-none"></video>

                        <!-- Draggable Overlay Boxes Container (Feste Größen ohne Verzerrung) -->
                        <div id="crop-overlay-layer" class="absolute inset-0 select-none">
                            <!-- 🟩 Facecam Box (Feste 3:2 Proportion, frei verschiebbar & stufenlos skalierbar) -->
                            <div id="crop-box-cam" class="absolute select-none border-2 border-emerald-400 bg-emerald-500/20 shadow-[0_0_20px_rgba(52,211,153,0.5)] rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:shadow-[0_0_25px_rgba(52,211,153,0.8)]" title="Verschieben (Ziehen) oder Größe ändern (Ecken ziehen / Mausrad)">
                                <div class="absolute -top-6 left-0 bg-emerald-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>📷 Facecam</span>
                                    <span class="text-emerald-200 text-2xs font-normal">(Festes 3:2 Format)</span>
                                </div>
                                <div class="w-5 h-5 rounded-full border border-white/70 bg-emerald-500/60 pointer-events-none flex items-center justify-center shadow">
                                    <span class="text-2xs text-white font-black">✚</span>
                                </div>
                                <!-- 4 Ecken zum stufenlosen Vergrößern/Verkleinern mit festem 3:2 Seitenverhältnis -->
                                <div class="crop-cam-handle absolute -top-1.5 -left-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="tl" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="tr" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -bottom-1.5 -left-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="bl" title="Größe anpassen (3:2)"></div>
                                <div class="crop-cam-handle absolute -bottom-1.5 -right-1.5 w-3.5 h-3.5 bg-emerald-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="br" title="Größe anpassen (3:2)"></div>
                            </div>

                            <!-- 🟦 Gameplay Box (Feste 9:10 Proportion, frei verschiebbar & stufenlos skalierbar) -->
                            <div id="crop-box-game" class="absolute select-none border-2 border-sky-400 bg-sky-500/20 shadow-[0_0_20px_rgba(56,189,248,0.5)] rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:shadow-[0_0_25px_rgba(56,189,248,0.8)]" title="Verschieben (Ziehen) oder Größe ändern (Ecken ziehen / Mausrad)">
                                <div class="absolute -top-6 left-0 bg-sky-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>🎮 Gameplay</span>
                                    <span id="crop-game-format-badge" class="text-sky-200 text-2xs font-normal">(Festes 9:10 Format)</span>
                                </div>
                                <div class="w-5 h-5 rounded-full border border-white/70 bg-sky-500/60 pointer-events-none flex items-center justify-center shadow">
                                    <span class="text-2xs text-white font-black">✚</span>
                                </div>
                                <!-- 4 Ecken zum stufenlosen Vergrößern/Verkleinern mit festem 9:10 Seitenverhältnis -->
                                <div class="crop-game-handle absolute -top-1.5 -left-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="tl" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="tr" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -bottom-1.5 -left-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nesw-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="bl" title="Gameplay-Größe anpassen (9:10)"></div>
                                <div class="crop-game-handle absolute -bottom-1.5 -right-1.5 w-3.5 h-3.5 bg-sky-400 border-2 border-slate-900 rounded-full cursor-nwse-resize shadow-md z-20 hover:scale-125 transition-transform" data-handle="br" title="Gameplay-Größe anpassen (9:10)"></div>
                            </div>

                            <!-- 🟪 Reiner 9:16 IRL Vollbild-Rahmen (Festes 9:16 Format, horizontal verschiebbar) -->
                            <div id="crop-box-single" class="absolute select-none border-2 border-fuchsia-400 bg-fuchsia-500/20 shadow-[0_0_25px_rgba(217,70,239,0.6)] rounded-lg cursor-grab active:cursor-grabbing flex items-center justify-center transition-shadow hover:shadow-[0_0_30px_rgba(217,70,239,0.9)] hidden">
                                <div class="absolute -top-6 left-0 bg-fuchsia-600 text-[10px] font-black text-white px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap flex items-center gap-1">
                                    <span>📱 9:16 IRL Bildausschnitt</span>
                                    <span class="text-fuchsia-200 text-2xs font-normal">(Festes 9:16 Vollbild)</span>
                                </div>
                                <div class="w-6 h-6 rounded-full border border-white/70 bg-fuchsia-500/60 pointer-events-none flex items-center justify-center shadow">
                                    <span class="text-xs text-white font-black">↔</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Video Scrubber / Timeline Bar -->
                    <div class="bg-slate-950/90 border border-slate-800 rounded-xl p-3 flex flex-col sm:flex-row items-center gap-3">
                        <div class="flex items-center gap-2">
                            <button onclick="seekCropVideo(-2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden zurück">⏪ -2s</button>
                            <button onclick="toggleCropVideoPlay()" id="crop-play-btn" class="px-3 py-1.5 bg-purple-700 hover:bg-purple-600 text-xs font-bold text-white rounded-lg transition">⏯️ Pause</button>
                            <button onclick="seekCropVideo(2)" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-lg transition" title="2 Sekunden vor">⏩ +2s</button>
                        </div>
                        <input type="range" id="crop-time-slider" min="0" max="30" step="0.1" value="0" class="flex-1 accent-purple-500 cursor-pointer" oninput="onCropSliderInput(this.value)">
                        <span id="crop-time-display" class="text-xs font-mono font-bold text-slate-300 min-w-[90px] text-right">00:00 / 00:00</span>
                    </div>

                    <!-- Presets & Quick Action Toolbar (Split vs Single 9:16) -->
                    <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3 space-y-2.5">
                        <!-- Toolbar für Split-Screen Modus -->
                        <div id="toolbar-split" class="space-y-2.5">
                            <div class="space-y-1.5">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="text-xs font-bold text-emerald-400 min-w-[100px]">📷 Cam-Position:</span>
                                    <button onclick="applyPreset('cam_br')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Unten Rechts</button>
                                    <button onclick="applyPreset('cam_tl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Oben Links</button>
                                    <button onclick="applyPreset('cam_tr')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Oben Rechts</button>
                                    <button onclick="applyPreset('cam_bl')" class="px-2.5 py-1 bg-slate-800 hover:bg-emerald-900/60 border border-slate-700 hover:border-emerald-500 text-xs rounded-lg text-slate-200 transition">📍 Unten Links</button>
                                    <button onclick="detectFacecamInCropModal()" id="btn-crop-detect" class="px-3 py-1 bg-purple-900/80 hover:bg-purple-800 border border-purple-500/80 text-purple-200 hover:text-white text-xs font-bold rounded-lg transition shadow flex items-center gap-1">
                                        <span>🤖</span> KI Auto-Erkennen
                                    </button>
                                    <button onclick="toggleCamEnabled()" id="btn-crop-toggle-cam" class="px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition">
                                        🚫 Keine Cam (Vollbild)
                                    </button>
                                </div>
                                <!-- Stufenlose Cam-Größenregelung mit festem 3:2 Seitenverhältnis -->
                                <div class="flex flex-wrap items-center gap-3 bg-slate-900/70 p-2.5 rounded-xl border border-slate-800/80">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs font-bold text-emerald-400 min-w-[90px] flex items-center gap-1">
                                            <span>📏</span> Cam-Größe:
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
                                        <span class="text-2xs text-slate-500 hidden md:inline ml-1">🔒 3:2 fest • Mausrad / Ecken ziehen</span>
                                    </div>
                                </div>
                                <div class="flex flex-wrap items-center gap-2 pt-1.5 border-t border-slate-800/60">
                                    <span class="text-xs font-semibold text-emerald-400 min-w-[100px] flex items-center gap-1">
                                        <span>🎭</span> Snapchat-Filter:
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
                                        <span>🎮</span> Game-Position:
                                    </span>
                                    <button onclick="applyPreset('game_center')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">🎯 Mitte (Zentriert)</button>
                                    <button onclick="applyPreset('game_left')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">⬅️ Links</button>
                                    <button onclick="applyPreset('game_right')" class="px-2.5 py-1 bg-slate-800 hover:bg-sky-900/60 border border-slate-700 hover:border-sky-500 text-xs rounded-lg text-slate-200 transition">➡️ Rechts</button>
                                </div>
                                <div class="flex flex-wrap items-center gap-3 bg-slate-900/70 p-2.5 rounded-xl border border-slate-800/80">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs font-bold text-sky-400 min-w-[90px] flex items-center gap-1">
                                            <span>📏</span> Game-Größe:
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
                                        <span id="crop-game-hint-text" class="text-2xs text-slate-500 hidden md:inline ml-1">🔒 9:10 fest (Split) • Mausrad / Ecken ziehen</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Toolbar für Reines 9:16 IRL Vollbild -->
                        <div id="toolbar-single" class="hidden flex flex-wrap items-center gap-2.5">
                            <span class="text-xs font-bold text-fuchsia-400 min-w-[110px]">📱 IRL-Ausschnitt:</span>
                            <button onclick="applyPreset('single_center')" class="px-3 py-1.5 bg-slate-800 hover:bg-fuchsia-900/60 border border-slate-700 hover:border-fuchsia-500 text-xs font-bold rounded-lg text-slate-200 transition">🎯 Mitte (Zentriert)</button>
                            <button onclick="applyPreset('single_left')" class="px-3 py-1.5 bg-slate-800 hover:bg-fuchsia-900/60 border border-slate-700 hover:border-fuchsia-500 text-xs font-bold rounded-lg text-slate-200 transition">⬅️ Links</button>
                            <button onclick="applyPreset('single_right')" class="px-3 py-1.5 bg-slate-800 hover:bg-fuchsia-900/60 border border-slate-700 hover:border-fuchsia-500 text-xs font-bold rounded-lg text-slate-200 transition">➡️ Rechts</button>
                            <span class="text-2xs text-fuchsia-300/80 ml-auto bg-fuchsia-950/80 px-2 py-1 rounded border border-fuchsia-800/60">🔒 Fester 9:16 Vollbild-Ausschnitt (608x1080 px)</span>
                        </div>
                    </div>
                </div>

                <!-- Right Column: 9:16 Live Smartphone Mockup Preview (4 cols) -->
                <div class="lg:col-span-4 flex flex-col items-center justify-between bg-slate-950/70 border border-slate-800 rounded-2xl p-4">
                    <div class="text-center mb-2">
                        <span class="text-xs font-bold uppercase tracking-wider text-purple-400 block">📱 Live 9:16 Vorschau</span>
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
                <button onclick="closeCropModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl transition">
                    Abbrechen
                </button>
                <div class="flex items-center gap-2">
                    <button onclick="saveCropCoordinates(false)" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-bold text-xs rounded-xl transition">
                        💾 Nur Speichern
                    </button>
                    <button onclick="saveCropCoordinates(true)" class="px-6 py-2.5 bg-gradient-to-r from-purple-600 via-pink-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-black text-xs rounded-xl shadow-lg shadow-purple-500/25 transition active:scale-95 flex items-center gap-2">
                        <span>🚀</span> Zuschnitt speichern & Jetzt Rendern (NVENC)
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Live Auto-Update Script -->
    <script>
        function openStreamerModal() {
            document.getElementById('streamer-modal').classList.remove('hidden');
        }

        function closeStreamerModal() {
            document.getElementById('streamer-modal').classList.add('hidden');
        }

        function filterStudioByStreamer(streamerName) {
            document.querySelectorAll('.streamer-pill').forEach(btn => {
                btn.classList.remove('active', 'bg-purple-600', 'text-white');
                btn.classList.add('bg-slate-800', 'text-slate-300');
            });
            
            const activePill = document.getElementById('pill-' + streamerName);
            if (activePill) {
                activePill.classList.remove('bg-slate-800', 'text-slate-300');
                activePill.classList.add('active', 'bg-purple-600', 'text-white');
            }

            document.querySelectorAll('.studio-clip-card').forEach(card => {
                if (streamerName === 'all' || card.getAttribute('data-streamer') === streamerName) {
                    card.classList.remove('hidden');
                } else {
                    card.classList.add('hidden');
                }
            });
        }

        async function toggleManualPublished(clipId, isChecked) {
            const card = document.getElementById('card-' + clipId);
            const label = document.getElementById('pub-label-' + clipId);
            
            if (isChecked) {
                card.classList.add('opacity-40', 'grayscale', 'hover:grayscale-0', 'hover:opacity-95', 'border-emerald-900/80', 'bg-slate-950/90');
                if (label) {
                    label.innerText = '✓ Veröffentlicht';
                    label.className = 'text-xs font-bold text-emerald-400';
                }
            } else {
                card.classList.remove('opacity-40', 'grayscale', 'hover:grayscale-0', 'hover:opacity-95', 'border-emerald-900/80', 'bg-slate-950/90');
                if (label) {
                    label.innerText = 'Veröffentlicht?';
                    label.className = 'text-xs font-bold text-slate-400';
                }
            }

            try {
                await fetch('/api/clip/' + clipId + '/toggle-published', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_published: isChecked })
                });
            } catch (e) {
                console.error('Fehler beim Aktualisieren des Veröffentlichungs-Status:', e);
            }
        }
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active', 'text-purple-400'));
            
            const target = document.getElementById('tab-' + tabId);
            if (target) target.classList.remove('hidden');
            const btn = document.getElementById('tab-' + tabId + '-btn');
            if (btn) {
                btn.classList.add('active');
                btn.classList.remove('text-slate-400');
            }
        }

        let currentPreviewClipId = '';
        let currentPreviewStreamer = '';
        let currentPreviewTitle = '';

        function openRawPreview(clipId, streamer, title, views, duration, createdAgo = '', createdFull = '') {
            currentPreviewClipId = clipId;
            currentPreviewStreamer = streamer;
            currentPreviewTitle = title;
            document.getElementById('modal-streamer').innerText = streamer.toUpperCase();
            document.getElementById('modal-title').innerText = title;
            let statsText = '👁️ ' + views + ' Views • ⏱️ ' + duration + 's (Rohdatei auf Festplatte)';
            if (createdAgo) {
                statsText += ' • 📅 Erstellt: ' + createdAgo;
            }
            const statsElem = document.getElementById('modal-stats');
            statsElem.innerText = statsText;
            if (createdFull) {
                statsElem.title = createdFull;
            }
            
            const player = document.getElementById('modal-video-player');
            player.src = '/raw-video/' + clipId;
            player.load();
            player.play();

            document.getElementById('modal-process-form').action = '/process-one/' + clipId;
            document.getElementById('modal-delete-form').action = '/queue/delete/' + clipId;
            document.getElementById('modal-download-raw').href = '/download/raw/' + clipId;
            document.getElementById('preview-modal').classList.remove('hidden');
        }

        function closePreviewModal() {
            const player = document.getElementById('modal-video-player');
            player.pause();
            player.src = '';
            document.getElementById('preview-modal').classList.add('hidden');
        }

        let logsOpen = false;
        function toggleLogs() {
            logsOpen = !logsOpen;
            const box = document.getElementById('log-box');
            const icon = document.getElementById('log-toggle-icon');
            if (logsOpen) {
                box.classList.remove('hidden');
                icon.innerText = '▲ Verbergen';
            } else {
                box.classList.add('hidden');
                icon.innerText = '▼ Anzeigen';
            }
        }

        async function triggerRun() {
            const btn = document.getElementById('btn-trigger');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> Scanne Twitch...';
            try {
                await fetch('/api/run', { method: 'POST' });
            } catch (e) {
                console.error(e);
            }
        }

        async function processAll() {
            const btn = document.getElementById('btn-process-all');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span>⏳</span> Schneide alle Clips...';
            }
            try {
                await fetch('/api/process-all', { method: 'POST' });
                switchTab('studio');
            } catch (e) {
                console.error(e);
            }
        }

        async function updateStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const dot = document.getElementById('live-dot');
                const text = document.getElementById('live-status-text');
                const desc = document.getElementById('live-task-desc');
                const btn = document.getElementById('btn-trigger');

                // Render Progress Card
                const progressCard = document.getElementById('render-progress-card');
                const progressBar = document.getElementById('render-progress-bar');
                const progressPercent = document.getElementById('render-percent-text');
                const progressEta = document.getElementById('render-eta-text');
                const progressSpeed = document.getElementById('render-speed-badge');
                const progressTitle = document.getElementById('render-progress-title');

                if (data.is_running) {
                    dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
                    text.innerText = 'Aktiv: ' + data.status.toUpperCase();
                    desc.innerText = data.current_task + (data.streamer ? ' (' + data.streamer + ')' : '');
                    if (btn) {
                        btn.disabled = true;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-slate-800 text-slate-400 font-bold text-sm rounded-xl cursor-not-allowed';
                    }

                    // Render Fortschritt einblenden
                    if (data.status === 'rendering' || data.progress_percent > 0) {
                        progressCard.classList.remove('hidden');
                        progressBar.style.width = data.progress_percent + '%';
                        progressPercent.innerText = data.progress_percent + '%';
                        
                        if (data.eta_seconds !== null && data.eta_seconds !== undefined) {
                            progressEta.innerText = 'Noch ca. ' + data.eta_seconds + 's';
                        } else {
                            progressEta.innerText = 'Berechne...';
                        }

                        if (data.speed) {
                            progressSpeed.innerText = data.speed + ' NVENC';
                        }
                        progressTitle.innerText = data.current_task || 'Rendere Video...';
                    } else {
                        progressCard.classList.add('hidden');
                    }
                } else {
                    dot.className = 'w-2 h-2 rounded-full bg-slate-400';
                    text.innerText = 'Standby';
                    desc.innerText = data.current_task;
                    progressCard.classList.add('hidden');
                    if (btn) {
                        btn.disabled = false;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 font-bold text-sm rounded-xl shadow-lg shadow-purple-500/20 transition transform active:scale-95 text-white';
                        btn.innerHTML = '<span>⚡</span> Neue Clips auf Twitch suchen';
                    }
                }

                if (data.logs && data.logs.length > 0) {
                    document.getElementById('log-count').innerText = data.logs.length + ' Einträge';
                    const logBox = document.getElementById('log-box');
                    logBox.innerHTML = data.logs.slice(-30).map(l => '<div>' + l + '</div>').join('');
                    if (logsOpen) {
                        logBox.scrollTop = logBox.scrollHeight;
                    }
                }
            } catch (err) {
                console.error('Polling error:', err);
            }
        }

        // --- VISUELLER ZUSCHNITT & CROPPER ---
        let currentCropClipId = null;
        let currentCropTitle = '';
        let currentCropStreamer = '';
        let currentCropMode = 'split'; // 'split' oder 'single_916'
        let videoNativeWidth = 1920;
        let videoNativeHeight = 1080;
        let cropState = {
            cam: { x: 0.73, y: 0.64, w: 0.26, h: 0.34, enabled: true },
            game: { x: 0.245, y: 0.0, w: 0.51, h: 1.0, enabled: true },
            single: { x: (1 - (608 / 1920)) / 2, y: 0.0, w: 608 / 1920, h: 1.0, enabled: true }
        };
        let activeCropDrag = null;
        let cropVideoInitialized = false;

        function switchCropMode(mode) {
            currentCropMode = mode;
            const btnSplit = document.getElementById('btn-mode-split');
            const btnSingle = document.getElementById('btn-mode-single');
            const tbSplit = document.getElementById('toolbar-split');
            const tbSingle = document.getElementById('toolbar-single');
            const boxCam = document.getElementById('crop-box-cam');
            const boxGame = document.getElementById('crop-box-game');
            const boxSingle = document.getElementById('crop-box-single');

            if (mode === 'single_916') {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-gradient-to-r from-fuchsia-600 to-pink-600 text-white shadow-lg shadow-fuchsia-500/20';
                }
                if (tbSplit) tbSplit.classList.add('hidden');
                if (tbSingle) tbSingle.classList.remove('hidden');
                if (boxCam) boxCam.classList.add('hidden');
                if (boxGame) boxGame.classList.add('hidden');
                if (boxSingle) boxSingle.classList.remove('hidden');
                updateBoxDom('single');
            } else {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-lg shadow-purple-500/20';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300';
                }
                if (tbSplit) tbSplit.classList.remove('hidden');
                if (tbSingle) tbSingle.classList.add('hidden');
                if (boxCam && cropState.cam.enabled) boxCam.classList.remove('hidden');
                if (boxGame) boxGame.classList.remove('hidden');
                if (boxSingle) boxSingle.classList.add('hidden');
                updateBoxDom('cam');
                updateBoxDom('game');
            }
            draw916Preview();
        }

        async function openCropModal(clipId, streamer, title) {
            currentCropClipId = clipId;
            currentCropStreamer = streamer || '';
            currentCropTitle = title || '';

            const badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = (streamer ? streamer + ': ' : '') + (title ? title.slice(0, 28) : clipId);

            const cardFilterSelect = document.querySelector(`form[action="/save/${clipId}"] select[name="cam_filter"]`);
            const filterVal = cardFilterSelect ? cardFilterSelect.value : 'none';
            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            if (modalFilterSelect) modalFilterSelect.value = filterVal;

            const modal = document.getElementById('crop-modal');
            modal.classList.remove('hidden');

            const vid = document.getElementById('crop-stage-video');
            vid.src = '/raw-video/' + clipId;
            vid.load();

            // Default Box States: Feste Seitenverhältnisse (3:2 für Cam, 9:10 für Gameplay, 9:16 für Single)
            cropState.cam = {
                x: 1 - (540 / 1920) - 0.02,
                y: 1 - (360 / 1080) - 0.03,
                w: 540 / 1920,
                h: 360 / 1080,
                enabled: true
            };
            cropState.game = {
                x: (1 - (972 / 1920)) / 2,
                y: 0.0,
                w: 972 / 1920,
                h: 1.0,
                enabled: true
            };
            cropState.single = {
                x: (1 - (608 / 1920)) / 2,
                y: 0.0,
                w: 608 / 1920,
                h: 1.0,
                enabled: true
            };
            currentCropMode = 'split';

            // Saved metadata abrufen falls vorhanden
            try {
                const resp = await fetch(`/api/clip/${clipId}/meta`);
                const meta = await resp.json();
                if (meta) {
                    if (meta.layout_mode === 'single_916' || (meta.custom_crops && meta.custom_crops.mode === 'single_916')) {
                        currentCropMode = 'single_916';
                        if (meta.custom_crops) {
                            const s = meta.custom_crops.single || meta.custom_crops.single_916;
                            if (s) {
                                if (s.x_pct !== undefined) cropState.single.x = s.x_pct;
                                else if (s.x !== undefined) cropState.single.x = s.x / (meta.video_w || 1920);
                            }
                        }
                    } else if (meta.custom_crops && meta.custom_crops.cam) {
                        currentCropMode = 'split';
                        const c = meta.custom_crops.cam;
                        const g = meta.custom_crops.game;
                        if (c.w_pct) {
                            cropState.cam.w = c.w_pct;
                            cropState.cam.h = c.h_pct;
                        }
                        cropState.cam.x = c.x_pct !== undefined ? c.x_pct : (c.x / (meta.video_w || 1920));
                        cropState.cam.y = c.y_pct !== undefined ? c.y_pct : (c.y / (meta.video_h || 1080));
                        cropState.cam.enabled = c.enabled !== false;

                        if (g) {
                            if (g.w_pct) {
                                cropState.game.w = g.w_pct;
                                cropState.game.h = g.h_pct || (g.w_pct * ((meta.video_w || 1920) / (meta.video_h || 1080)) * (10 / 9));
                            }
                            cropState.game.x = g.x_pct !== undefined ? g.x_pct : (g.x / (meta.video_w || 1920));
                            cropState.game.y = g.y_pct !== undefined ? g.y_pct : 0.0;
                        }
                    }
                    if (meta.title) currentCropTitle = meta.title;
                    if (meta.cam_filter && modalFilterSelect) {
                        modalFilterSelect.value = meta.cam_filter;
                    }
                }
            } catch (e) {
                console.warn('Keine vorherigen Zuschnitt-Metadaten geladen:', e);
            }

            // Sync Cam & Game Größen-Regler
            const curWpx = Math.round(cropState.cam.w * (videoNativeWidth || 1920));
            const curHpx = Math.round(curWpx * (2 / 3));
            syncCamSizeUi(curWpx, curHpx);

            const isVollbild = isGameplayVollbild();
            const curGW = Math.round(cropState.game.w * (videoNativeWidth || 1920));
            const curGH = Math.round(curGW * (isVollbild ? (16 / 9) : (10 / 9)));
            syncGameSizeUi(curGW, curGH);

            switchCropMode(currentCropMode);
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');

            if (!cropVideoInitialized) {
                initCropInteractions();
                initCropVideoListeners();
                cropVideoInitialized = true;
            }
        }

        function closeCropModal() {
            const vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.pause();
                vid.src = '';
            }
            document.getElementById('crop-modal').classList.add('hidden');
        }

        function initCropVideoListeners() {
            const vid = document.getElementById('crop-stage-video');
            const slider = document.getElementById('crop-time-slider');
            const timeDisp = document.getElementById('crop-time-display');

            vid.addEventListener('loadedmetadata', () => {
                videoNativeWidth = vid.videoWidth || 1920;
                videoNativeHeight = vid.videoHeight || 1080;
                slider.max = vid.duration || 30;
                vid.currentTime = Math.min(2.0, (vid.duration || 10) * 0.1);

                // Sync Cam & Game Größen-Regler
                const curWpx = Math.round(cropState.cam.w * videoNativeWidth);
                const curHpx = Math.round(curWpx * (2 / 3));
                syncCamSizeUi(curWpx, curHpx);

                const isVollbild = isGameplayVollbild();
                const curGW = Math.round(cropState.game.w * videoNativeWidth);
                const curGH = Math.round(curGW * (isVollbild ? (16 / 9) : (10 / 9)));
                syncGameSizeUi(curGW, curGH);

                updateBoxDom('cam');
                updateBoxDom('game');
                updateBoxDom('single');
                draw916Preview();
            });

            vid.addEventListener('timeupdate', () => {
                slider.value = vid.currentTime;
                const cur = formatTime(vid.currentTime);
                const tot = formatTime(vid.duration || 0);
                timeDisp.innerText = `${cur} / ${tot}`;
                draw916Preview();
            });

            vid.addEventListener('seeked', draw916Preview);
            vid.addEventListener('play', () => {
                document.getElementById('crop-play-btn').innerHTML = '⏸️ Pause';
            });
            vid.addEventListener('pause', () => {
                document.getElementById('crop-play-btn').innerHTML = '▶️ Abspielen';
            });
        }

        function formatTime(sec) {
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60);
            return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
        }

        function toggleCropVideoPlay() {
            const vid = document.getElementById('crop-stage-video');
            if (vid.paused) vid.play(); else vid.pause();
        }

        function seekCropVideo(delta) {
            const vid = document.getElementById('crop-stage-video');
            vid.currentTime = Math.max(0, Math.min(vid.duration || 60, vid.currentTime + delta));
        }

        function onCropSliderInput(val) {
            const vid = document.getElementById('crop-stage-video');
            vid.currentTime = parseFloat(val);
        }

        function setCamPixelWidth(widthPx) {
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const maxAllowedW = Math.min(vw, Math.floor(vh * 1.5));
            const clampedW = Math.max(160, Math.min(maxAllowedW, Math.round(parseFloat(widthPx))));
            const clampedH = Math.round(clampedW * (2 / 3));

            const newW = clampedW / vw;
            const newH = clampedH / vh;

            // Mittelpunkt stabil halten
            const centerX = cropState.cam.x + (cropState.cam.w / 2);
            const centerY = cropState.cam.y + (cropState.cam.h / 2);

            cropState.cam.w = newW;
            cropState.cam.h = newH;
            cropState.cam.x = Math.max(0, Math.min(1 - newW, centerX - (newW / 2)));
            cropState.cam.y = Math.max(0, Math.min(1 - newH, centerY - (newH / 2)));

            syncCamSizeUi(clampedW, clampedH);
            updateBoxDom('cam');
            draw916Preview();
        }

        function syncCamSizeUi(w_px, h_px) {
            const slider = document.getElementById('crop-cam-size-slider');
            const disp = document.getElementById('crop-cam-size-display');
            if (slider && document.activeElement !== slider) slider.value = w_px;
            if (disp) disp.innerText = `${w_px} x ${h_px} px`;

            const bNormal = document.getElementById('btn-size-normal');
            const bSmall = document.getElementById('btn-size-small');
            const bLarge = document.getElementById('btn-size-large');
            const actCls = 'px-2 py-0.5 bg-emerald-900/80 border border-emerald-500 text-2xs font-bold rounded text-emerald-200 shadow transition';
            const inactCls = 'px-2 py-0.5 bg-slate-800 hover:bg-emerald-900/50 border border-slate-700 hover:border-emerald-500 text-2xs rounded text-slate-200 transition';
            if (bNormal) bNormal.className = (w_px === 540) ? actCls : inactCls;
            if (bSmall) bSmall.className = (w_px === 420) ? actCls : inactCls;
            if (bLarge) bLarge.className = (w_px === 680) ? actCls : inactCls;
        }

        function setCamSize(size) {
            if (size === 'small') setCamPixelWidth(420);
            else if (size === 'large') setCamPixelWidth(680);
            else setCamPixelWidth(540);
        }

        function isGameplayVollbild() {
            return currentCropMode === 'single_916' || !cropState.cam.enabled;
        }

        function setGamePixelWidth(widthPx) {
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const isVollbild = isGameplayVollbild();

            // Format-Wahl: 
            // Mit Cam -> 9:10 (Höhe = Breite * 10 / 9)
            // Keine Cam / Vollbild -> 9:16 (Höhe = Breite * 16 / 9)
            const ratioW = 9;
            const ratioH = isVollbild ? 16 : 10;

            const maxAllowedW = Math.min(vw, Math.floor(vh * (ratioW / ratioH)));
            const minAllowedW = isVollbild ? 200 : 320;
            const clampedW = Math.max(minAllowedW, Math.min(maxAllowedW, Math.round(parseFloat(widthPx))));
            const clampedH = Math.round(clampedW * (ratioH / ratioW));

            const newW = clampedW / vw;
            const newH = clampedH / vh;

            // Mittelpunkt beibehalten beim Zoomen/Skalieren
            const centerX = cropState.game.x + (cropState.game.w / 2);
            const centerY = cropState.game.y + (cropState.game.h / 2);

            cropState.game.w = newW;
            cropState.game.h = newH;
            cropState.game.x = Math.max(0, Math.min(1 - newW, centerX - (newW / 2)));
            cropState.game.y = Math.max(0, Math.min(1 - newH, centerY - (newH / 2)));

            syncGameSizeUi(clampedW, clampedH);
            updateBoxDom('game');
            draw916Preview();
        }

        function syncGameSizeUi(w_px, h_px) {
            const isVollbild = isGameplayVollbild();
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            const slider = document.getElementById('crop-game-size-slider');
            const disp = document.getElementById('crop-game-size-display');
            const badge = document.getElementById('crop-game-format-badge');
            const hint = document.getElementById('crop-game-hint-text');

            const bMax = document.getElementById('btn-game-size-max');
            const bMed = document.getElementById('btn-game-size-medium');
            const bSmall = document.getElementById('btn-game-size-small');

            const actCls = 'px-2 py-0.5 bg-sky-900/80 border border-sky-500 text-2xs font-bold rounded text-sky-200 shadow transition';
            const inactCls = 'px-2 py-0.5 bg-slate-800 hover:bg-sky-900/50 border border-slate-700 hover:border-sky-500 text-2xs rounded text-slate-200 transition';

            if (isVollbild) {
                const maxW = Math.min(vw, Math.floor(vh * (9 / 16))); // 608 auf 1080p
                const medW = Math.round(maxW * 0.833); // 506px
                const zoomW = Math.round(maxW * 0.667); // 405px

                if (slider) {
                    slider.min = 200;
                    slider.max = maxW;
                    if (document.activeElement !== slider) slider.value = w_px;
                }
                if (badge) badge.innerText = '(Festes 9:16 Vollbild)';
                if (hint) hint.innerText = '🔒 9:16 fest (Vollbild) • Mausrad / Ecken ziehen';

                if (bSmall) {
                    bSmall.innerText = `Zoom (${zoomW}px)`;
                    bSmall.onclick = () => setGamePixelWidth(zoomW);
                    bSmall.className = (Math.abs(w_px - zoomW) <= 5) ? actCls : inactCls;
                }
                if (bMed) {
                    bMed.innerText = `Mittel (${medW}px)`;
                    bMed.onclick = () => setGamePixelWidth(medW);
                    bMed.className = (Math.abs(w_px - medW) <= 5) ? actCls : inactCls;
                }
                if (bMax) {
                    bMax.innerText = `Voll (${maxW}px)`;
                    bMax.onclick = () => setGamePixelWidth(maxW);
                    bMax.className = (Math.abs(w_px - maxW) <= 5) ? actCls : inactCls;
                }
            } else {
                const maxW = Math.min(vw, Math.floor(vh * 0.9)); // 972 auf 1080p
                const medW = 810;
                const zoomW = 648;

                if (slider) {
                    slider.min = 320;
                    slider.max = maxW;
                    if (document.activeElement !== slider) slider.value = w_px;
                }
                if (badge) badge.innerText = '(Festes 9:10 Format)';
                if (hint) hint.innerText = '🔒 9:10 fest (Split) • Mausrad / Ecken ziehen';

                if (bSmall) {
                    bSmall.innerText = 'Zoom (648px)';
                    bSmall.onclick = () => setGamePixelWidth(648);
                    bSmall.className = (Math.abs(w_px - 648) <= 5) ? actCls : inactCls;
                }
                if (bMed) {
                    bMed.innerText = 'Mittel (810px)';
                    bMed.onclick = () => setGamePixelWidth(810);
                    bMed.className = (Math.abs(w_px - 810) <= 5) ? actCls : inactCls;
                }
                if (bMax) {
                    bMax.innerText = `Voll (${maxW}px)`;
                    bMax.onclick = () => setGamePixelWidth(maxW);
                    bMax.className = (Math.abs(w_px - maxW) <= 5) ? actCls : inactCls;
                }
            }

            if (disp) disp.innerText = `${w_px} x ${h_px} px`;
        }

        function updateBoxDom(type) {
            const box = document.getElementById('crop-box-' + type);
            if (!box) return;
            const s = cropState[type];
            if (!s) return;
            box.style.left = (s.x * 100) + '%';
            box.style.top = (s.y * 100) + '%';
            box.style.width = (s.w * 100) + '%';
            box.style.height = (s.h * 100) + '%';

            if (currentCropMode === 'single_916') {
                if (type === 'single') box.classList.remove('hidden');
                else box.classList.add('hidden');
            } else {
                if (type === 'single') box.classList.add('hidden');
                else if (type === 'cam') {
                    if (s.enabled) box.classList.remove('hidden');
                    else box.classList.add('hidden');
                } else if (type === 'game') {
                    box.classList.remove('hidden');
                }
            }

            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const readout = document.getElementById('crop-coords-readout');
            if (readout) {
                if (currentCropMode === 'single_916') {
                    const singlePx = { w: Math.round(cropState.single.w * vw), h: Math.round(cropState.single.h * vh), x: Math.round(cropState.single.x * vw), y: 0 };
                    readout.innerText = `📱 Reines 9:16 IRL: ${singlePx.w}x${singlePx.h} @ (${singlePx.x}, 0) • Feste 9:16 Proportion (100% Video-Höhe)`;
                } else {
                    const camPx = { w: Math.round(cropState.cam.w * vw), h: Math.round(cropState.cam.h * vh), x: Math.round(cropState.cam.x * vw), y: Math.round(cropState.cam.y * vh) };
                    const gamePx = { w: Math.round(cropState.game.w * vw), h: Math.round(cropState.game.h * vh), x: Math.round(cropState.game.x * vw), y: Math.round(cropState.game.y * vh) };
                    readout.innerText = `Cam: ${cropState.cam.enabled ? camPx.w + 'x' + camPx.h + ' @ (' + camPx.x + ',' + camPx.y + ')' : 'Deaktiviert'} • Game: ${gamePx.w}x${gamePx.h} @ (${gamePx.x},${gamePx.y})`;
                }
            }
        }

        function initCropInteractions() {
            const stage = document.getElementById('crop-stage-container');
            if (!stage) return;

            const camBox = document.getElementById('crop-box-cam');
            if (camBox) {
                // Verschieben der Cam-Box
                camBox.addEventListener('pointerdown', (e) => {
                    // Falls auf einen Ecken-Resize-Handle geklickt wurde, kein Move-Drag starten
                    if (e.target.classList.contains('crop-cam-handle')) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'cam',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.cam.x,
                        initY: cropState.cam.y
                    };
                });

                // Mausrad zum stufenlosen Vergrößern/Verkleinern (3:2 bleibt fest)
                camBox.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const vw = videoNativeWidth || 1920;
                    const curWpx = cropState.cam.w * vw;
                    const delta = e.deltaY < 0 ? 15 : -15;
                    setCamPixelWidth(curWpx + delta);
                }, { passive: false });
            }

            // Ecken-Resize Handles für stufenlose Cam-Größenänderung mit festem 3:2 Seitenverhältnis
            document.querySelectorAll('.crop-cam-handle').forEach(handleEl => {
                handleEl.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    const handle = handleEl.getAttribute('data-handle');
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;

                    activeCropDrag = {
                        target: 'cam_resize',
                        handle: handle,
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.cam.x,
                        initY: cropState.cam.y,
                        initW: cropState.cam.w,
                        initH: cropState.cam.h,
                        initWpx: cropState.cam.w * vw,
                        anchorX: handle.includes('r') ? cropState.cam.x : cropState.cam.x + cropState.cam.w,
                        anchorY: handle.includes('b') ? cropState.cam.y : cropState.cam.y + cropState.cam.h
                    };
                });
            });

            // Ecken-Resize Handles für stufenlose Gameplay-Größenänderung mit festem 9:10 Seitenverhältnis
            document.querySelectorAll('.crop-game-handle').forEach(handleEl => {
                handleEl.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    const handle = handleEl.getAttribute('data-handle');
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;

                    activeCropDrag = {
                        target: 'game_resize',
                        handle: handle,
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.game.x,
                        initY: cropState.game.y,
                        initW: cropState.game.w,
                        initH: cropState.game.h,
                        initWpx: cropState.game.w * vw,
                        anchorX: handle.includes('r') ? cropState.game.x : cropState.game.x + cropState.game.w,
                        anchorY: handle.includes('b') ? cropState.game.y : cropState.game.y + cropState.game.h
                    };
                });
            });

            const gameBox = document.getElementById('crop-box-game');
            if (gameBox) {
                gameBox.addEventListener('pointerdown', (e) => {
                    if (e.target.classList.contains('crop-game-handle')) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'game',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.game.x,
                        initY: cropState.game.y
                    };
                });

                // Mausrad zum stufenlosen Gameplay-Vergrößern/Verkleinern (9:10 bleibt fest)
                gameBox.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const vw = videoNativeWidth || 1920;
                    const curWpx = cropState.game.w * vw;
                    const delta = e.deltaY < 0 ? 20 : -20;
                    setGamePixelWidth(curWpx + delta);
                }, { passive: false });
            }

            const singleBox = document.getElementById('crop-box-single');
            if (singleBox) {
                singleBox.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'single',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.single.x,
                        initY: 0.0
                    };
                });
            }

            window.addEventListener('pointermove', (e) => {
                if (!activeCropDrag) return;
                const dx = (e.clientX - activeCropDrag.startX) / activeCropDrag.stageW;
                const dy = (e.clientY - activeCropDrag.startY) / activeCropDrag.stageH;

                if (activeCropDrag.target === 'cam') {
                    // Cam bewegt sich frei in X und Y, GRÖSSE BLEIBT FEST (3:2 Format)!
                    cropState.cam.x = Math.max(0, Math.min(1 - cropState.cam.w, activeCropDrag.initX + dx));
                    cropState.cam.y = Math.max(0, Math.min(1 - cropState.cam.h, activeCropDrag.initY + dy));
                    updateBoxDom('cam');
                    draw916Preview();
                } else if (activeCropDrag.target === 'cam_resize') {
                    // Stufenlose Größenänderung über Eckengriffe (3:2 strikt gesperrt)
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;
                    const handle = activeCropDrag.handle;
                    const dxPx = dx * vw;

                    let targetWpx;
                    if (handle.includes('r')) {
                        targetWpx = activeCropDrag.initWpx + dxPx;
                    } else {
                        targetWpx = activeCropDrag.initWpx - dxPx;
                    }

                    const maxAllowedW = Math.min(vw, Math.floor(vh * 1.5));
                    let clampedWpx = Math.max(160, Math.min(maxAllowedW, Math.round(targetWpx)));
                    let clampedHpx = Math.round(clampedWpx * (2 / 3));

                    let wNorm = clampedWpx / vw;
                    let hNorm = clampedHpx / vh;

                    // Randbegrenzung mit festem Seitenverhältnis
                    if (handle.includes('r')) {
                        if (activeCropDrag.anchorX + wNorm > 1.0) {
                            wNorm = 1.0 - activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (2 / 3));
                            hNorm = clampedHpx / vh;
                        }
                    } else {
                        if (activeCropDrag.anchorX - wNorm < 0.0) {
                            wNorm = activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (2 / 3));
                            hNorm = clampedHpx / vh;
                        }
                    }

                    if (handle.includes('b')) {
                        if (activeCropDrag.anchorY + hNorm > 1.0) {
                            hNorm = 1.0 - activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (3 / 2));
                            wNorm = clampedWpx / vw;
                        }
                    } else {
                        if (activeCropDrag.anchorY - hNorm < 0.0) {
                            hNorm = activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (3 / 2));
                            wNorm = clampedWpx / vw;
                        }
                    }

                    clampedWpx = Math.max(160, Math.round(wNorm * vw));
                    clampedHpx = Math.round(clampedWpx * (2 / 3));
                    wNorm = clampedWpx / vw;
                    hNorm = clampedHpx / vh;

                    const newX = handle.includes('l') ? (activeCropDrag.anchorX - wNorm) : activeCropDrag.anchorX;
                    const newY = handle.includes('t') ? (activeCropDrag.anchorY - hNorm) : activeCropDrag.anchorY;

                    cropState.cam.w = wNorm;
                    cropState.cam.h = hNorm;
                    cropState.cam.x = Math.max(0, Math.min(1 - wNorm, newX));
                    cropState.cam.y = Math.max(0, Math.min(1 - hNorm, newY));

                    syncCamSizeUi(clampedWpx, clampedHpx);
                    updateBoxDom('cam');
                    draw916Preview();
                } else if (activeCropDrag.target === 'game_resize') {
                    // Stufenlose Gameplay-Größenänderung über Eckengriffe mit dynamischem Format (9:10 mit Cam vs. 9:16 ohne Cam)
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;
                    const isVollbild = isGameplayVollbild();
                    const ratioW = 9;
                    const ratioH = isVollbild ? 16 : 10;

                    const handle = activeCropDrag.handle;
                    const dxPx = dx * vw;

                    let targetWpx;
                    if (handle.includes('r')) {
                        targetWpx = activeCropDrag.initWpx + dxPx;
                    } else {
                        targetWpx = activeCropDrag.initWpx - dxPx;
                    }

                    const maxAllowedW = Math.min(vw, Math.floor(vh * (ratioW / ratioH)));
                    const minAllowedW = isVollbild ? 200 : 320;
                    let clampedWpx = Math.max(minAllowedW, Math.min(maxAllowedW, Math.round(targetWpx)));
                    let clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));

                    let wNorm = clampedWpx / vw;
                    let hNorm = clampedHpx / vh;

                    // Randbegrenzung mit festem Seitenverhältnis
                    if (handle.includes('r')) {
                        if (activeCropDrag.anchorX + wNorm > 1.0) {
                            wNorm = 1.0 - activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                            hNorm = clampedHpx / vh;
                        }
                    } else {
                        if (activeCropDrag.anchorX - wNorm < 0.0) {
                            wNorm = activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                            hNorm = clampedHpx / vh;
                        }
                    }

                    if (handle.includes('b')) {
                        if (activeCropDrag.anchorY + hNorm > 1.0) {
                            hNorm = 1.0 - activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (ratioW / ratioH));
                            wNorm = clampedWpx / vw;
                        }
                    } else {
                        if (activeCropDrag.anchorY - hNorm < 0.0) {
                            hNorm = activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (ratioW / ratioH));
                            wNorm = clampedWpx / vw;
                        }
                    }

                    clampedWpx = Math.max(minAllowedW, Math.round(wNorm * vw));
                    clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                    wNorm = clampedWpx / vw;
                    hNorm = clampedHpx / vh;

                    const newX = handle.includes('l') ? (activeCropDrag.anchorX - wNorm) : activeCropDrag.anchorX;
                    const newY = handle.includes('t') ? (activeCropDrag.anchorY - hNorm) : activeCropDrag.anchorY;

                    cropState.game.w = wNorm;
                    cropState.game.h = hNorm;
                    cropState.game.x = Math.max(0, Math.min(1 - wNorm, newX));
                    cropState.game.y = Math.max(0, Math.min(1 - hNorm, newY));

                    syncGameSizeUi(clampedWpx, clampedHpx);
                    updateBoxDom('game');
                    draw916Preview();
                } else if (activeCropDrag.target === 'game') {
                    // Gameplay bewegt sich frei in X und Y (falls H < 1.0), GRÖSSE BLEIBT FEST (9:10 Format)!
                    cropState.game.x = Math.max(0, Math.min(1 - cropState.game.w, activeCropDrag.initX + dx));
                    cropState.game.y = Math.max(0, Math.min(1 - cropState.game.h, activeCropDrag.initY + dy));
                    updateBoxDom('game');
                    draw916Preview();
                } else if (activeCropDrag.target === 'single') {
                    // 9:16 IRL Rahmen: nur horizontal bewegbar, feste 9:16 Proportion (608x1080 px / 100% Höhe)!
                    cropState.single.x = Math.max(0, Math.min(1 - cropState.single.w, activeCropDrag.initX + dx));
                    cropState.single.y = 0.0;
                    updateBoxDom('single');
                    draw916Preview();
                }
            });

            window.addEventListener('pointerup', () => {
                activeCropDrag = null;
            });
        }

        function applyPreset(presetName) {
            if (presetName === 'cam_br') {
                cropState.cam.x = Math.max(0, 1 - cropState.cam.w - 0.015);
                cropState.cam.y = Math.max(0, 1 - cropState.cam.h - 0.02);
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_tl') {
                cropState.cam.x = 0.015;
                cropState.cam.y = 0.02;
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_tr') {
                cropState.cam.x = Math.max(0, 1 - cropState.cam.w - 0.015);
                cropState.cam.y = 0.02;
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_bl') {
                cropState.cam.x = 0.015;
                cropState.cam.y = Math.max(0, 1 - cropState.cam.h - 0.02);
                cropState.cam.enabled = true;
            } else if (presetName === 'game_center') {
                cropState.game.x = (1 - cropState.game.w) / 2;
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'game_left') {
                cropState.game.x = 0.01;
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'game_right') {
                cropState.game.x = Math.max(0, 1 - cropState.game.w - 0.01);
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'single_center') {
                cropState.single.x = (1 - cropState.single.w) / 2;
                cropState.single.y = 0.0;
            } else if (presetName === 'single_left') {
                cropState.single.x = 0.0;
                cropState.single.y = 0.0;
            } else if (presetName === 'single_right') {
                cropState.single.x = Math.max(0, 1 - cropState.single.w);
                cropState.single.y = 0.0;
            }
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');
            draw916Preview();
        }

        async function detectFacecamInCropModal() {
            if (!currentCropClipId) return;
            const btn = document.getElementById('btn-crop-detect');
            btn.innerHTML = '<span>⏳</span> Erkenne...';
            btn.disabled = true;
            try {
                const resp = await fetch(`/api/clip/${currentCropClipId}/detect-cam`);
                const data = await resp.json();
                if (data && data.cam) {
                    const faceCenterX = data.cam.x_pct + (data.cam.w_pct / 2);
                    const faceCenterY = data.cam.y_pct + (data.cam.h_pct / 2);
                    cropState.cam.x = Math.max(0, Math.min(1 - cropState.cam.w, faceCenterX - (cropState.cam.w / 2)));
                    cropState.cam.y = Math.max(0, Math.min(1 - cropState.cam.h, faceCenterY - (cropState.cam.h / 2)));
                    cropState.cam.enabled = true;
                    updateBoxDom('cam');
                    draw916Preview();
                }
            } catch (e) {
                console.error(e);
            } finally {
                btn.innerHTML = '<span>🤖</span> KI Auto-Erkennen';
                btn.disabled = false;
            }
        }

        function toggleCamEnabled() {
            cropState.cam.enabled = !cropState.cam.enabled;
            const btn = document.getElementById('btn-crop-toggle-cam');
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            if (cropState.cam.enabled) {
                btn.innerText = '🚫 Keine Cam (Vollbild)';
                btn.className = 'px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition';
                
                // Zu 9:10 Split-Format wechseln (Höhe beibehalten, Breite anpassen)
                const curHpx = Math.round(cropState.game.h * vh);
                const targetWpx = Math.round(curHpx * (9 / 10));
                setGamePixelWidth(targetWpx);
            } else {
                btn.innerText = '✅ Facecam wieder aktivieren';
                btn.className = 'px-2.5 py-1 bg-emerald-900/80 border border-emerald-500 text-xs font-bold rounded-lg text-emerald-200 transition';
                
                // Zu 9:16 Vollbild-Format wechseln (Höhe beibehalten, Breite anpassen)
                const curHpx = Math.round(cropState.game.h * vh);
                const targetWpx = Math.round(curHpx * (9 / 16));
                setGamePixelWidth(targetWpx);
            }
            updateBoxDom('cam');
            updateBoxDom('game');
            draw916Preview();
        }

        function draw916Preview() {
            const canvas = document.getElementById('crop-preview-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const vid = document.getElementById('crop-stage-video');
            if (!vid || vid.readyState < 2) return;

            const vw = vid.videoWidth || 1920;
            const vh = vid.videoHeight || 1080;

            ctx.fillStyle = '#05070e';
            ctx.fillRect(0, 0, 270, 480);

            if (currentCropMode === 'single_916') {
                // 📱 Reines 9:16 Vollbild (IRL) - 1:1 unverzerrt in 9:16 Canvas
                const sx = cropState.single.x * vw;
                const sy = 0;
                const sw = Math.max(16, cropState.single.w * vw);
                const sh = vh;

                try {
                    ctx.drawImage(vid, sx, sy, sw, sh, 0, 0, 270, 480);
                } catch(e) {}

                // Hook Sticker Simulation (oben bei y=120, um Hauptmotiv/Gesicht im Zentrum freizuhalten)
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                const stickerY = 120;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);

            } else if (cropState.cam.enabled) {
                // 1. Top Section: Facecam (1080x720 in 1080x1920 -> 270x180 px)
                const cx = cropState.cam.x * vw;
                const cy = cropState.cam.y * vh;
                const cw = Math.max(16, cropState.cam.w * vw);
                const ch = Math.max(16, cropState.cam.h * vh);

                const filterVal = document.getElementById('crop-cam-filter-select')?.value || 'none';
                if (filterVal === 'triangle') {
                    // 🔺 3D Dreimacs Pyramide
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 4);
                    ctx.lineTo(265, 178);
                    ctx.lineTo(5, 178);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'inv_triangle') {
                    // 🔻 3D Trichter-Kopf
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(5, 4);
                    ctx.lineTo(265, 4);
                    ctx.lineTo(135, 178);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'diamond') {
                    // 💎 3D Diamant-Kopf
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 4);
                    ctx.lineTo(265, 90);
                    ctx.lineTo(135, 176);
                    ctx.lineTo(5, 90);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'cube') {
                    // 📦 3D Block-Kopf (Steve)
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(35, 15, 200, 150);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'alien') {
                    // 👽 3D Megamind / Alien (Riesen-Stirn)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 6);
                    ctx.bezierCurveTo(260, 6, 260, 95, 170, 178);
                    ctx.lineTo(100, 178);
                    ctx.bezierCurveTo(10, 95, 10, 6, 135, 6);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'gigachad') {
                    // 🗿 3D Gigachad (Breiter Kiefer)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(90, 6);
                    ctx.lineTo(180, 6);
                    ctx.bezierCurveTo(220, 60, 265, 120, 265, 176);
                    ctx.lineTo(5, 176);
                    ctx.bezierCurveTo(5, 120, 50, 60, 90, 6);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'hamster') {
                    // 🎈 3D Hamsterbacken
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx, cy + ch * 0.4, cw, ch * 0.6, -15, 75, 300, 105);
                    } catch(e) {}
                } else if (filterVal === 'pinocchio') {
                    // 🤥 3D Pinocchio Langnase
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.35, cy + ch * 0.35, cw * 0.3, ch * 0.3, 100, 75, 70, 95);
                    } catch(e) {}
                } else if (filterVal === 'big_eyes') {
                    // 👀 3D Glubschaugen (Anime)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.35, 35, 30, 200, 80);
                    } catch(e) {}
                } else if (filterVal === 'tiny_face') {
                    // 🤏 3D Schrumpf-Gesicht (Meme)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.6, 95, 65, 80, 80);
                    } catch(e) {}
                } else if (filterVal === 'big_mouth') {
                    // 👄 3D Riesenmund
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.55, cw * 0.6, ch * 0.4, 50, 100, 170, 75);
                    } catch(e) {}
                } else if (filterVal === 'hourglass') {
                    // ⏳ 3D Sanduhr / Wespentaille (Pinch)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(5, 4);
                    ctx.lineTo(265, 4);
                    ctx.bezierCurveTo(195, 90, 195, 90, 265, 178);
                    ctx.lineTo(5, 178);
                    ctx.bezierCurveTo(75, 90, 75, 90, 5, 4);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'fisheye') {
                    // 🐟 3D Fischauge / Glaskugel
                    ctx.save();
                    ctx.beginPath();
                    ctx.ellipse(135, 90, 130, 86, 0, 0, Math.PI * 2);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx + cw * 0.1, cy + ch * 0.1, cw * 0.8, ch * 0.8, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'mirror_left') {
                    // 🪞 Doppel-Links: Linke Hälfte auf rechts gespiegelt
                    try {
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.save();
                        ctx.translate(270, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'mirror_right') {
                    // 🪞 Doppel-Rechts: Rechte Hälfte auf links gespiegelt
                    try {
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 135, 0, 135, 180);
                        ctx.save();
                        ctx.translate(135, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'stretch_vert') {
                    // 📏 Bleistift-Kopf
                    try {
                        ctx.drawImage(vid, cx + cw * 0.22, cy, cw * 0.56, ch, 0, 0, 270, 180);
                    } catch(e) {}
                } else if (filterVal === 'squish_wide') {
                    // 🗜️ Wide Meme
                    try {
                        ctx.drawImage(vid, cx, cy + ch * 0.2, cw, ch * 0.6, 0, 0, 270, 180);
                    } catch(e) {}
                } else {
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                    } catch(e) {}
                }

                // Filter Badge Tag anzeigen
                if (filterVal && filterVal !== 'none') {
                    const filterLabels = {
                        triangle: '🔺 3D Dreimacs Pyramide',
                        inv_triangle: '🔻 3D Trichter-Kopf',
                        diamond: '💎 3D Diamant-Kopf',
                        cube: '📦 3D Block-Kopf',
                        gigachad: '🗿 3D Gigachad Kiefer',
                        alien: '👽 3D Megamind Alien',
                        hamster: '🎈 3D Hamsterbacken',
                        pinocchio: '🤥 3D Pinocchio Langnase',
                        big_eyes: '👀 3D Glubschaugen',
                        tiny_face: '🤏 3D Schrumpf-Gesicht',
                        big_mouth: '👄 3D Riesenmund',
                        hourglass: '⏳ 3D Sanduhr Pinch',
                        fisheye: '🐟 3D Glaskugel Fischauge',
                        swirl: '🌀 3D Strudel Twist',
                        wave: '🌊 3D Wackelpudding',
                        mirror_left: '🪞 Doppel-Links',
                        mirror_right: '🪞 Doppel-Rechts',
                        stretch_vert: '📏 Bleistift-Kopf',
                        squish_wide: '🗜️ Wide Meme'
                    };
                    const tag = filterLabels[filterVal] || filterVal;
                    ctx.save();
                    ctx.font = 'bold 9px sans-serif';
                    const tw = ctx.measureText(tag).width;
                    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
                    ctx.strokeStyle = '#34d399';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    if (ctx.roundRect) ctx.roundRect(8, 8, tw + 14, 18, 4);
                    else ctx.rect(8, 8, tw + 14, 18);
                    ctx.fill();
                    ctx.stroke();
                    ctx.fillStyle = '#34d399';
                    ctx.textAlign = 'left';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(tag, 15, 17);
                    ctx.restore();
                }

                // Divider Seam
                ctx.fillStyle = '#1e1b4b';
                ctx.fillRect(0, 178, 270, 4);
                ctx.fillStyle = '#c084fc';
                ctx.fillRect(0, 179, 270, 2);

                // 2. Bottom Section: Gameplay (1080x1200 in 1080x1920 -> 270x300 px)
                const gx = cropState.game.x * vw;
                const gy = cropState.game.y * vh;
                const gw = Math.max(16, cropState.game.w * vw);
                const gh = Math.max(16, cropState.game.h * vh);

                try {
                    ctx.drawImage(vid, gx, gy, gw, gh, 0, 180, 270, 300);
                } catch(e) {}

                // Hook Sticker Badge Simulation
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, 180 - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, 180 - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, 180);

            } else {
                // 📱 Reines Vollbild-Gameplay (Festes 9:16 Short)
                const gx = cropState.game.x * vw;
                const gy = cropState.game.y * vh;
                const gw = Math.max(16, cropState.game.w * vw);
                const gh = Math.max(16, cropState.game.h * vh);

                try {
                    ctx.drawImage(vid, gx, gy, gw, gh, 0, 0, 270, 480);
                } catch(e) {}

                // Hook Sticker Simulation (oben bei y=120)
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                const stickerY = 120;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);
            }

            // Subtitle Preview Simulation
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillStyle = '#fde047';
            ctx.strokeStyle = '#000000';
            ctx.lineWidth = 2.5;
            ctx.strokeText("💬 [Untertitel Bereich]", 135, 435);
            ctx.fillText("💬 [Untertitel Bereich]", 135, 435);
        }

        async function saveCropCoordinates(renderNow) {
            if (!currentCropClipId) return;
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            let editedTranscript = null;
            const formEl = document.getElementById('form-' + currentCropClipId);
            if (formEl) {
                const txEl = formEl.querySelector('textarea[name="transcript"]');
                if (txEl) editedTranscript = txEl.value;
            }

            let payload;
            if (currentCropMode === 'single_916') {
                payload = {
                    layout_mode: 'single_916',
                    render_now: renderNow,
                    transcript: editedTranscript,
                    custom_crops: {
                        mode: 'single_916',
                        enabled: true,
                        single: {
                            x_pct: cropState.single.x,
                            y_pct: 0.0,
                            w_pct: cropState.single.w,
                            h_pct: 1.0,
                            x: Math.round(cropState.single.x * vw),
                            y: 0,
                            w: Math.round(cropState.single.w * vw),
                            h: vh
                        }
                    }
                };
            } else {
                payload = {
                    layout_mode: 'custom',
                    render_now: renderNow,
                    transcript: editedTranscript,
                    custom_crops: {
                        mode: 'split',
                        enabled: true,
                        cam: {
                            x_pct: cropState.cam.x,
                            y_pct: cropState.cam.y,
                            w_pct: cropState.cam.w,
                            h_pct: cropState.cam.h,
                            x: Math.round(cropState.cam.x * vw),
                            y: Math.round(cropState.cam.y * vh),
                            w: Math.round(cropState.cam.w * vw),
                            h: Math.round(cropState.cam.h * vh),
                            enabled: cropState.cam.enabled
                        },
                        game: {
                            x_pct: cropState.game.x,
                            y_pct: cropState.game.y,
                            w_pct: cropState.game.w,
                            h_pct: cropState.game.h,
                            x: Math.round(cropState.game.x * vw),
                            y: Math.round(cropState.game.y * vh),
                            w: Math.round(cropState.game.w * vw),
                            h: Math.round(cropState.game.h * vh),
                            enabled: true
                        }
                    }
                };
            }

            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            if (modalFilterSelect) {
                payload.cam_filter = modalFilterSelect.value;
                const cardFilterSelect = document.querySelector(`form[action="/save/${currentCropClipId}"] select[name="cam_filter"]`);
                if (cardFilterSelect) cardFilterSelect.value = modalFilterSelect.value;
            }

            try {
                const resp = await fetch(`/api/clip/${currentCropClipId}/save-crop`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (res.success) {
                    closeCropModal();
                    if (renderNow) {
                        const renderCard = document.getElementById('render-progress-card');
                        if (renderCard) renderCard.classList.remove('hidden');
                    }
                }
            } catch (e) {
                alert('Fehler beim Speichern: ' + e);
            }
        }

        async function startTikTokBrowserLogin() {
            const btn = document.getElementById('btn-tt-browser-login');
            const box = document.getElementById('tt-browser-status-box');
            const text = document.getElementById('tt-browser-status-text');

            if (btn) {
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
            }
            if (box) box.classList.remove('hidden');
            if (text) text.innerText = 'Chrome wird gestartet... Bitte im geöffneten Fenster einloggen (z. B. QR-Code scannen)!';

            try {
                const resp = await fetch('/api/accounts/tiktok/browser-login', { method: 'POST' });
                const data = await resp.json();
                if (!data.success) {
                    alert(data.message);
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('opacity-70', 'cursor-not-allowed');
                    }
                    if (box) box.classList.add('hidden');
                    return;
                }

                const pollTimer = setInterval(async () => {
                    try {
                        const sResp = await fetch('/api/accounts/tiktok/browser-login/status');
                        const sData = await sResp.json();
                        if (text && sData.message) text.innerText = sData.message;

                        if (!sData.running) {
                            clearInterval(pollTimer);
                            if (sData.message && sData.message.includes('Erfolgreich')) {
                                if (text) text.innerText = '✅ Erfolgreich verbunden! Aktualisiere Dashboard...';
                                setTimeout(() => window.location.reload(), 1200);
                            } else {
                                if (btn) {
                                    btn.disabled = false;
                                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                                }
                                setTimeout(() => { if (box) box.classList.add('hidden'); }, 4000);
                            }
                        }
                    } catch (err) {
                        console.error('Polling status error:', err);
                    }
                }, 1500);

            } catch (err) {
                alert('Fehler beim Starten des Browser-Logins: ' + err);
                if (btn) {
                    btn.disabled = false;
                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                }
                if (box) box.classList.add('hidden');
            }
        }

        async function startYouTubeOAuthLogin() {
            const btn = document.getElementById('btn-yt-login');
            const box = document.getElementById('yt-login-status-box');
            const text = document.getElementById('yt-login-status-text');

            if (btn) {
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
            }
            if (box) box.classList.remove('hidden');
            if (text) text.innerText = 'Google-Anmeldung wird vorbereitet...';

            try {
                const resp = await fetch('/api/accounts/youtube/authorize', { method: 'POST' });
                const data = await resp.json();
                if (!data.success || !data.auth_url) {
                    alert(data.message || 'Fehler beim Starten der Google-Anmeldung.');
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('opacity-70', 'cursor-not-allowed');
                    }
                    if (box) box.classList.add('hidden');
                    return;
                }

                // Im neuen Tab öffnen!
                window.open(data.auth_url, '_blank');
                if (text) text.innerText = '👉 Google-Login im neuen Tab geöffnet! Wähle deinen YouTube-Kanal und klicke auf "Zulassen"...';

                // Status überwachen bis YouTube auf verbunden springt
                const pollTimer = setInterval(async () => {
                    try {
                        const aResp = await fetch('/api/accounts/status');
                        const aData = await aResp.json();
                        if (aData && aData.youtube && aData.youtube.is_connected) {
                            clearInterval(pollTimer);
                            if (text) text.innerText = '✅ YouTube erfolgreich verbunden! Seite wird aktualisiert...';
                            setTimeout(() => window.location.reload(), 1500);
                        }
                    } catch (err) {
                        console.error('Polling YT status error:', err);
                    }
                }, 1500);

            } catch (err) {
                alert('Fehler: ' + err);
                if (btn) {
                    btn.disabled = false;
                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                }
                if (box) box.classList.add('hidden');
            }
        }

        setInterval(updateStatus, 1500);
        updateStatus();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
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
        scheduled_rows = cursor.fetchall()

        # Published Clips
        cursor.execute("SELECT * FROM clips WHERE status = 'published' ORDER BY rowid DESC")
        published_rows = cursor.fetchall()

    ready_clips = []
    for r in ready_rows:
        clip_id = r["clip_id"]
        meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
        sticker_text = ""
        title = r["ai_title"] or r["original_title"] or ""
        sub_position = "bottom"
        
        is_manually_published = bool(r["is_manually_published"]) if "is_manually_published" in r.keys() and r["is_manually_published"] else False
        cam_filter = "none"
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

    return render_template_string(
        HTML_DASHBOARD,
        counts=counts,
        ready_clips=ready_clips,
        queue_clips=queue_rows,
        older_queue_count=older_queue_count,
        scheduled_clips=scheduled_rows,
        published_clips=published_rows,
        account_status=account_status,
        streamers=all_streamers,
        streamer_counts=streamer_counts,
        cam_filters=AVAILABLE_CAM_FILTERS
    )

@app.route("/api/status")
def get_status():
    return jsonify(status_manager.get_state())

@app.route("/api/run", methods=["POST"])
def trigger_run_api():
    """Startet das Suchen & Herunterladen auf Twitch."""
    if not status_manager.get_state().get("is_running", False):
        from src.scheduler import PipelineOrchestrator
        orch = PipelineOrchestrator()
        
        def run_harvest_background():
            status_manager.set_task("harvesting", "Scanne Twitch-Streamer nach neuen Clips...")
            streamers = orch.config.get("streamers", [])
            for s in streamers:
                if s.get("enabled", True):
                    status_manager.set_task("harvesting", "Scanne Twitch...", streamer=s.get("name"))
                    orch.harvester.harvest_channel(s)
            status_manager.set_task("idle", "Clips heruntergeladen und in Warteschlange gespeichert.")

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
        def run_all_worker():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT clip_id FROM clips WHERE status = 'harvested' ORDER BY view_count DESC")
                clips = cursor.fetchall()

            for idx, c in enumerate(clips, 1):
                status_manager.set_task("processing", f"Schneide Clip [{idx}/{len(clips)}]...")
                process_single_clip(c["clip_id"])

            status_manager.set_task("idle", f"Alle {len(clips)} Clips fertig ins Studio übertragen.")

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
    print(f"  🎬 CLIP-FARMING MISSION CONTROL GESTARTET!")
    print(f"  👉 Öffne im Browser: http://localhost:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

if __name__ == "__main__":
    start_studio()
