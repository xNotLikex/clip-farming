import io
from pathlib import Path

import numpy as np

from src.video import filters


class _FakeCapture:
    def __init__(self, frames: list[np.ndarray]):
        self._frames = frames
        self._idx = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        if prop == filters.cv2.CAP_PROP_FRAME_WIDTH:
            return 320.0
        if prop == filters.cv2.CAP_PROP_FRAME_HEIGHT:
            return 240.0
        if prop == filters.cv2.CAP_PROP_FPS:
            return 30.0
        if prop == filters.cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self._frames))
        return 0.0

    def read(self):
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        self._idx += 1
        return True, frame

    def release(self) -> None:
        self.released = True


class _CaptureBytesIO(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.captured = b""

    def close(self) -> None:
        self.captured = self.getvalue()
        super().close()


class _FakePopen:
    def __init__(self, output_path: Path):
        self.stdin = _CaptureBytesIO()
        self.stderr = io.BytesIO(b"")
        self.returncode = 0
        self._output_path = output_path
        self.written_bytes = b""

    def wait(self, timeout=None) -> int:
        self.written_bytes = self.stdin.captured
        self._output_path.write_bytes(b"mp4-stub")
        return 0


def test_process_cam_video_3d_pipes_raw_frames_to_ffmpeg_stdin(monkeypatch, tmp_path):
    frames = [np.zeros((240, 320, 3), dtype=np.uint8) for _ in range(3)]
    fake_cap = _FakeCapture(frames)
    captured_cmds: list[list[str]] = []
    fake_procs: list[_FakePopen] = []

    monkeypatch.setattr(filters.cv2, "VideoCapture", lambda _p: fake_cap)
    monkeypatch.setattr(filters, "get_face_detector", lambda w, h: None)
    monkeypatch.setattr(
        filters,
        "filter_cam_frame_3d",
        lambda cam_frame, *_args: cam_frame + 1,
    )

    def fake_popen(cmd, stdin=None, stdout=None, stderr=None):
        captured_cmds.append(cmd)
        proc = _FakePopen(Path(cmd[-1]))
        fake_procs.append(proc)
        return proc

    monkeypatch.setattr(filters.subprocess, "Popen", fake_popen)

    out_path = tmp_path / "cam_3d.mp4"
    res = filters.process_cam_video_3d(
        tmp_path / "raw.mp4",
        {"x": 0, "y": 0, "w": 100, "h": 100},
        "cube",
        out_path,
    )

    assert res == out_path
    assert fake_cap.released
    assert len(captured_cmds) == 1
    assert "-f" in captured_cmds[0] and "rawvideo" in captured_cmds[0]
    assert "-pix_fmt" in captured_cmds[0] and "bgr24" in captured_cmds[0]
    assert len(fake_procs[0].written_bytes) == 3 * 100 * 100 * 3
