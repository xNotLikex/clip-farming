from unittest.mock import MagicMock

from src import scheduler


def test_scheduler_marks_rendered_not_published_when_only_tiktok_enabled(tmp_path, monkeypatch):
    raw_file = tmp_path / "raw_c1.mp4"
    raw_file.write_bytes(b"raw")
    rendered_file = tmp_path / "short_c1.mp4"
    rendered_file.write_bytes(b"short")
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)

    cfg = {
        "streamers": [{"name": "trymacs", "enabled": True}],
        "publishing": {
            "youtube": {"enabled": False},
            "tiktok": {"enabled": True},
        },
        "ai": {},
        "video": {},
    }
    monkeypatch.setattr(scheduler, "load_config", lambda: cfg)
    monkeypatch.setattr(scheduler, "METADATA_OUTPUT_DIR", meta_dir)
    monkeypatch.setattr(scheduler, "RAW_CLIPS_DIR", tmp_path)
    monkeypatch.setattr(
        scheduler,
        "get_pending_clips",
        lambda limit=10: [
            {
                "clip_id": "c1",
                "streamer": "trymacs",
                "original_title": "Epic Clip",
                "raw_path": str(raw_file),
            }
        ],
    )

    status_updates: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        scheduler,
        "update_clip_status",
        lambda clip_id, status, **kw: status_updates.append((clip_id, status, kw)),
    )

    orch = scheduler.PipelineOrchestrator.__new__(scheduler.PipelineOrchestrator)
    orch.config = cfg
    orch.harvester = MagicMock()
    orch.harvester.harvest_channel.return_value = []
    orch.transcriber = MagicMock()
    orch.transcriber.transcribe.return_value = []
    orch.transcriber.get_full_transcript.return_value = "Hallo"
    orch.sub_gen = MagicMock()
    orch.meta_gen = MagicMock()
    orch.meta_gen.generate.return_value = {
        "title": "AI Title",
        "description": "Desc",
        "tags": "#gaming",
    }
    orch.composer = MagicMock()
    orch.composer.render_short.return_value = rendered_file
    orch.yt_uploader = MagicMock()
    orch.tt_uploader = MagicMock()
    orch.tt_uploader.upload_short.return_value = None

    orch.run_cycle()

    assert len(status_updates) == 1
    cid, status, kw = status_updates[0]
    assert cid == "c1"
    assert status == "ready"
    assert kw["tiktok_video_id"] is None
    assert "TikTok" in (kw["error_log"] or "")
