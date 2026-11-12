from pathlib import Path

from src.video.layout import build_filter_graph

RAW = Path("raw.mp4")
VIDEO_INFO = {"width": 1920, "height": 1080, "duration": 30.0, "fps": 60.0, "has_audio": True}


def test_snapshot_auto_blur_stack_no_face():
    fg, inputs, sticker_y = build_filter_graph(RAW, VIDEO_INFO, layout_mode="auto")
    assert inputs == ["-i", "raw.mp4"]
    assert sticker_y == 520
    assert fg == (
        "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
        "boxblur=6:2,scale=1080:1920[bg];"
        "[0:v]scale=1080:608[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];[base]copy[v]"
    )


def test_snapshot_auto_with_facecam():
    fg, inputs, sticker_y = build_filter_graph(
        RAW, VIDEO_INFO, layout_mode="auto", face_box=(100, 100, 200, 200)
    )
    assert inputs == ["-i", "raw.mp4"]
    assert sticker_y == 620
    assert fg == (
        "[0:v]crop=440:293:0:20,scale=1080:720[cam];"
        "[0:v]scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
        "[cam][game]vstack=inputs=2[base];[base]copy[v]"
    )


def test_snapshot_single_916_pct():
    fg, inputs, sticker_y = build_filter_graph(
        RAW,
        VIDEO_INFO,
        layout_mode="single_916",
        custom_crops={"mode": "single_916", "single": {"x_pct": 0.25}},
    )
    assert inputs == ["-i", "raw.mp4"]
    assert sticker_y == 480
    assert fg == "[0:v]crop=606:1080:480:0,scale=1080:1920[base];[base]copy[v]"


def test_snapshot_custom_cam_and_game():
    fg, inputs, sticker_y = build_filter_graph(
        RAW,
        VIDEO_INFO,
        layout_mode="custom",
        custom_crops={
            "enabled": True,
            "cam": {"x": 10, "y": 20, "w": 400, "h": 300},
            "game": {"x": 200, "y": 0, "w": 1200, "h": 1080},
        },
    )
    assert inputs == ["-i", "raw.mp4"]
    assert sticker_y == 620
    assert fg == (
        "[0:v]crop=400:300:10:20,scale=1080:720:force_original_aspect_ratio=increase,crop=1080:720[cam];"
        "[0:v]crop=1200:1080:200:0,scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
        "[cam][game]vstack=inputs=2[base];[base]copy[v]"
    )


def test_snapshot_custom_no_cam_with_game_crop():
    fg, inputs, sticker_y = build_filter_graph(
        RAW,
        VIDEO_INFO,
        layout_mode="custom",
        custom_crops={
            "enabled": True,
            "cam": {"enabled": False, "w": 0},
            "game": {"x": 400, "y": 0, "w": 608, "h": 1080},
        },
    )
    assert inputs == ["-i", "raw.mp4"]
    assert sticker_y == 520
    assert fg == (
        "[0:v]crop=608:1080:400:0,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base];"
        "[base]copy[v]"
    )


def test_snapshot_with_3d_cam_sticker_and_subtitles():
    fg, inputs, sticker_y = build_filter_graph(
        RAW,
        VIDEO_INFO,
        layout_mode="split_cam_top",
        face_box=(0, 0, 320, 240),
        cam_3d_path=Path("cam3d.mp4"),
        sticker_path=Path("sticker.png"),
        ass_subtitle_path=Path(r"C:\Users\Max O'Neil\subs [1].ass"),
    )
    assert inputs == ["-i", "raw.mp4", "-i", "cam3d.mp4", "-i", "sticker.png"]
    assert sticker_y == 620
    assert fg == (
        "[1:v]scale=1080:720:force_original_aspect_ratio=increase,crop=1080:720[cam];"
        "[0:v]scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200[game];"
        "[cam][game]vstack=inputs=2[base];"
        "[base][2:v]overlay=(W-w)/2:620[with_sticker];"
        r"[with_sticker]subtitles='C\:/Users/Max O'\''Neil/subs [1].ass'[v]"
    )
