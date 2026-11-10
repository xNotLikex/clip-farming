import os
from pathlib import Path
from typing import Dict, Any, Optional
from src.config import DATA_DIR, load_config

class YouTubeUploader:
    def __init__(self):
        self.config = load_config()
        self.yt_cfg = self.config.get("publishing", {}).get("youtube", {})
        self.enabled = self.yt_cfg.get("enabled", False)
        self.privacy = self.yt_cfg.get("privacy_status", "private")
        self.secrets_file = Path(self.yt_cfg.get("client_secrets_file", "config/youtube_secrets.json"))
        self.token_file = DATA_DIR / "youtube_token.json"

    def is_configured(self) -> bool:
        return self.enabled and self.secrets_file.exists()

    def get_authenticated_service(self):
        """Authentifiziert den Google Account und erneuert das Token automatisch."""
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
        creds = None

        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.secrets_file.exists():
                    raise FileNotFoundError(
                        f"YouTube Client Secrets nicht gefunden unter: {self.secrets_file}\n"
                        "Bitte erstelle ein OAuth 2.0 Client-ID Projekt in der Google Cloud Console "
                        "und lade die JSON-Datei in den config-Ordner herunter."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.secrets_file), SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_file, "w", encoding="utf-8") as token_out:
                token_out.write(creds.to_json())

        return build("youtube", "v3", credentials=creds)

    def upload_short(self, video_path: Path, title: str, description: str, tags: str) -> Optional[str]:
        """
        Laedt ein fertiges 9:16 Video auf YouTube Shorts hoch.
        Gibt die YouTube Video-ID zurueck.
        """
        if not self.enabled:
            print("[i] YouTube Upload ist in config.yaml deaktiviert (enabled: false).")
            return None

        from googleapiclient.http import MediaFileUpload

        try:
            youtube = self.get_authenticated_service()
            print(f"[*] Starte YouTube Upload: \"{title}\" (Status: {self.privacy})...")

            # Sicherstellen, dass #Shorts in der Beschreibung ist
            if "#Shorts" not in description and "#shorts" not in description:
                description += "\n\n#Shorts #Gaming"

            tag_list = [t.strip() for t in tags.split(",") if t.strip()]

            body = {
                "snippet": {
                    "title": title[:100],
                    "description": description,
                    "tags": tag_list,
                    "categoryId": "20" # 20 = Gaming
                },
                "status": {
                    "privacyStatus": self.privacy,
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None

            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"    Upload Fortschritt: {int(status.progress() * 100)}%")

            video_id = response.get("id")
            print(f"[+] Erfolgreich hochgeladen! https://youtube.com/shorts/{video_id}")
            return video_id
        except Exception as e:
            print(f"[!] YouTube Upload Fehler: {e}")
            return None
