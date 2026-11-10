import os
import json
import requests
from typing import Dict, Any, Optional
from src.config import load_config, METADATA_OUTPUT_DIR

class MetadataGenerator:
    def __init__(self):
        self.config = load_config()
        self.ai_cfg = self.config.get("ai_copywriter", {})
        self.provider = self.ai_cfg.get("provider", "gemini")
        self.api_key = self.ai_cfg.get("api_key", "").strip() or os.getenv("GEMINI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        self.model = self.ai_cfg.get("model", "gemini-2.5-flash")

    def _generate_fallback(self, clip_title: str, streamer: str) -> Dict[str, str]:
        """Offline-Fallback, falls kein LLM API-Key angegeben wurde."""
        title = clip_title.strip()
        if len(title) > 48:
            title = title[:45] + "..."
        
        description = (
            f"{title} 😱\n\n"
            f"🎥 Streamer: twitch.tv/{streamer}\n"
            f"#shorts #twitchdeutschland #gaming #{streamer.lower()} #clips"
        )
        pinned_comment = f"Was hättet ihr an der Stelle von {streamer} gemacht? Schreibt's in die Kommentare! 👇"

        return {
            "title": title,
            "description": description,
            "pinned_comment": pinned_comment,
            "tags": f"shorts,twitch,{streamer},gaming,clips"
        }

    def generate(self, original_title: str, streamer: str, transcript: str) -> Dict[str, str]:
        """
        Generiert per LLM virale Metadaten (Titel, Beschreibung, Pinned Comment).
        """
        if not self.api_key:
            return self._generate_fallback(original_title, streamer)

        prompt = f"""Du bist ein Experte für virale YouTube Shorts und TikToks im deutschen Gaming/Twitch-Bereich.
Analysiere folgenden Twitch-Clip und erstelle fesselnde Metadaten:

Streamer: {streamer}
Originaler Clip-Titel: {original_title}
Transkript des Clips:
\"\"\"{transcript[:1200]}\"\"\"

Antworte NUR mit einem validen JSON-Objekt im folgenden Format (ohne Markdown Backticks):
{{
  "title": "Maximal 48 Zeichen langer, packender Titel mit Neugier-Trigger und 1-2 Emojis",
  "description": "2 kurze Sätze zum Inhalt des Clips, gefolgt von Credits und 4-5 relevanten Hashtags",
  "pinned_comment": "Eine provokante oder neugierige Frage an die Zuschauer zum Kommentieren",
  "tags": "kommagetrennte,tags,fuer,youtube"
}}
"""

        try:
            if self.provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500}
                }
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if text.startswith("```"):
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    data = json.loads(text.strip())
                    return data
            elif self.provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {self.api_key}"}
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    return json.loads(resp.json()["choices"][0]["message"]["content"])
        except Exception as e:
            print(f"[!] Fehler bei der LLM-Generierung ({e}). Nutze Fallback...")

        return self._generate_fallback(original_title, streamer)
