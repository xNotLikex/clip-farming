# 🎬 Clip-Farming Studio & Autopilot (Twitch → 9:16 Shorts)

Eine vollautomatische Windows-Desktop-App (**Tauri v2 + Rust** & **Python/Flask-Backend**) zum Finden, Zuschneiden, Untertiteln und Veröffentlichen vertikaler 9:16 Kurzvideos aus Twitch-Clips für **YouTube Shorts** und **TikTok**.

---

## ✨ Highlights & Funktionen

### 🖥️ Desktop-App & Web-Dashboard
Die Anwendung kombiniert eine native Windows-Oberfläche (`clip-farming.exe`) mit einem lokalen Studio-Backend (`http://127.0.0.1:5000`) und bietet einen Live-Status inklusive Fortschrittsanzeige für Harvesting, Transkription und Rendering:

1. **📥 Warteschlange (`Warteschlange`):**
   * Listet automatisch geerntete Twitch-Clips sortiert nach Views auf (inkl. Rohvideo-Vorschau).
   * Einzelübernahme oder Massenimport (*„Alle ins Studio übernehmen“*).
   * Aufräumfunktion für alte Rohclips (*„Gestern & älter löschen“*) sowie dauerhaftes Löschen/Ignorieren (`status = 'deleted'`).

2. **🎬 Studio & Freigabe (`Studio & Freigabe`):**
   * **9:16 Video-Vorschau & HQ Download:** Direktes Abspielen gerenderter Shorts im Studio sowie Download/Export in voller Qualität.
   * **Manuelle Twitch-Clip-Suche:** Suche nach beliebigen Twitch-Streamern mit wählbarem Zeitfenster (**24 Stunden**, **7 Tage**, **30 Tage**, **All Time**) und direktem Import in die Warteschlange oder ins Studio.
   * **Clip-Editor pro Karte:**
     * **Sprechblasen-Hook:** TikTok/Shorts-Header-Sticker (`sticker_text`).
     * **Titel & Untertiteltext:** Bearbeitbares Transkript (`transcript`), das beim **„Speichern & Neu Rendern“** direkt neu in die Video-Untertitel ausgerichtet wird.
     * **Untertitel-Platzierung:** `bottom` (Standard), `center`, `top` oder `none`.
     * **Layout-Modi:**
       * `auto` – KI erkennt Facecam automatisch (Split-Cam oder Blur-Stack).
       * `custom` – Benutzerdefinierte Schnittrahmen aus dem **visuellen Crop-Editor**.
       * `single_916` – Reines 9:16 Vollbild (IRL / Fullscreen).
       * `split_cam_top` – Facecam oben, Gameplay unten.
       * `blur_stack` – 16:9-Clip mittig auf unscharfem Hintergrund.
     * **3D-Mesh-Cam-Filter (20 Effekte):** Facecam Fun-Warps wie Pyramide, Trichter-Kopf, Diamant, Voxel-Cube, Gigachad, Megamind/Alien, Hamsterbacken, Pinocchio, Glubschaugen, Schrumpf-Gesicht, Riesenmund, Sanduhr, Glaskugel-Bulge, Vortex-Wirbel, Wackelpudding u. v. m.
   * **Streamer-Filter-Pills**, Status-Markierung (*„Veröffentlicht?“*) und **Löschen & Ignorieren** (entfernt auch aktive Streams & die fertige `.mp4`).

3. **🗓️ Veröffentlichungs-Planer (`Planer`):**
   * Drip-Feed-Zeitplanung (`Zeitplan`) für fertige Shorts im konfigurierbaren Abstand oder sofortige Veröffentlichung (`Sofort posten`).

4. **🔗 Konten (`Konten`):**
   * **YouTube Shorts:** OAuth2-Anbindung über `config/youtube_secrets.json` (Token wird in `data/youtube_token.json` abgelegt).
   * **TikTok:** Session-basierte Anbindung (`data/tiktok_session.json`).

5. **👥 Streamer-Verwaltung (`Streamer`):**
   * Überwachte Twitch-Kanäle hinzufügen, aktivieren/deaktivieren, Mindest-Views (`min_clip_views`), Clip-Limit (`max_clips_per_run`), Standard-Layout und gespeicherte Crop-Bereiche pro Streamer verwalten.
   * Beispielclip direkt laden, um Schnittrahmen vorab einzustellen.

