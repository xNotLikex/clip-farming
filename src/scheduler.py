import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import (
    load_config, RAW_CLIPS_DIR, SHORTS_OUTPUT_DIR, METADATA_OUTPUT_DIR
)
from src.database import get_pending_clips, update_clip_status
from src.harvesters.twitch_clips import TwitchClipHarvester
from src.video.transcriber import VideoTranscriber
from src.video.subtitles import SubtitleGenerator
from src.video.layout import VideoComposer
from src.meta.generator import MetadataGenerator
from src.uploaders.youtube import YouTubeUploader
from src.uploaders.tiktok import TikTokUploader
from src.state import status_manager

class PipelineOrchestrator:
    def __init__(self):
        self.config = load_config()
        self.harvester = TwitchClipHarvester()
        self.transcriber = VideoTranscriber()
        self.sub_gen = SubtitleGenerator()
        self.composer = VideoComposer()
        self.meta_gen = MetadataGenerator()
        self.yt_uploader = YouTubeUploader()
        self.tt_uploader = TikTokUploader()

    def run_cycle(self):
        """Fuehrt einen kompletten Harvesting-, Schneide- und Upload-Zyklus durch."""
        status_manager.state["is_running"] = True
        status_manager.set_task("starting", "Initialisiere Pipeline-Durchlauf...")
        print("\n" + "="*70)
        print("  🚀 [CLIP-FARMING] Starte neuen Durchlauf...")
        print("="*70)

        streamers = self.config.get("streamers", [])
        enabled_streamers = [s for s in streamers if s.get("enabled", True)]
        
        print(f"[*] {len(enabled_streamers)} Streamer aktiv in der Liste.")

        # 1. Harvesting Phase
        new_clips_count = 0
        for streamer in enabled_streamers:
            st_name = streamer.get("name")
            status_manager.set_task("harvesting", f"Scanne Twitch nach Clips...", streamer=st_name)
            harvested = self.harvester.harvest_channel(streamer)
            new_clips_count += len(harvested)

        print(f"\n[i] Harvesting abgeschlossen. {new_clips_count} neue Clips in der Pipeline.")

        # 2. Processing & Rendering Phase
        pending = get_pending_clips(limit=10)
        if not pending:
            status_manager.set_task("idle", "Keine offenen Clips in der Warteschlange. Standby.")
            status_manager.state["is_running"] = False
            print("[i] Keine offenen Clips zur Verarbeitung.")
            return

        print(f"[*] Verarbeite {len(pending)} Clips (Transkription, Untertitel, 9:16 Render)...")

        for idx, clip in enumerate(pending, 1):
            clip_id = clip["clip_id"]
            streamer = clip["streamer"]
            orig_title = clip.get('original_title', 'Clip')
            raw_path = Path(clip["raw_path"]) if clip.get("raw_path") else RAW_CLIPS_DIR / f"{clip_id}.mp4"

            if not raw_path.exists():
                print(f"[!] Rohdatei nicht gefunden: {raw_path}")
                update_clip_status(clip_id, "failed", error_log="Rohdatei nicht gefunden")
                continue

            try:
                # A. Transkription (faster-whisper)
                status_manager.set_task("transcribing", f"Transkribiere mit Whisper (CUDA)... [{idx}/{len(pending)}]", clip_title=orig_title, streamer=streamer)
                print(f"\n---> [{streamer}] Verarbeite Clip: \"{orig_title}\"")
                print("  [1/4] Erstelle Audio-Transkription & Word-Timestamps...")
                segments = self.transcriber.transcribe(raw_path)
                full_transcript = self.transcriber.get_full_transcript(segments)

                # B. Untertitel (.ass Datei mit Karaoke Highlight)
                status_manager.set_task("subtitles", "Generiere animierte Karaoke-Untertitel...", clip_title=orig_title, streamer=streamer)
                print("  [2/4] Generiere animierte Karaoke-Untertitel...")
                ass_path = RAW_CLIPS_DIR / f"{clip_id}.ass"
                self.sub_gen.generate_ass(segments, ass_path)

                # C. Virale Metadaten & Titel (LLM)
                status_manager.set_task("metadata", "Erstelle virale Titel & Hook...", clip_title=orig_title, streamer=streamer)
                print("  [3/4] Erstelle virale Titel, Beschreibung und Pinned Comment...")
                metadata = self.meta_gen.generate(
                    original_title=orig_title,
                    streamer=streamer,
                    transcript=full_transcript
                )
                
                # Metadaten als JSON sichern
                meta_file = METADATA_OUTPUT_DIR / f"{clip_id}.json"
                with open(meta_file, "w", encoding="utf-8") as mf:
                    json.dump(metadata, mf, indent=2, ensure_ascii=False)

                # D. 9:16 Video Rendering (KI Facecam-Check + TikTok Sticker Hook)
                status_manager.set_task("rendering", "Rendere 9:16 Short (NVENC GPU)...", clip_title=orig_title, streamer=streamer)
                print("  [4/4] Rendere vertikales 9:16 Short (NVENC GPU)...")
                layout_mode = "auto"
                for s in enabled_streamers:
                    if s["name"].lower() == streamer.lower():
                        layout_mode = s.get("layout", "auto")
                        break

                sticker_text = metadata.get("title") or orig_title

                rendered_path = self.composer.render_short(
                    raw_video_path=raw_path,
                    clip_id=clip_id,
                    ass_subtitle_path=ass_path,
                    header_sticker_text=sticker_text,
                    streamer_name=streamer,
                    layout_mode=layout_mode
                )

                if rendered_path and rendered_path.exists():
                    # E. Uploads durchfuehren (falls konfiguriert)
                    yt_id = None
                    tt_id = None
                    if self.config.get("publishing", {}).get("youtube", {}).get("enabled", False):
                        status_manager.set_task("uploading", "Lade auf YouTube Shorts hoch...", clip_title=orig_title, streamer=streamer)
                        yt_id = self.yt_uploader.upload_short(
                            video_path=rendered_path,
                            title=metadata.get("title", orig_title),
                            description=metadata.get("description", ""),
                            tags=metadata.get("tags", "")
                        )
                    
                    if self.config.get("publishing", {}).get("tiktok", {}).get("enabled", False):
                        status_manager.set_task("uploading", "Lade auf TikTok hoch...", clip_title=orig_title, streamer=streamer)
                        tt_id = self.tt_uploader.upload_short(
                            video_path=rendered_path,
                            caption=metadata.get("title", orig_title)
                        )

                    update_clip_status(
                        clip_id=clip_id,
                        status="published" if (yt_id or tt_id) else "ready",
                        rendered_path=str(rendered_path),
                        ai_title=metadata.get("title"),
                        ai_description=metadata.get("description"),
                        ai_tags=metadata.get("tags"),
                        youtube_video_id=yt_id,
                        tiktok_video_id=tt_id
                    )

                    print(f"  [OK] Clip {clip_id} erfolgreich fertiggestellt!")
                else:
                    update_clip_status(clip_id, "failed", error_log="Rendering fehlgeschlagen")

            except Exception as e:
                print(f"  [!] Unerwarteter Fehler bei Clip {clip_id}: {e}")
                update_clip_status(clip_id, "failed", error_log=str(e))

        status_manager.set_task("idle", f"Zyklus abgeschlossen. {len(pending)} Clips verarbeitet.")
        status_manager.state["is_running"] = False

    def run_forever(self, interval_minutes: int = 15):
        """Startet den vollautomatischen 24/7 Autopilot-Modus."""
        print(f"[*] Autopilot gestartet! Intervall: alle {interval_minutes} Minuten.")
        while True:
            try:
                self.run_cycle()
            except Exception as err:
                print(f"[!] Autopilot Fehler im Zyklus: {err}")
            
            print(f"\n[zZz] Warte {interval_minutes} Minuten bis zum nächsten Check... (Strg+C zum Beenden)")
            time.sleep(interval_minutes * 60)
