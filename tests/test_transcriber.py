import sys
import types
from pathlib import Path
from types import SimpleNamespace

from src.video.transcriber import VideoTranscriber


def test_transcribe_falls_back_to_cpu_when_cuda_dll_missing_at_runtime(monkeypatch, tmp_path):
    init_calls: list[tuple[str, str, str]] = []

    class _FakeWhisperModel:
        def __init__(self, model_size, device="cuda", compute_type="float16"):
            init_calls.append((model_size, device, compute_type))
            self.device = device

        def transcribe(self, _path, **_kwargs):
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            seg = SimpleNamespace(
                start=0.0,
                end=1.2,
                text="Hallo Welt",
                words=[SimpleNamespace(word="Hallo", start=0.0, end=0.5, probability=0.99)],
            )
            return iter([seg]), SimpleNamespace(language="de")

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    monkeypatch.setattr("src.video.transcriber.load_config", lambda: {"video": {"whisper_model": "small", "device": "cuda"}})

    vt = VideoTranscriber()
    result = vt.transcribe(Path(tmp_path / "clip.mp4"))

    assert vt.device == "cpu"
    assert init_calls == [("small", "cuda", "float16"), ("small", "cpu", "int8")]
    assert result == [
        {
            "start": 0.0,
            "end": 1.2,
            "text": "Hallo Welt",
            "words": [{"word": "Hallo", "start": 0.0, "end": 0.5, "probability": 0.99}],
        }
    ]
