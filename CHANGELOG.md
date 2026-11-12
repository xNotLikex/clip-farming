# Changelog

## [0.5.13] - 2026-11-12

### Entfernt
- **Upload & Account-Verknüpfung (YouTube / TikTok):** `src/uploaders/` (`youtube.py`, `tiktok.py`, `account_manager.py`, `browser_login.py`), `auto_publisher_worker`, Tabs *Planer* und *Konten* sowie zugehörige API-Routen und Upload-Abhängigkeiten dauerhaft entfernt. Fokus liegt auf Clip-Grabbing, Bearbeitung im Studio und HQ-Export.

### Behoben (P0)
- **Secrets-Hygiene (`P0-3`):** `config/config.yaml` aus Git entfernt, `.gitignore` abgesichert, automatisches Bootstrap von `config/config.example.yaml` beim Start.
- **TikTok-Stub (`P0-1`):** Gefakten TikTok-Erfolg entfernt (`upload_short` gibt `None` zurück), Clips werden ohne echte ID nicht als `published` markiert.
- **Twitch `time_filter` (`P0-2`):** `LAST_WEEK` (168h), `LAST_MONTH` (720h), `ALL_TIME` und `TRENDING` werden sauber an `fetch_clips_helix` und den GQL-Fallback durchgereicht.
- **Status-Datei (`P0-4`):** Atomares Schreiben (`os.replace`), `copy.deepcopy(DEFAULT_STATE)` und Warn-Logging bei JSON-/IO-Fehlern.

### Performance & Stabilität (P1)
- **State-Caching (`P1-1`):** `StatusManager` hält Zustand im Speicher und schreibt Fortschritt/Logs gedrosselt (`1.5s`).
- **SQLite (`P1-2`, `P1-3`):** `@contextmanager` mit `WAL`, `busy_timeout=5000`, `foreign_keys=ON`, garantiertem `close()` sowie Batch-Duplikatprüfung (`get_processed_ids`).
- **Config (`P1-4`):** `load_config()` mit thread-sicherem `mtime`-Cache und Env-Overrides (`TWITCH_CLIENT_SECRET`, `GEMINI_API_KEY`, etc.).
- **FFmpeg & Video (`P1-5`..`P1-8`):** Einzelner `ffprobe`-JSON-Aufruf (`probe_video`), `stdin`-Pipe für 3D-Cam-Filter, `proc.wait()` statt `sleep`, Windows-Pfad-Escaping (`escape_ffmpeg_filter_path`).
- **Harvester (`P1-9`):** Gemeinsame `requests.Session` mit `Retry`, einheitliche GQL-`time_filter`-Allowlist, parallele Downloads (`ThreadPoolExecutor`).

### Architektur, Tests & CI (P2 / P3)
- **Layout & Facecam (`P2-1`, `P2-2`):** Reine `build_filter_graph()`-Funktion, vereinheitlichte Rechteck-Normalisierung, Snapshot-Tests und Metadaten-Cache für `detect_facecam_overlay`.
- **Web-Studio & DB (`P2-3`, `P2-6`):** HTML-Template ausgelagert (`src/web/templates.py`), `create_app()` + `start_workers()` (kein Thread-Start beim Import), `PRAGMA user_version`-Migrationen.
- **Logging & Frontend (`P2-4`, `P2-7`):** Zentrales `RotatingFileHandler`-Logging (`data/logs/clip_farming.log`) und `visibilityState`-gesteuertes Status-Polling.
- **Tests & CI (`P3-1`..`P3-4`):** `pyproject.toml`, `requirements-dev.txt`, `pytest`-Testsuite, GitHub Actions CI (`windows-latest`: `ruff`, `pytest`, `cargo check`) und aktualisierte Doku.
