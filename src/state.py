import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from src.config import DATA_DIR

STATE_FILE = DATA_DIR / "pipeline_state.json"
_STATE_LOCK = threading.RLock()

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
    "logs": []
}

class StatusManager:
    def __init__(self):
        self._ensure_file()
        # Beim Backend-Start sicherstellen, dass keine Zombie-Locks aus vorherigen Abstürzen/Beenden aktiv sind
        with _STATE_LOCK:
            try:
                state = self.get_state()
                if state.get("is_running", False):
                    state["is_running"] = False
                    state["status"] = "idle"
                    state["current_task"] = "Bereit zum Start"
                    state["progress_percent"] = 0
                    state["eta_seconds"] = None
                    state["speed"] = None
                    with open(STATE_FILE, "w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def _ensure_file(self):
        with _STATE_LOCK:
            if not STATE_FILE.exists():
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_STATE, f, indent=2, ensure_ascii=False)

    def get_state(self) -> Dict[str, Any]:
        self._ensure_file()
        with _STATE_LOCK:
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return DEFAULT_STATE.copy()

    def update(self, **kwargs):
        with _STATE_LOCK:
            state = self.get_state()
            for k, v in kwargs.items():
                state[k] = v
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def set_task(self, status: str, task_desc: str, clip_title: str = None, streamer: str = None):
        with _STATE_LOCK:
            state = self.get_state()
            state["status"] = status
            state["current_task"] = task_desc
            # is_running darf bei idle oder error nicht True sein; alle aktiven Phasen sind True
            state["is_running"] = status not in ("idle", "error")
            if clip_title:
                state["current_clip"] = clip_title
            if streamer:
                state["streamer"] = streamer
            
            # Log hinzufügen
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] [{status.upper()}] {task_desc}"
            logs = state.get("logs", [])
            logs.append(entry)
            if len(logs) > 60:
                logs = logs[-60:]
            state["logs"] = logs

            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def set_progress(self, percent: int, eta_seconds: int = None, speed: str = None, phase: str = None, clip_id: str = None):
        """Aktualisiert Render-Fortschritt in Prozent und geschätzte Restdauer."""
        with _STATE_LOCK:
            state = self.get_state()
            state["progress_percent"] = max(0, min(100, int(percent)))
            if eta_seconds is not None:
                state["eta_seconds"] = max(0, int(eta_seconds))
            if speed is not None:
                state["speed"] = speed
            if phase is not None:
                state["render_phase"] = phase
            if clip_id is not None:
                state["active_clip_id"] = clip_id
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def reset_progress(self):
        with _STATE_LOCK:
            state = self.get_state()
            state["progress_percent"] = 0
            state["eta_seconds"] = None
            state["speed"] = None
            state["render_phase"] = None
            state["active_clip_id"] = None
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def log(self, message: str):
        with _STATE_LOCK:
            state = self.get_state()
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] {message}"
            logs = state.get("logs", [])
            logs.append(entry)
            if len(logs) > 60:
                logs = logs[-60:]
            state["logs"] = logs
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

status_manager = StatusManager()
