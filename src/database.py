import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from src.config import DATA_DIR

DB_PATH = DATA_DIR / "pipeline.db"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialisiert die SQLite-Datenbanktabellen."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Clips-Tabelle: Verhindert Duplikate und trackt den Status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clips (
                clip_id TEXT PRIMARY KEY,
                streamer TEXT NOT NULL,
                platform TEXT NOT NULL,
                original_title TEXT,
                url TEXT NOT NULL,
                view_count INTEGER DEFAULT 0,
                duration REAL DEFAULT 0.0,
                clip_created_at TEXT,
                harvested_at TEXT,
                status TEXT DEFAULT 'harvested',
                raw_path TEXT,
                rendered_path TEXT,
                ai_title TEXT,
                ai_description TEXT,
                ai_tags TEXT,
                published_at TEXT,
                scheduled_publish_at TEXT,
                is_manually_published INTEGER DEFAULT 0,
                youtube_video_id TEXT,
                tiktok_video_id TEXT,
                error_log TEXT
            )
        """)
        try:
            cursor.execute("ALTER TABLE clips ADD COLUMN scheduled_publish_at TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE clips ADD COLUMN is_manually_published INTEGER DEFAULT 0")
        except Exception:
            pass
        
        # Streamer-Tracking Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS streamer_checks (
                streamer TEXT PRIMARY KEY,
                last_checked_at TEXT,
                last_stream_id TEXT,
                last_stream_start TEXT
            )
        """)
        conn.commit()

def is_clip_already_processed(clip_id: str) -> bool:
    """Prüft, ob ein Clip bereits in der Datenbank existiert."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM clips WHERE clip_id = ?", (clip_id,))
        return cursor.fetchone() is not None

def save_clip(clip_data: Dict[str, Any]):
    """Speichert einen neu gefundenen Clip."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO clips (
                clip_id, streamer, platform, original_title, url, view_count,
                duration, clip_created_at, harvested_at, status, raw_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clip_data.get("clip_id"),
            clip_data.get("streamer"),
            clip_data.get("platform", "twitch"),
            clip_data.get("title"),
            clip_data.get("url"),
            clip_data.get("view_count", 0),
            clip_data.get("duration", 0.0),
            clip_data.get("created_at"),
            datetime.now().isoformat(),
            "harvested",
            clip_data.get("raw_path")
        ))
        conn.commit()

def update_clip_status(clip_id: str, status: str, **kwargs):
    """Aktualisiert den Status und Metadaten eines Clips."""
    # C8 Audit-Fix: Nur erlaubte Spaltennamen akzeptieren (SQL-Injection-Schutz)
    ALLOWED_COLUMNS = {
        "raw_path", "rendered_path", "ai_title", "ai_description", "ai_tags",
        "published_at", "scheduled_publish_at", "is_manually_published",
        "youtube_video_id", "tiktok_video_id", "error_log"
    }
    with get_db_connection() as conn:
        cursor = conn.cursor()
        fields = ["status = ?"]
        values = [status]
        for key, val in kwargs.items():
            if key not in ALLOWED_COLUMNS:
                raise ValueError(f"Unzulässiger Spaltenname: {key}")
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(clip_id)
        
        query = f"UPDATE clips SET {', '.join(fields)} WHERE clip_id = ?"
        cursor.execute(query, values)
        conn.commit()

def get_pending_clips(limit: int = 10) -> List[Dict[str, Any]]:
    """Gibt Clips zurück, die noch gerendert werden müssen."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clips WHERE status = 'harvested' ORDER BY view_count DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

# Initialisiere die Datenbank direkt beim Import
init_db()
