import os
import sys
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import subprocess
import json

from src.config import RAW_CLIPS_DIR, load_config
from src.database import is_clip_already_processed, save_clip

TWITCH_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"

class TwitchClipHarvester:
    def __init__(self):
        self.config = load_config()
        self.twitch_cfg = self.config.get("twitch", {})
        self.client_id = self.twitch_cfg.get("client_id", "").strip()
        self.client_secret = self.twitch_cfg.get("client_secret", "").strip()
        self.access_token = None

    def _get_app_access_token(self) -> Optional[str]:
        """Holt ein OAuth App Access Token über die offizielle Twitch API."""
        if not self.client_id or not self.client_secret:
            return None
        if self.access_token:
            return self.access_token

        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        try:
            resp = requests.post(url, params=params, timeout=10)
            if resp.status_code == 200:
                self.access_token = resp.json().get("access_token")
                return self.access_token
        except Exception as e:
            print(f"[!] Fehler beim Abrufen des Twitch Tokens: {e}")
        return None

    def fetch_clips_gql_fallback(self, channel_name: str, time_filter: str = "LAST_DAY", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Zero-Config Fallback: Holt aktuelle Clips direkt über die 
        öffentliche Twitch GQL-Schnittstelle.
        time_filter Optionen: 'LAST_DAY', 'LAST_WEEK', 'ALL_TIME'
        """
        headers = {"Client-ID": TWITCH_GQL_CLIENT_ID}
        query = f"""
        query($login: String!, $limit: Int!) {{
            user(login: $login) {{
                id
                login
                clips(first: $limit, criteria: {{ filter: {time_filter} }}) {{
                    edges {{
                        node {{
                            id
                            slug
                            title
                            viewCount
                            durationSeconds
                            createdAt
                            url
                        }}
                    }}
                }}
            }}
        }}
        """
        payload = {
            "query": query,
            "variables": {"login": channel_name.lower(), "limit": limit}
        }

        try:
            resp = requests.post(TWITCH_GQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            user_data = data.get("data", {}).get("user")
            if not user_data or not user_data.get("clips"):
                return []

            edges = user_data["clips"].get("edges", [])
            clips = []
            for edge in edges:
                node = edge.get("node", {})
                clips.append({
                    "clip_id": node.get("slug") or node.get("id"),
                    "streamer": channel_name,
                    "platform": "twitch",
                    "title": node.get("title", "Clip"),
                    "url": node.get("url") or f"https://clips.twitch.tv/{node.get('slug')}",
                    "view_count": node.get("viewCount", 0),
                    "duration": float(node.get("durationSeconds", 30.0)),
                    "created_at": node.get("createdAt")
                })
            return clips
        except Exception as e:
            print(f"[!] GQL-Fehler bei Kanal {channel_name}: {e}")
            return []

    def fetch_clips_helix(self, channel_name: str, hours_back: int = 24) -> List[Dict[str, Any]]:
        """Holt Clips über die offizielle Twitch Helix API."""
        token = self._get_app_access_token()
        if not token:
            return self.fetch_clips_gql_fallback(channel_name)

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        # 1. User ID holen
        user_resp = requests.get(f"https://api.twitch.tv/helix/users?login={channel_name}", headers=headers, timeout=10)
        if user_resp.status_code != 200 or not user_resp.json().get("data"):
            return self.fetch_clips_gql_fallback(channel_name)
        
        user_id = user_resp.json()["data"][0]["id"]

        # 2. Prüfen, ob der Streamer aktuell live ist (um started_at zu nutzen)
        started_at_str = None
        stream_resp = requests.get(f"https://api.twitch.tv/helix/streams?user_id={user_id}", headers=headers, timeout=10)
        if stream_resp.status_code == 200 and stream_resp.json().get("data"):
            started_at_str = stream_resp.json()["data"][0]["started_at"]
        else:
            # Wenn offline: Zeitfenster der letzten X Stunden
            dt = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            started_at_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 3. Clips abrufen
        clips_url = f"https://api.twitch.tv/helix/clips?broadcaster_id={user_id}&started_at={started_at_str}&first=50"
        clips_resp = requests.get(clips_url, headers=headers, timeout=10)
        if clips_resp.status_code != 200:
            return self.fetch_clips_gql_fallback(channel_name)

        clips_data = clips_resp.json().get("data", [])
        result = []
        for c in clips_data:
            result.append({
                "clip_id": c.get("id"),
                "streamer": channel_name,
                "platform": "twitch",
                "title": c.get("title", "Clip"),
                "url": c.get("url"),
                "view_count": c.get("view_count", 0),
                "duration": float(c.get("duration", 30.0)),
                "created_at": c.get("created_at")
            })
        return result

    def download_clip(self, clip_url: str, clip_id: str) -> Optional[Path]:
        """Lädt einen Clip portabel per yt-dlp in den raw-Ordner herunter."""
        output_path = RAW_CLIPS_DIR / f"{clip_id}.mp4"
        if output_path.exists() and output_path.stat().st_size > 1000:
            return output_path

        # Wir nutzen das python modul yt_dlp oder das command line tool
        try:
            import yt_dlp
            ydl_opts = {
                'outtmpl': str(output_path),
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clip_url])
            
            if output_path.exists() and output_path.stat().st_size > 1000:
                return output_path
        except Exception as e:
            print(f"[!] Download via yt_dlp Modul fehlgeschlagen ({e}), versuche CLI Fallback...")

        # Fallback via Subprocess
        cmd = [
            "yt-dlp",
            "-o", str(output_path),
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            clip_url
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
            if output_path.exists() and output_path.stat().st_size > 1000:
                return output_path
            else:
                print(f"[!] Fehler beim Download von {clip_url}: {res.stderr}")
        except Exception as err:
            print(f"[!] Ausnahme beim Downloaden von {clip_url}: {err}")

        return None

    def harvest_channel(self, streamer_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Harvested die besten neuen Clips für einen Streamer."""
        # Konfiguration stets frisch laden
        self.config = load_config()
        self.twitch_cfg = self.config.get("twitch", {})
        autopilot_cfg = self.config.get("autopilot", {})

        channel_name = streamer_cfg.get("name")
        min_views = streamer_cfg.get("min_clip_views", 50)
        max_clips = streamer_cfg.get("max_clips_per_run", 3)
        hours_back = self.twitch_cfg.get("hours_back", 12)
        time_filter = (
            streamer_cfg.get("time_filter")
            or autopilot_cfg.get("time_filter")
            or self.twitch_cfg.get("time_filter", "LAST_DAY")
        )

        print(f"[*] Scanne Kanal: {channel_name} (Filter: {time_filter}, Min-Views: {min_views}, Max: {max_clips})...")

        # 1. Frische Clips abrufen (Helix oder GQL)
        if self.client_id and self.client_secret:
            all_clips = self.fetch_clips_helix(channel_name, hours_back=hours_back)
        else:
            all_clips = self.fetch_clips_gql_fallback(channel_name, time_filter=time_filter, limit=50)

        # 2. Filtern: Noch nicht verarbeitet und mind. min_views
        unprocessed_fresh = [
            c for c in all_clips 
            if not is_clip_already_processed(c["clip_id"]) and c["view_count"] >= min_views
        ]

        # Frische Clips immer zuerst nach Views sortieren und bis zu max_clips übernehmen!
        unprocessed_fresh.sort(key=lambda x: x["view_count"], reverse=True)
        selected_clips = list(unprocessed_fresh[:max_clips])

        # 2b. Intelligenter Wochen-Fallback: NUR wenn noch Plätze frei sind UND fallback_to_week aktiv ist!
        fallback_enabled = autopilot_cfg.get("fallback_to_week", True)
        if "fallback_to_week" in streamer_cfg:
            fallback_enabled = bool(streamer_cfg["fallback_to_week"])

        needed_slots = max_clips - len(selected_clips)
        if needed_slots > 0 and time_filter == "LAST_DAY" and fallback_enabled and not (self.client_id and self.client_secret):
            print(f"  [i] {len(selected_clips)}/{max_clips} frische Clips (24h) für {channel_name}. Prüfe beste Clips der Woche für {needed_slots} Rest-Plätze...")
            week_clips = self.fetch_clips_gql_fallback(channel_name, time_filter="LAST_WEEK", limit=50)
            existing_ids = {c["clip_id"] for c in selected_clips}
            week_candidates = [
                c for c in week_clips
                if c["clip_id"] not in existing_ids and not is_clip_already_processed(c["clip_id"]) and c["view_count"] >= min_views
            ]
            week_candidates.sort(key=lambda x: x["view_count"], reverse=True)
            # Nur die tatsächlich noch benötigten Restplätze mit den besten Wochen-Clips auffüllen!
            selected_clips.extend(week_candidates[:needed_slots])

        if not selected_clips:
            print(f"[-] Keine neuen qualifizierten Clips für {channel_name} gefunden.")
            return []

        downloaded_clips = []
        for clip in selected_clips:
            print(f"  -> Gefunden: \"{clip['title']}\" ({clip['view_count']} Views) - Lade herunter...")
            raw_path = self.download_clip(clip["url"], clip["clip_id"])
            if raw_path:
                clip["raw_path"] = str(raw_path)
                save_clip(clip)
                downloaded_clips.append(clip)
                print(f"  [+] Gespeichert: {raw_path.name}")
            else:
                print(f"  [-] Download fehlgeschlagen: {clip['clip_id']}")

        return downloaded_clips
