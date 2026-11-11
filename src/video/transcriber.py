from pathlib import Path
from typing import List, Dict, Any, Optional
from src.config import load_config

class VideoTranscriber:
    def __init__(self):
        self.config = load_config()
        video_cfg = self.config.get("video", {})
        self.model_size = video_cfg.get("whisper_model", "small")
        self.device = video_cfg.get("device", "cuda")
        self.model = None

    def _load_model(self):
        if self.model is None:
            from faster_whisper import WhisperModel
            print(f"[*] Lade faster-whisper Modell '{self.model_size}' auf {self.device}...")
            compute_type = "float16" if self.device == "cuda" else "int8"
            try:
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
            except Exception as e:
                print(f"[!] Warnung: CUDA nicht verfuegbar oder Fehler ({e}). Wechsle zu CPU...")
                self.device = "cpu"
                self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_or_video_path: Path, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Transkribiert das Video/Audio und liefert Segmente mit exakten Word-Level Timestamps.
        M10 Audit-Fix: Sprache standardmäßig auf None (Auto-Detection) oder dynamisch wählbar.
        """
        self._load_model()
        segments_data = []

        # Falls language None ist, erkennt Whisper die Sprache automatisch
        transcribe_kwargs = {
            "word_timestamps": True,
            "vad_filter": True,
            "vad_parameters": dict(min_silence_duration_ms=500)
        }
        if language:
            transcribe_kwargs["language"] = language

        segments, info = self.model.transcribe(
            str(audio_or_video_path),
            **transcribe_kwargs
        )

        for seg in segments:
            words = []
            if seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability
                    })
            segments_data.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": words
            })

        return segments_data

    def get_full_transcript(self, segments: List[Dict[str, Any]]) -> str:
        """Gibt den gesamten transkribierten Text als zusammenhängenden String zurück."""
        return " ".join([s["text"] for s in segments if s.get("text")])
