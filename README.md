# 🎬 Clip-Farming Studio (Twitch → 9:16 Shorts)

Eine **100 % portable Windows-Desktop-App in Rust (Tauri v2)** zum Finden, Zuschneiden, Untertiteln und Exportieren vertikaler 9:16-Kurzvideos aus Twitch-Clips – komplett ohne Python, ohne Installer und ohne AppData-Müll.

---

## ✨ Highlights & Funktionen

1. **📥 Clip-Eingang (`Clip-Eingang`):**
   * Listet automatisch geerntete Twitch-Clips sortiert nach Views auf (inkl. Rohvideo-Vorschau).
   * Einzelübernahme ins Studio, Massenimport oder Aufräumfunktion für alte Rohclips.

2. **🎬 Studio & Freigabe (`Studio & Freigabe`):**
   * **Originalclip & 9:16-Vorschau:** Zeigt importierte Originalclips zur direkten Bearbeitung und gerenderte 9:16-Shorts mit **HQ Download** (inkl. Speicherort-Auswahl).
   * **Clip-Editor pro Karte:**
     * Titel, Untertitel-Platzierung (`bottom`, `center`, `top`, `none`) und Layout-Modi (`auto`, `custom`, `single_916`, `split_cam_top`, `blur_stack`).
     * Visueller **Crop-Editor** für benutzerdefinierte Facecam-/Gameplay-Ausschnitte.
     * **20 Facecam-Fun-Filter** (u. a. Pyramide, Trichter-Kopf, Diamant, Voxel-Cube, Gigachad, Alien, Hamsterbacken, Pinocchio, Glubschaugen, Vortex-Wirbel, Wackelpudding).
   * **Streamer-Filter**, Status-Markierung (*„Veröffentlicht?“*) und **Löschen & Ignorieren**.

3. **🔍 Clip Explorer (`Clip Explorer`):**
   * Manuelle Suche nach beliebigen Twitch-Streamern mit wählbarem Zeitfenster (**24h**, **7 Tage**, **30 Tage**, **All-Time**).
   * Direkt-Import als Originalclip ins **Studio** (ohne erzwungene Vorab-Umwandlung) oder in den **Clip-Eingang**.

4. **👥 Streamer (`Streamer`):**
   * Überwachte Twitch-Kanäle verwalten (aktivieren/deaktivieren, Mindest-Views, Clip-Limit, Standard-Layout und gespeicherte Crop-Bereiche).

5. **⚙️ Autopilot & Hardware-Einstellungen:**
   * Konfigurierbares Prüf-Intervall, Zeitfenster, Wochen-Fallback und optionales automatisches Rendering.
   * Automatische GPU-Erkennung & Hardware-Encoder (`h264_nvenc`, `h264_amf`, `h264_qsv`, `h264_mf`, Software-Fallback `libx264`).
   * Lokale Whisper-Transkription (`whisper-cli.exe`, Modelle werden automatisch in `models/` geladen).

---

## 🚀 Starten (Portable ZIP – Empfohlen)

1. Die aktuelle **`Clip-Farming-v0.1.1-Portable-Windows-x64.zip`** unter [GitHub Releases](https://github.com/xNotLikex/clip-farming/releases) herunterladen.
2. In einen beliebigen Ordner entpacken (z. B. `D:\Clip-Farming\`).
3. **`clip-farming.exe`** starten – fertig!

> **100 % Portabel:** Alle Daten (`config/`, `data/`, `downloads/`, `output/`, `models/`, `logs/`, `data/webview2/`) werden direkt neben `clip-farming.exe` gespeichert. Es wird nichts installiert und nichts in `%APPDATA%` oder `%LOCALAPPDATA%` abgelegt.  
> **Systemvoraussetzung:** Windows 10/11 (x64) mit Microsoft Edge WebView2 Runtime (auf Windows 11 vorinstalliert).

---

## 🛠️ Aus dem Quellcode bauen (Entwicklung)

**Voraussetzungen:** Rust (Edition 2024 / `1.90+`), Node.js (nur falls `ui/tailwind.css` neu generiert wird).

```powershell
# Release-Binary bauen
cargo build --release --manifest-path src-tauri/Cargo.toml
```

Das fertige Binary liegt anschließend unter `src-tauri/target/release/clip-farming.exe`. Für den portablen Betrieb müssen `ffmpeg.exe`, `ffprobe.exe` und `whisper-cli.exe` (inkl. DLLs) im Unterordner `binaries/` neben der `.exe` liegen.

---

## 🏗️ Projektstruktur

```text
Clip-Farming/
├── src-tauri/                  # Tauri v2 Desktop-App & komplette Pipeline in Rust
│   ├── src/
│   │   ├── main.rs / lib.rs    # Einstiegspunkt, WebView2-Portable-Pfad & Tauri-Setup
│   │   ├── commands.rs         # In-Process API-Dispatcher & Tauri-Commands
│   │   ├── config.rs           # Portabler Pfad-Manager & config/config.yaml
│   │   ├── db.rs / models.rs   # SQLite-Datenbank & Dashboard-Datenmodelle
│   │   ├── twitch.rs           # Twitch GraphQL Clip-Suche & Downloader
│   │   ├── pipeline.rs         # Autopilot & Verarbeitungs-Pipeline
│   │   ├── layout.rs           # 9:16 FFmpeg-Compositor, Filter & Thumbnails
│   │   ├── whisper.rs          # Lokale whisper-cli Integration & Modell-Download
│   │   ├── subtitles.rs        # ASS-Untertitel-Generator
│   │   ├── sticker.rs          # Header-/Sprechblasen-Overlay
│   │   ├── gpu.rs              # GPU-Erkennung & Encoder-Auswahl
│   │   ├── state.rs            # Live-Status & Render-Abbruch
│   │   └── updater.rs          # GitHub Release Update-Check
│   ├── binaries/               # Sidecars (ffmpeg, ffprobe, whisper-cli + DLLs)
│   ├── tauri.conf.json
│   └── Cargo.toml
├── ui/                         # Eingebettete Frontend-SPA (HTML, Tailwind CSS, JS)
│   ├── index.html
│   ├── app.js
│   └── tailwind.css
└── .github/workflows/          # CI & Release-Workflows
```
