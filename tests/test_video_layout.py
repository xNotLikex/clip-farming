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


def test_cancel_active_render_kills_and_waits(monkeypatch):
    events: list[str] = []

    class _FakeProc:
        def poll(self):
            return None

        def kill(self):
            events.append("kill")

        def wait(self, timeout=None):
            events.append(f"wait:{timeout}")
            return 0

    job = {"proc": _FakeProc(), "cancelled": False}
    monkeypatch.setattr(layout, "active_renders", {"c1": job})

    assert layout.cancel_active_render("c1") is True
    assert job["cancelled"] is True
    assert events == ["kill", "wait:5"]


def test_escape_ffmpeg_filter_path_handles_windows_special_chars():
    raw_path = r"C:\Users\Max O'Neil\clips [1].ass"
    escaped = layout.escape_ffmpeg_filter_path(raw_path)
    assert escaped == r"C\:/Users/Max O'\''Neil/clips [1].ass"


def test_detect_facecam_overlay_uses_metadata_cache(monkeypatch, tmp_path):
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_file = meta_dir / "clip42.json"
    meta_file.write_text(
        json.dumps({"facecam_checked": True, "detected_face_box": [10, 20, 120, 90]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(layout, "METADATA_OUTPUT_DIR", meta_dir)
    monkeypatch.setattr(
        layout.cv2,
        "VideoCapture",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("VideoCapture sollte nicht aufgerufen werden")),
    )

    composer = layout.VideoComposer.__new__(layout.VideoComposer)
    assert composer.detect_facecam_overlay(tmp_path / "raw.mp4", clip_id="clip42") == (10, 20, 120, 90)


def _setup_fake_composer(monkeypatch, tmp_path, encoder_key: str):
    shorts_dir = tmp_path / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    raw_file = tmp_path / "raw.mp4"
    raw_file.write_bytes(b"fake-raw")

    monkeypatch.setattr(layout, "SHORTS_OUTPUT_DIR", shorts_dir)
    monkeypatch.setattr(
        layout,
        "probe_video",
        lambda _p: {"duration": 10.0, "width": 1920, "height": 1080, "fps": 30.0, "has_audio": True},
    )
    monkeypatch.setattr(layout, "generate_thumbnail", lambda *_a, **_k: None)

    composer = layout.VideoComposer.__new__(layout.VideoComposer)
    composer.config = {}
    composer.video_cfg = {}
    composer.use_nvenc = True
    composer.hardware_encoder = encoder_key
    composer.encoder_profile = layout.ENCODER_PROFILES[encoder_key]
    composer.audio_normalize = False
    composer.detect_facecam_overlay = lambda *_a, **_k: None
    return composer, raw_file, shorts_dir


def test_render_short_falls_back_from_qsv_to_mf_on_runtime_failure(monkeypatch, tmp_path):
    composer, raw_file, _ = _setup_fake_composer(monkeypatch, tmp_path, "qsv")
    attempted_codecs: list[str] = []
    progress_encoders: list[str] = []

    class _FakeProc:
        def __init__(self, cmd):
            codec = cmd[cmd.index("-c:v") + 1]
            attempted_codecs.append(codec)
            self._codec = codec
            self._out_path = Path(cmd[-1])
            self.stdout = iter(["progress=end\n"])
            self.stderr = iter(["QSV init failed\n"] if codec == "h264_qsv" else [])
            self.returncode = 1 if codec == "h264_qsv" else 0
            if self.returncode == 0:
                self._out_path.write_bytes(b"x" * 2048)

        def wait(self):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(layout.subprocess, "Popen", lambda cmd, **_k: _FakeProc(cmd))

    out = composer.render_short(
        raw_video_path=raw_file,
        clip_id="clip_qsv_fail",
        layout_mode="auto",
        on_progress=lambda pct, _eta, info: progress_encoders.append(info) if pct == 5 else None,
    )

    assert out is not None and out.exists()
    assert attempted_codecs == ["h264_qsv", "h264_mf"]
    assert progress_encoders == ["Intel QuickSync", "Windows Media Foundation"]


def test_render_short_does_not_fallback_when_cancelled(monkeypatch, tmp_path):
    composer, raw_file, _ = _setup_fake_composer(monkeypatch, tmp_path, "qsv")
    attempted_codecs: list[str] = []

    class _FakeProc:
        def __init__(self, cmd):
            codec = cmd[cmd.index("-c:v") + 1]
            attempted_codecs.append(codec)
            self.stdout = self._iter_stdout()
            self.stderr = iter([])
            self.returncode = 1

        def _iter_stdout(self):
            with layout.render_lock:
                layout.active_renders["clip_cancel"]["cancelled"] = True
            yield "out_time_us=1000000\n"

        def wait(self):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(layout.subprocess, "Popen", lambda cmd, **_k: _FakeProc(cmd))

    out = composer.render_short(
        raw_video_path=raw_file,
        clip_id="clip_cancel",
        layout_mode="auto",
    )

    assert out is None
    assert attempted_codecs == ["h264_qsv"]




