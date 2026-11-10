# 🎬 Clip-Farming Autopilot (Twitch -> 9:16 Shorts)

Eine vollautomatische, portable End-to-End-Pipeline, die beliebig viele Twitch-Streamer überwacht, virale Clips abfarmt, daraus per GPU (RTX NVENC) vertikale 9:16 Shorts mit animierten Karaoke-Untertiteln schneidet und diese selbstständig auf YouTube Shorts & TikTok veröffentlicht.

---

## 🚀 Schnellstart (1-Klick)

1. **Einrichten (einmalig):**
   * Doppelklick auf `setup.bat` (installiert alle Abhängigkeiten in die isolierte `.venv`).
2. **Mission Control & Editor (Web Dashboard):**
   * Doppelklick auf `dashboard.bat` (oder `edit.bat`): Öffnet automatisch das moderne Web-Dashboard im Browser unter `http://localhost:5000`.
3. **24/7 Autopilot im Hintergrund:**
   * Eingabeaufforderung öffnen: `run.bat --daemon` (prüft alle 15 Minuten)

---

## 🖥️ Mission Control Web-Dashboard

Mit einem Klick auf **`dashboard.bat`** hast du die volle Kontrolle:
* 🟢 **Live-Status:** Sieht in Echtzeit, was der Bot gerade tut (*„Scanne Twitch“*, *„Transkribiere mit Whisper auf CUDA“*, *„Rendere 9:16 Short auf RTX 4070“*, *„Standby“*).
* 📥 **Warteschlange (Queue):** Zeigt alle neu gefundenen Clips, View-Counts und Streamer.
* 🎬 **Studio & Editor:** 
  * Videos direkt im 9:16 Player ansehen.
  * **TikTok-Header-Sticker bearbeiten** (*„Gstastys ki hittet double mace“*).
  * Titel anpassen & mit **„⚡ Speichern & Neu Rendern“** in 2–3 Sekunden mit der RTX 4070 aktualisieren.
* 🚀 **Veröffentlicht:** Übersicht aller online gestellten Videos mit Direktlinks.
* ⚡ **Sofort-Start-Button:** Starte mit einem Klick im Browser einen neuen Durchlauf.

---

## ⚙️ Konfiguration (`config/config.yaml`)

Alle Einstellungen sind zentral und portabel in `config/config.yaml` steuerbar:

### 1. Streamer hinzufügen
```yaml
streamers:
  - name: "montanablack88"
    platform: "twitch"
    enabled: true
    min_clip_views: 50        # Mindestanzahl an Views
    max_clips_per_run: 3      # Maximale Clips pro Durchlauf
    layout: "split_cam_top"   # "split_cam_top" oder "blur_stack"
    
  - name: "eliasn97"
    platform: "twitch"
    enabled: true
    min_clip_views: 75
    max_clips_per_run: 2
```

### 2. KI-Untertitel & Rendering
* **Hardware-Beschleunigung:** Nutzt automatisch NVIDIA RTX NVENC (`use_nvenc: true`).
* **Untertitel-Stil:** Alex-Hormozi / MrBeast-Stil (gelbe Wort-Highlights, fett, animiert, 1–3 Wörter pro Chunk).
* **Audio-Normalisierung:** `audio_normalize: true` (gleicht Lautstärkeunterschiede automatisch an EBU R128 an).

### 3. YouTube Shorts & TikTok Upload
* In `config/config.yaml` kannst du unter `publishing:`
  * `youtube.enabled: true` setzen.
  * Leg deine Google Cloud `client_secrets.json` als `config/youtube_secrets.json` ab.
  * Beim ersten Start öffnet sich 1x der Browser zum Bestätigen – danach speichert das Tool das Token in `data/youtube_token.json` und läuft für immer autark!

---

## 📁 Ordnerstruktur (100 % portabel)

```text
Clip-Farming/
├── .venv/                  # Isolierte Python-Umgebung
├── config/
│   └── config.yaml         # Zentrale Einstellungen & Streamer-Liste
├── data/
│   └── pipeline.db         # SQLite-Datenbank (Deduplizierung & Status)
├── downloads/
│   └── raw/                # Zwischengespeicherte Clips (werden nach Render bereinigt)
├── output/
│   ├── shorts/             # Fertige 9:16 MP4-Videos (Upload-fertig)
│   └── metadata/           # Generierte Titel, Beschreibungen & Pinned Comments
├── src/
│   ├── config.py           # Portabler Pfad-Manager
│   ├── database.py         # SQLite Speicher & Deduplizierung
│   ├── harvesters/         # Twitch Clip & Chat Slicer
│   ├── video/              # faster-whisper, Face-Tracking & FFmpeg NVENC
│   ├── meta/               # LLM Copywriter (Gemini / OpenAI / Fallback)
│   └── uploaders/          # YouTube Shorts & TikTok Uploader
├── main.py                 # CLI & Steuerungszentrale
├── run.bat                 # 1-Klick Starter
├── setup.bat               # 1-Klick Installer
└── requirements.txt
```

---

## 🛠️ CLI-Befehle

* `python main.py` -> Führt einen einzelnen Prüf- und Schnittdurchlauf durch.
* `python main.py --daemon` -> Startet den permanenten 24/7 Hintergrund-Dienst.
* `python main.py --daemon --interval 30` -> Prüft alle 30 Minuten.
* `python main.py --status` -> Zeigt Statistiken über verarbeitete Clips und Streamer an.
* `python main.py --harvest-only` -> Lädt nur neue Clips herunter, ohne zu rendern.
