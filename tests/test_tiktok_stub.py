from unittest.mock import patch

import src.web_studio as ws
from src.uploaders.tiktok import TikTokUploader


def test_tiktok_upload_short_never_returns_fake_id(tmp_path):
    uploader = TikTokUploader()
    uploader.enabled = True
    dummy_video = tmp_path / "short_test.mp4"
    dummy_video.write_bytes(b"video")

    with patch.object(uploader, "get_session_id", return_value="real_session_123456"):
        result = uploader.upload_short(dummy_video, "Test Caption")

    assert result is None


def test_publish_clip_now_does_not_mark_published_when_only_tiktok_enabled(tmp_path):
    clip_id = "tt_stub_clip_1"
    shorts_dir = tmp_path / "shorts"
    meta_dir = tmp_path / "meta"
    shorts_dir.mkdir()
    meta_dir.mkdir()
    (shorts_dir / f"short_{clip_id}.mp4").write_bytes(b"video")

    recorded = {}

    def fake_update_clip_status(cid, status, **kwargs):
        recorded["clip_id"] = cid
        recorded["status"] = status
        recorded.update(kwargs)

    class _DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self

        def execute(self, *args, **kwargs):
            return self

        def fetchone(self):
            return {"clip_id": clip_id, "ai_title": "Test Title", "original_title": "Orig"}

    with (
        patch.object(ws, "SHORTS_OUTPUT_DIR", shorts_dir),
        patch.object(ws, "METADATA_OUTPUT_DIR", meta_dir),
        patch.object(ws, "get_db_connection", return_value=_DummyConn()),
        patch.object(ws.yt_uploader, "is_configured", return_value=False),
        patch.object(ws.tt_uploader, "is_configured", return_value=True),
        patch.object(ws.tt_uploader, "get_session_id", return_value="session_123456789"),
        patch.object(ws, "update_clip_status", side_effect=fake_update_clip_status),
    ):
        ok = ws.publish_clip_now(clip_id)

    assert ok is False
    assert recorded["status"] != "published"
    assert recorded.get("tiktok_video_id") is None
    assert recorded.get("error_log")