6. **⚙️ Autopilot & Hardware-Einstellungen (`Einstellungen`):**
   * Konfigurierbares Prüf-Intervall (z. B. 15 / 30 / 60 / 120 Min), Standard-Zeitfenster, intelligenter Wochen-Fallback und optionales vollautomatisches Rendering.
   * Automatische GPU-Erkennung & Live-Encoder-Test (`src/video/gpu.py`):
     * **NVIDIA NVENC** (`h264_nvenc`)
     * **AMD AMF** (`h264_amf`)
     * **Intel QuickSync** (`h264_qsv`)
     * **Windows Media Foundation** (`h264_mf`)
     * **CPU Software Fallback** (`libx264`)
   * Auswahl des `faster-whisper` KI-Modells für die Transkription.

---

## 🚀 Installation & Start

### Variante A: Windows-Installer (Empfohlen)
1. Die aktuelle `Clip-Farming-Installer.exe` von den [GitHub Releases](https://github.com/xNotLikex/clip-farming/releases) herunterladen.
2. Installer ausführen (vollständig autark – enthält Desktop-Binary, eingebettete Python-Runtime sowie `ffmpeg.exe` & `ffprobe.exe`).
3. **Clip Farming Studio** starten.

### Variante B: Direkt aus dem Repository (Entwicklung / Portabel)
**Voraussetzungen:** Python 3.10+, FFmpeg (`bin/ffmpeg.exe`), optional Rust/Cargo für Tauri-Builds.

1. **Umgebung einrichten (einmalig):**
   ```bat
   setup.bat
   ```
   *(Installiert alle Abhängigkeiten aus `requirements.txt` in `.venv/`.)*
2. **Desktop-App starten:**
   ```bat
   start-desktop.bat
   ```
   *(Oder direkt `clip-farming.exe` – der integrierte Setup-Wizard prüft die Umgebung und öffnet anschließend das Studio.)*
3. **Alternativ nur das Web-Dashboard im Browser:**
   ```bat
   dashboard.bat
   ```
   *(Startet Flask unter `http://127.0.0.1:5000`.)*
4. **Headless / 24/7 Autopilot per Konsole:**
   ```bat
   run.bat --daemon
   ```

---

## ⚙️ Konfiguration (`config/config.yaml`)

Zentrale Einstellungen liegen in `config/config.yaml` (oder lassen sich direkt im Studio unter **Einstellungen** und **Streamer** anpassen):

```yaml
streamers:
  - name: "eliasn97"
    platform: "twitch"
    enabled: true
    min_clip_views: 50        # Mindestanzahl an Views
    max_clips_per_run: 3      # Maximale Clips pro Durchlauf
    layout: "auto"            # "auto", "custom", "single_916", "split_cam_top", "blur_stack"

twitch:
  client_id: ""
  client_secret: ""
  time_filter: "LAST_DAY"
  hours_back: 12

autopilot:
  enabled: true
  interval_minutes: 30
  time_filter: "LAST_DAY"
  fallback_to_week: false
  auto_render: false

video:
  hardware_encoder: "nvenc"   # "auto", "nvenc", "amf", "qsv", "mf", "cpu"
  use_nvenc: true
  whisper_model: "large-v3"   # z. B. "small", "medium", "large-v3"
  device: "cuda"
  audio_normalize: true       # Dynamische Kompression + EBU R128 Loudness
  subtitles:
    enabled: true
    font_name: "Arial Black"
    font_size: 24
    max_words_per_segment: 3

ai_copywriter:
  provider: "gemini"          # "gemini", "openai" oder lokaler Fallback
  model: "gemini-2.5-flash"
  api_key: ""
  language: "de"

publishing:
  drip_feed_hours: 3
  youtube:
    enabled: true
    privacy_status: "private"
    client_secrets_file: "config/youtube_secrets.json"
  tiktok:
    enabled: true
    upload_mode: "public"
    session_id: ""

storage:
  auto_cleanup_raw: true
  database_path: "data/pipeline.db"
```

### YouTube & TikTok einrichten
* **YouTube Shorts:** Google Cloud OAuth2 `client_secrets.json` unter `config/youtube_secrets.json` ablegen und im Tab **Konten** verbinden. Das Refresh-Token wird dauerhaft in `data/youtube_token.json` gespeichert.
* **TikTok:** Im Tab **Konten** anmelden bzw. Session in `data/tiktok_session.json` hinterlegen.

---

## 🛠️ CLI-Befehle (`main.py`)

```bash
python main.py                        # Einzelnen Harvesting- & Render-Durchlauf starten
python main.py --daemon               # 24/7 Autopilot im Hintergrund starten
python main.py --daemon --interval 30 # Prüf-Intervall auf 30 Minuten setzen
python main.py --status               # Pipeline-Statistiken nach Status & Streamer anzeigen
python main.py --harvest-only         # Nur neue Clips laden, ohne zu rendern
python main.py --reset-failed         # Fehlgeschlagene Clips wieder auf 'harvested' setzen
```

---

## 🏗️ Architektur & Ordnerstruktur

```text
Clip-Farming/
├── src-tauri/                  # Native Tauri v2 Desktop-App (Rust)
│   ├── src/
│   │   ├── main.rs             # Einstiegspunkt & Cache-/Backend-Bootstrap
│   │   ├── lib.rs              # Tauri Builder & Command-Handler
│   │   ├── commands.rs         # Desktop-Kommandos (DB, GPU, Ordner, Proxy)
│   │   ├── setup.rs            # Setup-Wizard & Python-Studio-Launcher
│   │   ├── db.rs / models.rs   # SQLite Dashboard-Queries
│   │   ├── gpu.rs / twitch.rs  # Hardware- & Twitch-Helfer
│   ├── tauri.conf.json
│   └── Cargo.toml
├── ui/                         # Frontend SPA (HTML/Tailwind + Vanilla JS)
│   ├── index.html              # Desktop-Setup & Studio-Einstieg
│   ├── setup.html
│   └── app.js                  # Reaktive Dashboard-, Studio-, Crop- & Such-Logik
├── src/                        # Python Pipeline & Flask Web-Studio
│   ├── web_studio.py           # REST API, Video-Streaming (HTTP Range) & UI-Server
│   ├── config.py               # Portabler Pfad- & YAML-Config-Manager
│   ├── database.py             # SQLite Deduplizierung & Clip-Lifecycle
│   ├── scheduler.py            # Autopilot & Publishing-Zeitplaner
│   ├── state.py                # Status- & Fortschritts-Manager + Crash-Recovery
│   ├── updater.py              # GitHub Release Auto-Update-Prüfung
│   ├── harvesters/             # Twitch Clip Downloader (yt-dlp / GraphQL / Helix)
│   ├── video/
│   │   ├── layout.py           # 9:16 Compositor & FFmpeg-Pipeline (+faststart)
│   │   ├── subtitles.py        # Karaoke ASS-Untertitel & Text-Alignment
│   │   ├── transcriber.py      # faster-whisper Transkription
│   │   ├── filters.py          # 3D-Mesh-Deformation Facecam-Filter
│   │   ├── sticker.py          # Sprechblasen-Hook Overlay
│   │   └── gpu.py              # GPU-Erkennung & Encoder-Auswahl
│   ├── meta/                   # KI-Titel-, Beschreibungs- & Tag-Generator
│   └── uploaders/              # YouTube Shorts & TikTok Uploader
├── scripts/                    # Installer- & Build-Skripte (Inno Setup + Py-Runtime)
├── config/                     # config.yaml & OAuth Secrets
├── data/                       # pipeline.db, Thumbnails & Account-Sessions
├── downloads/raw/              # Temporäre Rohclips & Transkripte
├── output/
│   ├── shorts/                 # Render-fertige 9:16 MP4-Dateien
│   └── metadata/               # Clip-Metadaten (Crop, Filter, Titel, Hook)
├── main.py                     # CLI-Einstiegspunkt
├── requirements.txt            # Python-Abhängigkeiten
└── setup.bat / run.bat / dashboard.bat / start-desktop.bat
```

---

## 📦 Desktop-Binary & Installer selbst bauen

```bash
# 1. Tauri Release-Binary bauen
cargo build --release --manifest-path src-tauri/Cargo.toml
copy src-tauri\target\release\clip-farming.exe clip-farming.exe

# 2. Autarken Windows-Installer (Inno Setup) erzeugen
.\.venv\Scripts\python.exe scripts\build_installer.py
```

Der fertige Installer landet anschließend unter `dist/Clip-Farming-Installer.exe`.
