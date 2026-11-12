import json
import logging
from pathlib import Path

from src.config import DATA_DIR, load_config

logger = logging.getLogger(__name__)


class TikTokUploader:
    def __init__(self):
        self.config = load_config()
        self.tt_cfg = self.config.get("publishing", {}).get("tiktok", {})
        self.session_file = DATA_DIR / "tiktok_session.json"
        self.enabled = self.tt_cfg.get("enabled", False)
        self.upload_mode = self.tt_cfg.get("upload_mode", "draft")

    def get_session_id(self) -> str | None:
        if self.session_file.exists():
            try:
                with open(self.session_file, encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("session_id")
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Konnte tiktok_session.json nicht lesen: %s", exc)
        return self.tt_cfg.get("session_id")

    def is_configured(self) -> bool:
        sid = self.get_session_id()
        return bool(self.enabled and sid and len(sid) > 10)

    def upload_short(self, video_path: Path, caption: str) -> str | None:
        """
        TikTok-Upload ist aktuell nicht implementiert (Stub entfernt, kein Fake-Erfolg).
        Gibt immer None zurück, damit kein Clip fälschlich als 'published' markiert wird.
        """
        sid = self.get_session_id()
        if not self.enabled or not sid:
            print("[i] TikTok Upload übersprungen: In Konten-Einstellungen nicht aktiviert oder keine Session-ID hinterlegt.")
            return None

        print(f"[!] TikTok-Upload nicht implementiert – Upload für \"{caption[:50]}\" abgebrochen.")
        return None
