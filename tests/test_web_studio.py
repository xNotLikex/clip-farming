import threading

import src.web_studio as ws
from src import database


def test_import_web_studio_starts_no_background_workers():
    thread_names = {t.name for t in threading.enumerate()}
    assert "auto_publisher_worker" not in thread_names
    assert "autopilot_background_worker" not in thread_names


def test_web_studio_smoke_routes(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ws.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    app = ws.create_app()
    client = app.test_client()

    resp_ver = client.get("/api/version")
    assert resp_ver.status_code == 200
    assert "version" in resp_ver.get_json()

    resp_status = client.get("/api/status")
    assert resp_status.status_code == 200
    assert "is_running" in resp_status.get_json()

    resp_settings = client.get("/api/settings")
    assert resp_settings.status_code == 200

    resp_js = client.get("/app.js")
    assert resp_js.status_code == 200
    assert b"updateStatus" in resp_js.data

    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert b"<!DOCTYPE html>" in resp_root.data
    assert b"tab-accounts" not in resp_root.data
    assert b"tab-planner" not in resp_root.data

    assert client.get("/api/accounts/status").status_code == 404
