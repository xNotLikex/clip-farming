import copy
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

STATE_FILE = DATA_DIR / "pipeline_state.json"
_STATE_LOCK = threading.RLock()
PERSIST_INTERVAL_SECONDS = 1.5

DEFAULT_STATE = {
    "status": "idle",
    "current_task": "Bereit zum Start",
    "current_clip": None,
    "active_clip_id": None,
    "streamer": None,
    "progress_percent": 0,
    "eta_seconds": None,
    "speed": None,
    "render_phase": None,
    "is_running": False,
    "last_cycle_time": None,
    "next_cycle_time": None,
    "logs": [],
}


def _atomic_write_json(target_path, data: dict[str, Any]) -> None:
    """Schreibt JSON atomar über eine temporäre Datei im selben Ordner und os.replace."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = tf.name
            json.dump(data, tf, indent=2, ensure_ascii=False)
            tf.flush()
        os.replace(tmp_path, target_path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class StatusManager:
    def __init__(self, persist_interval: float = PERSIST_INTERVAL_SECONDS):
        self._persist_interval = persist_interval
        self._last_persist_at = 0.0
        self._dirty = False
        with _STATE_LOCK:
            self._state = self._load_from_disk()
            # Beim Backend-Start sicherstellen, dass keine Zombie-Locks aus vorherigen Abstürzen/Beenden aktiv sind
            if self._state.get("is_running", False):
                self._state["is_running"] = False
                self._state["status"] = "idle"
                self._state["current_task"] = "Bereit zum Start"
                self._state["progress_percent"] = 0
                self._state["eta_seconds"] = None
                self._state["speed"] = None
                self._persist(force=True, context="init")

    def _load_from_disk(self) -> dict[str, Any]:
        if not STATE_FILE.exists():
            default_state = copy.deepcopy(DEFAULT_STATE)
            try:
                _atomic_write_json(STATE_FILE, default_state)
            except (OSError, TypeError, ValueError) as e:
                logger.warning("Fehler beim Initialisieren von pipeline_state.json: %s", e)
            return default_state
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise TypeError("pipeline_state.json enthält kein JSON-Objekt")
            return loaded
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Defekte pipeline_state.json erkannt, verwende Default-State: %s", e)
            return copy.deepcopy(DEFAULT_STATE)

    def _persist(self, *, force: bool = False, context: str = "state") -> None:
        now = time.monotonic()
        if not force and (now - self._last_persist_at) < self._persist_interval:
            self._dirty = True
            return
        try:
            _atomic_write_json(STATE_FILE, self._state)
            self._last_persist_at = now
            self._dirty = False
        except (OSError, TypeError, ValueError) as e:
            logger.warning("Fehler beim Schreiben von pipeline_state.json in %s(): %s", context, e)

    def flush(self) -> None:
        with _STATE_LOCK:
            if self._dirty:
                self._persist(force=True, context="flush")

    def get_state(self) -> dict[str, Any]:
        with _STATE_LOCK:
            return copy.deepcopy(self._state)

    def update(self, **kwargs):
        with _STATE_LOCK:
            for k, v in kwargs.items():
                self._state[k] = v
            self._persist(force=True, context="update")

    def set_task(self, status: str, task_desc: str, clip_title: str | None = None, streamer: str | None = None):
        with _STATE_LOCK:
            prev_status = self._state.get("status")
            self._state["status"] = status
            self._state["current_task"] = task_desc
            # is_running darf bei idle oder error nicht True sein; alle aktiven Phasen sind True
            self._state["is_running"] = status not in ("idle", "error")
            if clip_title:
                self._state["current_clip"] = clip_title
            if streamer:
                self._state["streamer"] = streamer

            # Log hinzufügen
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] [{status.upper()}] {task_desc}"
            logs = list(self._state.get("logs", []))
            logs.append(entry)
            if len(logs) > 60:
                logs = logs[-60:]
            self._state["logs"] = logs
            # Bei Statuswechsel (insbesondere idle/error) sofort persistieren
            force_write = (status != prev_status) or (status in ("idle", "error"))
            self._persist(force=force_write, context="set_task")

    def set_progress(self, percent: int, eta_seconds: int | None = None, speed: str | None = None, phase: str | None = None, clip_id: str | None = None):
        """Aktualisiert Render-Fortschritt in Prozent und geschätzte Restdauer."""
        with _STATE_LOCK:
            self._state["progress_percent"] = max(0, min(100, int(percent)))
            if eta_seconds is not None:
                self._state["eta_seconds"] = max(0, int(eta_seconds))
            if speed is not None:
                self._state["speed"] = speed
            if phase is not None:
                self._state["render_phase"] = phase
            if clip_id is not None:
                self._state["active_clip_id"] = clip_id
            self._persist(force=False, context="set_progress")

    def reset_progress(self):
        with _STATE_LOCK:
            self._state["progress_percent"] = 0
            self._state["eta_seconds"] = None
            self._state["speed"] = None
            self._state["render_phase"] = None
            self._state["active_clip_id"] = None
            self._persist(force=True, context="reset_progress")

    def log(self, message: str):
        with _STATE_LOCK:
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] {message}"
            logs = list(self._state.get("logs", []))
            logs.append(entry)
            if len(logs) > 60:
                logs = logs[-60:]
            self._state["logs"] = logs
            self._persist(force=False, context="log")

status_manager = StatusManager()
