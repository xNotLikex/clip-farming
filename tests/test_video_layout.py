import json
import subprocess
from pathlib import Path

from src.video import layout


def test_probe_video_parses_single_ffprobe_output(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_check_output(cmd, text=True, timeout=10):
        calls.append(cmd)
        return json.dumps(
            {
                "format": {"duration": "42.5"},
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1280,
                        "height": 720,
                        "avg_frame_rate": "60000/1001",
                    },
                    {"codec_type": "audio"},
                ],
            }
        )

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    info = layout.probe_video(tmp_path / "clip.mp4")

    assert len(calls) == 1
    assert info["duration"] == 42.5
    assert info["width"] == 1280
    assert info["height"] == 720
    assert abs(info["fps"] - 59.94) < 0.05
    assert info["has_audio"] is True
    assert layout.get_video_duration(tmp_path / "clip.mp4") == 42.5


def test_probe_video_returns_defaults_on_error(monkeypatch):
    def failing_check_output(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffprobe")

    monkeypatch.setattr(subprocess, "check_output", failing_check_output)
    info = layout.probe_video(Path("missing.mp4"))

    assert info == {
        "duration": 30.0,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "has_audio": True,
    }
