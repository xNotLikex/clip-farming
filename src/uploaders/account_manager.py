import json
import os
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

from src.config import PROJECT_ROOT, CONFIG_DIR, DATA_DIR, load_config

CONFIG_PATH = CONFIG_DIR / "config.yaml"
SECRETS_FILE = CONFIG_DIR / "youtube_secrets.json"
TOKEN_FILE = DATA_DIR / "youtube_token.json"
TIKTOK_SESSION_FILE = DATA_DIR / "tiktok_session.json"

class AccountManager:
    def __init__(self):
        self.config_path = CONFIG_PATH

    def get_status(self) -> Dict[str, Any]:
        """Liefert den aktuellen Verbindungsstatus aller Plattformen."""
        cfg = load_config()
        pub_cfg = cfg.get("publishing", {})
        yt_cfg = pub_cfg.get("youtube", {})
        tt_cfg = pub_cfg.get("tiktok", {})

        # 1. YouTube Status prüfen
        yt_has_secrets = SECRETS_FILE.exists() and SECRETS_FILE.stat().st_size > 20
        yt_has_token = TOKEN_FILE.exists() and TOKEN_FILE.stat().st_size > 20
        yt_enabled = yt_cfg.get("enabled", False)
        yt_privacy = yt_cfg.get("privacy_status", "private")

        yt_channel_name = None
        if yt_has_token:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
                if creds and creds.valid:
                    yt = build("youtube", "v3", credentials=creds)
                    ch_res = yt.channels().list(part="snippet", mine=True).execute()
                    items = ch_res.get("items", [])
                    if items:
                        yt_channel_name = items[0]["snippet"]["title"]
            except Exception:
                pass

        # 2. TikTok Status prüfen
        tt_session_id = ""
        if TIKTOK_SESSION_FILE.exists():
            try:
                with open(TIKTOK_SESSION_FILE, "r", encoding="utf-8") as f:
                    tdata = json.load(f)
                    tt_session_id = tdata.get("session_id", "")
            except Exception:
                pass
        if not tt_session_id:
            tt_session_id = tt_cfg.get("session_id", "")

        tt_has_session = bool(tt_session_id and len(tt_session_id) > 10)
        tt_enabled = tt_cfg.get("enabled", False)
        tt_mode = tt_cfg.get("upload_mode", "draft")

        return {
            "youtube": {
                "has_secrets": yt_has_secrets,
                "has_token": yt_has_token,
                "is_connected": yt_has_token,
                "enabled": yt_enabled,
                "privacy_status": yt_privacy,
                "channel_name": yt_channel_name or ("Verbunden" if yt_has_token else None)
            },
            "tiktok": {
                "has_session": tt_has_session,
                "is_connected": tt_has_session,
                "enabled": tt_enabled,
                "upload_mode": tt_mode,
                "session_id_preview": (tt_session_id[:6] + "..." + tt_session_id[-4:]) if tt_has_session else ""
            },
            "publishing_interval": pub_cfg.get("interval_minutes", 30)
        }

    def save_youtube_secrets(self, content_str: str) -> bool:
        """Speichert die client_secrets.json und aktiviert YouTube in der Konfiguration."""
        try:
            data = json.loads(content_str)
            SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SECRETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self._update_yaml_publishing({"youtube": {"enabled": True}})
            return True
        except Exception as e:
            print(f"[!] Fehler beim Speichern von youtube_secrets: {e}")
            return False

    def save_youtube_client_credentials(self, client_id: str, client_secret: str) -> bool:
        """Erzeugt und speichert die youtube_secrets.json anhand von Client-ID und Client-Secret."""
        data = {
            "installed": {
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"]
            }
        }
        return self.save_youtube_secrets(json.dumps(data))

    def start_youtube_oauth(self, port: int = 8088) -> Dict[str, Any]:
        """Startet den YouTube OAuth Flow im Hintergrund und liefert die Auth-URL für das Browser-Fenster."""
        from google_auth_oauthlib.flow import InstalledAppFlow
        SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]

        if not SECRETS_FILE.exists():
            return {"success": False, "message": "Bitte trage zuerst deine Google Client-ID und Client-Secret ein!"}

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_FILE), SCOPES)
            flow.redirect_uri = f"http://localhost:{port}/"
            auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

            def oauth_worker():
                try:
                    creds = flow.run_local_server(port=port, open_browser=False)
                    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(TOKEN_FILE, "w", encoding="utf-8") as tf:
                        tf.write(creds.to_json())

                    self._update_yaml_publishing({"youtube": {"enabled": True}})
                    print("[+] YouTube Konto erfolgreich via OAuth verbunden!")
                except Exception as e:
                    print(f"[!] YouTube OAuth Fehler: {e}")

            t = threading.Thread(target=oauth_worker, daemon=True)
            t.start()

            return {
                "success": True,
                "auth_url": auth_url,
                "message": "Google Login URL erzeugt."
            }
        except Exception as e:
            return {"success": False, "message": f"Fehler beim Erstellen der Google-Anmeldung: {e}"}

    def authorize_youtube(self) -> Dict[str, Any]:
        """Startet den Google OAuth 2.0 Flow im Browser."""
        return self.start_youtube_oauth()

    def disconnect_youtube(self):
        """Trennt die YouTube-Verbindung."""
        if TOKEN_FILE.exists():
            try:
                TOKEN_FILE.unlink()
            except Exception:
                pass
        self._update_yaml_publishing({"youtube": {"enabled": False}})

    def update_youtube_settings(self, enabled: bool, privacy_status: str):
        self._update_yaml_publishing({
            "youtube": {
                "enabled": enabled,
                "privacy_status": privacy_status
            }
        })

    def save_tiktok_session(self, session_id: str, upload_mode: str = "draft", enabled: bool = True):
        """Speichert die TikTok Session-ID."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(TIKTOK_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"session_id": session_id.strip(), "upload_mode": upload_mode}, f, indent=2)

        self._update_yaml_publishing({
            "tiktok": {
                "enabled": enabled,
                "upload_mode": upload_mode,
                "session_id": session_id.strip()
            }
        })

    def disconnect_tiktok(self):
        """Trennt die TikTok-Verknüpfung."""
        if TIKTOK_SESSION_FILE.exists():
            try:
                TIKTOK_SESSION_FILE.unlink()
            except Exception:
                pass
        self._update_yaml_publishing({
            "tiktok": {
                "enabled": False,
                "session_id": ""
            }
        })

    def set_publishing_interval(self, minutes: int):
        self._update_yaml_publishing({"interval_minutes": max(5, int(minutes))})

    def _update_yaml_publishing(self, updates: Dict[str, Any]):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            if "publishing" not in cfg:
                cfg["publishing"] = {}

            for k, v in updates.items():
                if isinstance(v, dict) and isinstance(cfg["publishing"].get(k), dict):
                    cfg["publishing"][k].update(v)
                else:
                    cfg["publishing"][k] = v

            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"[!] Fehler beim Aktualisieren der config.yaml: {e}")

account_manager = AccountManager()
