import json
from unittest.mock import patch

import src.state as st


def test_corrupted_state_file_logs_warning_and_preserves_default_state(tmp_path, caplog):
    state_file = tmp_path / "pipeline_state.json"
    state_file.write_text('{"status": "rendering", "logs": [', encoding="utf-8")

    with patch.object(st, "STATE_FILE", state_file):
        mgr = st.StatusManager()
        with caplog.at_level("WARNING"):
            s = mgr.get_state()
        assert s["status"] == "idle"
        assert s["logs"] == []
        assert any("Defekte pipeline_state.json" in r.message for r in caplog.records)

        mgr.log("Erster Logeintrag")
        mgr.flush()
        assert st.DEFAULT_STATE["logs"] == []
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert len(persisted["logs"]) == 1


def test_progress_clamping_and_log_limit_and_zombie_lock(tmp_path):
    state_file = tmp_path / "pipeline_state.json"
    state_file.write_text(
        json.dumps({"status": "rendering", "is_running": True, "progress_percent": 50, "logs": []}),
        encoding="utf-8",
    )

    with patch.object(st, "STATE_FILE", state_file):
        mgr = st.StatusManager()
        s = mgr.get_state()
        assert s["is_running"] is False
        assert s["status"] == "idle"
        assert s["progress_percent"] == 0

        mgr.set_progress(150)
        assert mgr.get_state()["progress_percent"] == 100
        mgr.set_progress(-10)
        assert mgr.get_state()["progress_percent"] == 0

        for i in range(75):
            mgr.log(f"msg {i}")
        assert len(mgr.get_state()["logs"]) == 60


def test_throttled_disk_writes_during_rapid_progress_updates(tmp_path):
    state_file = tmp_path / "pipeline_state.json"
    with (
        patch.object(st, "STATE_FILE", state_file),
        patch.object(st, "_atomic_write_json", wraps=st._atomic_write_json) as spy_write,
    ):
        mgr = st.StatusManager(persist_interval=1.5)
        initial_writes = spy_write.call_count

        for pct in range(1, 61):
            mgr.set_progress(pct, eta_seconds=60 - pct, speed="2.5x", phase="rendering")

        assert mgr.get_state()["progress_percent"] == 60
        assert spy_write.call_count - initial_writes <= 2

        mgr.set_task("idle", "Fertig")
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted["status"] == "idle"
        assert persisted["progress_percent"] == 60
