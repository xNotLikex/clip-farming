import subprocess
from unittest.mock import MagicMock

from src.video import gpu


def test_test_ffmpeg_encoder_probes_1080x1920_yuv420p(monkeypatch):
    seen_cmds: list[list[str]] = []

    def fake_run(cmd, capture_output=True, timeout=6):
        seen_cmds.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(gpu.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert gpu.test_ffmpeg_encoder("h264_qsv") is True
    assert len(seen_cmds) == 1
    cmd_str = " ".join(seen_cmds[0])
    assert "size=1080x1920" in cmd_str
    assert "-pix_fmt yuv420p" in cmd_str
    assert "-c:v h264_qsv" in cmd_str


def test_get_encoder_fallback_chain_orders_qsv_mf_cpu(monkeypatch):
    monkeypatch.setattr(
        gpu,
        "get_installed_gpus",
        lambda: [{"name": "Intel(R) UHD Graphics 630", "ram_mb": 128, "vendor": "intel", "is_onboard": True}],
    )

    chain_auto = gpu.get_encoder_fallback_chain("auto")
    assert [p["codec"] for p in chain_auto] == ["h264_qsv", "h264_mf", "libx264"]

    chain_qsv = gpu.get_encoder_fallback_chain("qsv")
    assert [p["codec"] for p in chain_qsv] == ["h264_qsv", "h264_mf", "libx264"]

    chain_amf = gpu.get_encoder_fallback_chain("amf")
    assert [p["codec"] for p in chain_amf] == ["h264_amf", "h264_mf", "libx264"]

    chain_cpu = gpu.get_encoder_fallback_chain("cpu")
    assert [p["codec"] for p in chain_cpu] == ["libx264"]


def test_get_best_video_encoder_falls_back_when_qsv_probe_fails(monkeypatch):
    monkeypatch.setattr(
        gpu,
        "get_installed_gpus",
        lambda: [{"name": "Intel(R) UHD Graphics 630", "ram_mb": 128, "vendor": "intel", "is_onboard": True}],
    )
    monkeypatch.setattr(gpu, "test_ffmpeg_encoder", lambda codec: codec == "h264_mf")

    best = gpu.get_best_video_encoder("auto")
    assert best["codec"] == "h264_mf"
