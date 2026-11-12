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


def test_get_processed_ids_empty_and_chunked(tmp_path, monkeypatch):
    db_file = tmp_path / "test_batch.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    assert database.get_processed_ids([]) == set()

    database.save_clip(
        {"clip_id": "known-0", "streamer": "s", "title": "t", "url": "https://twitch.tv/0"}
    )
    database.save_clip(
        {"clip_id": "known-950", "streamer": "s", "title": "t", "url": "https://twitch.tv/950"}
    )

    query_ids = [f"unknown-{i}" for i in range(950)] + ["known-0", "known-950", "known-0"]
    assert database.get_processed_ids(query_ids) == {"known-0", "known-950"}


def test_init_db_sets_user_version_and_upgrades_legacy_v0(tmp_path, monkeypatch):
    db_file = tmp_path / "test_migrate.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)

    # Simuliere Legacy-v0-Datenbank ohne scheduled_publish_at / is_manually_published
    with database.get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE clips (
                clip_id TEXT PRIMARY KEY,
                streamer TEXT NOT NULL,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                view_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'harvested'
            )
            """
        )

    database.init_db()
    database.init_db()  # Idempotent

    with database.get_db_connection() as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = {row[1] for row in conn.execute("PRAGMA table_info(clips)").fetchall()}
        assert user_version == 1
        assert "scheduled_publish_at" in cols
        assert "is_manually_published" in cols


