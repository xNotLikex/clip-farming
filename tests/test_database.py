import sqlite3
import threading

import pytest

from src import database


def test_get_db_connection_pragmas_and_close(tmp_path, monkeypatch):
    db_file = tmp_path / "test_pipeline.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    with database.get_db_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert busy_timeout >= 5000
        assert foreign_keys == 1

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_get_db_connection_rollback_on_error(tmp_path, monkeypatch):
    db_file = tmp_path / "test_rollback.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    database.save_clip(
        {"clip_id": "clip-1", "streamer": "tester", "title": "Init", "url": "https://twitch.tv/clip-1"}
    )

    with pytest.raises(RuntimeError), database.get_db_connection() as conn:
        conn.execute("UPDATE clips SET status = 'broken' WHERE clip_id = 'clip-1'")
        raise RuntimeError("boom")

    with database.get_db_connection() as conn:
        row = conn.execute("SELECT status FROM clips WHERE clip_id = 'clip-1'").fetchone()
        assert row["status"] == "harvested"


def test_update_clip_status_rejects_invalid_column(tmp_path, monkeypatch):
    db_file = tmp_path / "test_allowlist.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    with pytest.raises(ValueError, match="Unzulässiger Spaltenname"):
        database.update_clip_status("clip-1", "rendered", evil_col="DROP TABLE clips")


def test_concurrent_reads_and_writes(tmp_path, monkeypatch):
    db_file = tmp_path / "test_concurrent.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    errors: list[Exception] = []
    barrier = threading.Barrier(4)

    def worker(worker_id: int) -> None:
        try:
            barrier.wait(timeout=5)
            for idx in range(15):
                clip_id = f"w{worker_id}-c{idx}"
                database.save_clip(
                    {
                        "clip_id": clip_id,
                        "streamer": f"streamer_{worker_id}",
                        "title": f"Title {idx}",
                        "url": f"https://twitch.tv/{clip_id}",
                        "view_count": idx * 10,
                    }
                )
                database.update_clip_status(clip_id, "rendered", ai_title=f"AI {idx}")
                database.get_pending_clips(limit=5)
        except (sqlite3.Error, RuntimeError) as exc:  # pragma: no cover - nur bei Fehler
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors
    with database.get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        assert count == 60
