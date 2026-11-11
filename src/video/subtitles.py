import difflib
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.config import FONTS_DIR, load_config

def format_ass_time(seconds: float) -> str:
    """Konvertiert Sekunden in das ASS-Zeitformat: H:MM:SS.cs"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        secs += 1
        centis = 0
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def align_words_with_edited_text(orig_segments: Optional[List[Dict[str, Any]]], new_text: str, total_duration: float = 30.0) -> List[Dict[str, Any]]:
    """
    Passt die Zeitstempel der bestehenden Whisper-Wörter intelligent
    an den vom Benutzer korrigierten Text an.
    Erhält für unveränderte Wörter die exakten Original-Millisekunden und
    interpoliert geänderte oder neu hinzugefügte Wörter nahtlos.
    """
    new_words_raw = new_text.strip().split()
    if not new_words_raw:
        return []

    orig_words = []
    if orig_segments:
        for seg in orig_segments:
            for w in seg.get("words", []):
                if w.get("word", "").strip():
                    orig_words.append(w)

    if not orig_words:
        step = min(0.6, total_duration / max(1, len(new_words_raw)))
        result_words = []
        for i, nw in enumerate(new_words_raw):
            st = round(i * step, 2)
            et = round(st + step * 0.9, 2)
            result_words.append({"word": nw, "start": st, "end": et, "probability": 1.0})
        return [{"start": 0.0, "end": total_duration, "text": new_text, "words": result_words}]

    if len(new_words_raw) == len(orig_words):
        result_words = []
        for i, nw in enumerate(new_words_raw):
            result_words.append({
                "word": nw,
                "start": orig_words[i]["start"],
                "end": max(orig_words[i]["start"] + 0.08, orig_words[i]["end"]),
                "probability": 1.0
            })
        return [{"start": result_words[0]["start"], "end": result_words[-1]["end"], "text": new_text, "words": result_words}]

    orig_tokens = [w["word"].strip().lower().strip(".,!?:;\"'()[]") for w in orig_words]
    new_tokens = [nw.strip().lower().strip(".,!?:;\"'()[]") for nw in new_words_raw]

    matcher = difflib.SequenceMatcher(None, orig_tokens, new_tokens)
    result_words = [None] * len(new_words_raw)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for o_idx, n_idx in zip(range(i1, i2), range(j1, j2)):
                result_words[n_idx] = {
                    "word": new_words_raw[n_idx],
                    "start": orig_words[o_idx]["start"],
                    "end": max(orig_words[o_idx]["start"] + 0.08, orig_words[o_idx]["end"]),
                    "probability": 1.0
                }

    first_matched = next((idx for idx, w in enumerate(result_words) if w is not None), None)
    if first_matched is not None and first_matched > 0:
        end_t = result_words[first_matched]["start"]
        start_t = max(0.0, end_t - (first_matched * 0.4))
        step = (end_t - start_t) / first_matched
        for k in range(first_matched):
            result_words[k] = {
                "word": new_words_raw[k],
                "start": round(start_t + k * step, 2),
                "end": round(start_t + (k + 1) * step, 2),
                "probability": 1.0
            }

    for k in range(len(result_words)):
        if result_words[k] is None:
            prev_idx = k - 1
            while prev_idx >= 0 and result_words[prev_idx] is None:
                prev_idx -= 1
            next_idx = k + 1
            while next_idx < len(result_words) and result_words[next_idx] is None:
                next_idx += 1

            start_t = result_words[prev_idx]["end"] if prev_idx >= 0 else 0.0
            end_t = result_words[next_idx]["start"] if next_idx < len(result_words) else (start_t + 2.0)
            if end_t <= start_t:
                end_t = start_t + 0.45 * (next_idx - prev_idx)

            gap_count = next_idx - (prev_idx + 1)
            step = (end_t - start_t) / max(1, gap_count)
            for gap_i in range(gap_count):
                cur_idx = prev_idx + 1 + gap_i
                result_words[cur_idx] = {
                    "word": new_words_raw[cur_idx],
                    "start": round(start_t + gap_i * step, 2),
                    "end": round(start_t + (gap_i + 1) * step, 2),
                    "probability": 1.0
                }

    for k in range(len(result_words)):
        if result_words[k] is None:
            prev_t = result_words[k-1]["end"] if k > 0 and result_words[k-1] else 0.0
            result_words[k] = {
                "word": new_words_raw[k],
                "start": round(prev_t, 2),
                "end": round(prev_t + 0.4, 2),
                "probability": 1.0
            }

    start_clip = result_words[0]["start"] if result_words else 0.0
    end_clip = result_words[-1]["end"] if result_words else total_duration

    return [{
        "start": start_clip,
        "end": end_clip,
        "text": new_text,
        "words": result_words
    }]

class SubtitleGenerator:
    def __init__(self):
        self.config = load_config()
        self.sub_cfg = self.config.get("video", {}).get("subtitles", {})
        self.font_name = self.sub_cfg.get("font_name", "Arial Black")
        self.font_size = self.sub_cfg.get("font_size", 24)
        self.highlight_color = self.sub_cfg.get("highlight_color", "&H0000FFFF") # Gelb
        self.primary_color = self.sub_cfg.get("primary_color", "&H00FFFFFF")     # Weiß
        self.outline_color = self.sub_cfg.get("outline_color", "&H00000000")     # Schwarz
        self.outline_width = self.sub_cfg.get("outline_width", 3)
        self.max_words = self.sub_cfg.get("max_words_per_segment", 3)

    def generate_ass(self, segments: List[Dict[str, Any]], output_ass_path: Path, position: str = "bottom", style_preset: str = "yellow"):
        """
        Erstellt eine .ass Untertiteldatei im viralen Karaoke-Highlight-Stil.
        Zeigt immer nur 1-3 Wörter und hebt das aktuell gesprochene Wort farblich hervor.
        position: 'bottom' (unten), 'center' (mitte), 'top' (oben)
        style_preset: 'yellow' (MrBeast Gelb), 'cyan' (Cyber Cyan), 'neon' (Neon-Grün), 'white' (Clean Minimal)
        """
        # Phase 6: Farb-Presets
        color_presets = {
            "yellow": ("&H0000FFFF", "&H00FFFFFF"), # Highlight: Gelb, Normal: Weiß
            "cyan":   ("&H00FFFF00", "&H00FFFFFF"), # Highlight: Cyan, Normal: Weiß
            "neon":   ("&H0000FF00", "&H00FFFFFF"), # Highlight: Neon-Grün, Normal: Weiß
            "white":  ("&H00FFFFFF", "&H00CCCCCC"), # Highlight: Reinweiß, Normal: Hellgrau
        }
        hl_color, prim_color = color_presets.get(style_preset.lower(), (self.highlight_color, self.primary_color))

        # Alle Wörter chronologisch sammeln
        all_words = []
        for seg in segments:
            for w in seg.get("words", []):
                if w["word"].strip():
                    all_words.append(w)

        if not all_words:
            for seg in segments:
                all_words.append({
                    "word": seg["text"],
                    "start": seg["start"],
                    "end": seg["end"]
                })

        # Vertikaler Abstand (MarginV von unten gezählt bei Alignment 2)
        margin_v_map = {
            "bottom": 380,   # Unten (über den Shorts UI Buttons)
            "center": 820,   # Mitte / Unteres Drittel
            "top": 1450      # Oben
        }
        margin_v = margin_v_map.get(position.lower(), 380)

        # Sicherstellen, dass ein robuster Windows-Font verwendet wird
        font = "Arial Black" if self.font_name in ["Montserrat-Black", "TheBoldFont"] else self.font_name

        # ASS Header
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{self.font_size * 2.8},{prim_color},&H000000FF,{self.outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,{self.outline_width * 2},2,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []

        # Chunks von maximal self.max_words bilden
        for i in range(0, len(all_words), self.max_words):
            chunk = all_words[i:i + self.max_words]
            if not chunk:
                continue

            # Für jedes Wort im Chunk einen Eintrag erzeugen, in dem das aktive Wort hervorgehoben ist
            for active_idx, target_word in enumerate(chunk):
                start_t = format_ass_time(target_word["start"])
                end_t = format_ass_time(target_word["end"])

                # Zeile zusammenbauen mit Farbtag für das aktive Wort
                line_parts = []
                for idx, w in enumerate(chunk):
                    text = w["word"].upper()
                    if idx == active_idx:
                        # Aktives Wort in Highlight-Farbe
                        line_parts.append(f"{{\\c{hl_color}\\b1}}{text}{{\\r}}")
                    else:
                        # Andere Wörter normal
                        line_parts.append(f"{{\\c{prim_color}}}{text}")

                display_line = " ".join(line_parts)
                events.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{display_line}")

        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events) + "\n")

        return output_ass_path
