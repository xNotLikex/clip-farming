use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::config::{
    get_data_root, get_metadata_dir, get_raw_clips_dir, get_shorts_dir, load_config,
    preset_corner_crops, resolve_binary,
};
use crate::gpu::{build_runtime_fallback_chain, select_best_encoder};
use crate::state::{
    clear_active_render, consume_render_cancelled, is_render_cancelled, register_active_render,
};
use crate::sticker::create_tiktok_sticker;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoInfo {
    pub width: u32,
    pub height: u32,
    pub duration: f64,
    pub fps: f64,
    pub has_audio: bool,
}

impl Default for VideoInfo {
    fn default() -> Self {
        Self {
            width: 1920,
            height: 1080,
            duration: 30.0,
            fps: 60.0,
            has_audio: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct FilterGraphResult {
    pub filter_complex: String,
    pub inputs: Vec<String>,
    pub sticker_y: u32,
}

/// Escaped einen Dateipfad für FFmpeg `subtitles='...'` Filter (Windows-kompatibel).
pub fn escape_ffmpeg_filter_path(path: &Path) -> String {
    let mut s = path.to_string_lossy().replace('\\', "/");
    s = s.replace(':', "\\:");
    s = s.replace('\'', "\\'");
    s
}

fn even(n: i64, minimum: i64) -> i64 {
    let clamped = n.max(minimum);
    if clamped % 2 == 0 {
        clamped
    } else {
        clamped - 1
    }
}

fn parse_fps(raw: &str) -> f64 {
    let s = raw.trim();
    if s.is_empty() || s == "0/0" {
        return 60.0;
    }
    if let Some((num_s, den_s)) = s.split_once('/') {
        if let (Ok(num), Ok(den)) = (num_s.parse::<f64>(), den_s.parse::<f64>()) {
            if den > 0.0 {
                let fps = num / den;
                if (1.0..=240.0).contains(&fps) {
                    return fps;
                }
            }
        }
        return 60.0;
    }
    if let Ok(fps) = s.parse::<f64>() {
        if (1.0..=240.0).contains(&fps) {
            return fps;
        }
    }
    60.0
}

/// Ermittelt Auflösung, Länge, FPS und Audio-Existenz eines Videos über ffprobe.
pub fn probe_video(video_path: &Path) -> VideoInfo {
    let mut info = VideoInfo::default();
    let ffprobe = resolve_binary("ffprobe");

    let mut cmd = Command::new(&ffprobe);
    cmd.args([
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
    ])
    .arg(video_path);

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let Ok(output) = cmd.output() else {
        return info;
    };
    if !output.status.success() {
        return info;
    }

    let Ok(data) = serde_json::from_slice::<Value>(&output.stdout) else {
        return info;
    };

    if let Some(dur_val) = data.get("format").and_then(|f| f.get("duration")) {
        let parsed = dur_val
            .as_str()
            .and_then(|s| s.parse::<f64>().ok())
            .or_else(|| dur_val.as_f64())
            .unwrap_or(0.0);
        if parsed > 0.0 {
            info.duration = parsed;
        }
    }

    if let Some(streams) = data.get("streams").and_then(|s| s.as_array()) {
        if let Some(vstream) = streams
            .iter()
            .find(|s| s.get("codec_type").and_then(|c| c.as_str()) == Some("video"))
        {
            let w = vstream.get("width").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            let h = vstream.get("height").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            if w > 0 && h > 0 {
                info.width = w;
                info.height = h;
            }
            if (info.duration - 30.0).abs() < f64::EPSILON {
                let sdur = vstream
                    .get("duration")
                    .and_then(|d| d.as_str().and_then(|s| s.parse::<f64>().ok()).or_else(|| d.as_f64()))
                    .unwrap_or(0.0);
                if sdur > 0.0 {
                    info.duration = sdur;
                }
            }
            let fps_raw = vstream
                .get("avg_frame_rate")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty() && *s != "0/0")
                .or_else(|| vstream.get("r_frame_rate").and_then(|v| v.as_str()))
                .unwrap_or("");
            info.fps = parse_fps(fps_raw);
        }

        info.has_audio = streams
            .iter()
            .any(|s| s.get("codec_type").and_then(|c| c.as_str()) == Some("audio"));
    }

    info
}

fn resolve_rect(rect: &Value, vw: u32, vh: u32) -> (i64, i64, i64, i64) {
    let rx = rect.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let ry = rect.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let rw = rect.get("w").and_then(|v| v.as_f64()).unwrap_or(0.3);
    let rh = rect.get("h").and_then(|v| v.as_f64()).unwrap_or(0.3);

    let x = ((rx * vw as f64) as i64).clamp(0, (vw as i64 - 2).max(0));
    let y = ((ry * vh as f64) as i64).clamp(0, (vh as i64 - 2).max(0));
    let mut w = even((rw * vw as f64) as i64, 2);
    let mut h = even((rh * vh as f64) as i64, 2);
    w = w.min(even((vw as i64 - x).max(2), 2));
    h = h.min(even((vh as i64 - y).max(2), 2));
    (x, y, w.max(2), h.max(2))
}

/// Baut den deterministischen 9:16 FFmpeg-Filtergraph auf.
pub fn build_filter_graph(
    raw_video_path: &Path,
    video_info: &VideoInfo,
    layout_mode: &str,
    custom_crops: Option<&Value>,
    face_box: Option<(i64, i64, i64, i64)>,
    sticker_path: Option<&Path>,
    ass_subtitle_path: Option<&Path>,
) -> FilterGraphResult {
    let vw = video_info.width.max(2);
    let vh = video_info.height.max(2);

    let mut inputs = vec![
        "-i".to_string(),
        raw_video_path.to_string_lossy().to_string(),
    ];

    let is_single_916 = layout_mode == "single_916"
        || custom_crops
            .and_then(|c| c.get("mode"))
            .and_then(|m| m.as_str())
            == Some("single_916");

    let custom_enabled = custom_crops
        .and_then(|c| c.get("enabled"))
        .and_then(|b| b.as_bool())
        .unwrap_or(true);

    let (base_graph, sticker_y) = if is_single_916 {
        let sw = even(((vh as f64 * 9.0 / 16.0) as i64).min(vw as i64), 2);
        let sh = even(vh as i64, 2);
        let sx = ((vw as i64 - sw) / 2).max(0);
        (
            format!("[0:v]crop={sw}:{sh}:{sx}:0,scale=1080:1920[base]"),
            480u32,
        )
    } else if let Some(crops) = custom_crops.filter(|_| custom_enabled) {
        let cam = crops.get("cam").filter(|v| !v.is_null());
        let game = crops.get("game").filter(|v| !v.is_null());
        let has_cam = cam
            .and_then(|c| c.get("w"))
            .and_then(|w| w.as_f64())
            .map(|w| w > 0.0)
            .unwrap_or(false);

        if has_cam {
            let (cx, cy, cw, ch) = resolve_rect(cam.unwrap(), vw, vh);
            let cam_stream = format!(
                "[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1080:675:force_original_aspect_ratio=increase,crop=1080:675[cam]"
            );
            let game_filter = if let Some(g) = game {
                let (gx, gy, gw, gh) = resolve_rect(g, vw, vh);
                format!(
                    "[0:v]crop={gw}:{gh}:{gx}:{gy},scale=1080:1245:force_original_aspect_ratio=increase,crop=1080:1245[game];"
                )
            } else {
                let gw = even(((vw as f64) * 0.52) as i64, 2);
                let gh = even(vh as i64, 2);
                let gx = ((vw as i64 - gw) / 2).max(0);
                format!(
                    "[0:v]crop={gw}:{gh}:{gx}:0,scale=1080:1245:force_original_aspect_ratio=increase,crop=1080:1245[game];"
                )
            };
            (
                format!("{cam_stream};{game_filter}[cam][game]vstack=inputs=2[base]"),
                620u32,
            )
        } else if let Some(g) = game {
            let (gx, gy, gw, gh) = resolve_rect(g, vw, vh);
            (
                format!(
                    "[0:v]crop={gw}:{gh}:{gx}:{gy},scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base]"
                ),
                520u32,
            )
        } else {
            (
                "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,scale=1080:1920[bg];[0:v]scale=1080:608[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]".to_string(),
                520u32,
            )
        }
    } else if let Some((fx, fy, fw, fh)) = face_box {
        let cam_w = even(
            (fw as f64 * 2.6).max(vw as f64 * 0.18).min(vw as f64 * 0.45) as i64,
            2,
        );
        let cam_h = even((cam_w as f64 * 675.0 / 1080.0) as i64, 2);
        let cx = (fx + fw / 2 - cam_w / 2).clamp(0, (vw as i64 - cam_w).max(0));
        let cy = (fy + fh / 2 - cam_h / 2).clamp(0, (vh as i64 - cam_h).max(0));
        let cam_stream = format!(
            "[0:v]crop={cam_w}:{cam_h}:{cx}:{cy},scale=1080:675:force_original_aspect_ratio=increase,crop=1080:675[cam]"
        );
        let gw = even((vw as f64 * 0.52) as i64, 2);
        let gh = even(vh as i64, 2);
        let gx = ((vw as i64 - gw) / 2).max(0);
        let game_stream = format!(
            "[0:v]crop={gw}:{gh}:{gx}:0,scale=1080:1245:force_original_aspect_ratio=increase,crop=1080:1245[game]"
        );
        (
            format!("{cam_stream};{game_stream};[cam][game]vstack=inputs=2[base]"),
            620u32,
        )
    } else {
        (
            "[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,scale=1080:1920[bg];[0:v]scale=1080:608[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]".to_string(),
            520u32,
        )
    };

    let mut filter_complex = base_graph;
    let mut current_label = "base";

    if let Some(sp) = sticker_path.filter(|p| p.exists()) {
        let sticker_idx = inputs.len() / 2;
        inputs.push("-i".to_string());
        inputs.push(sp.to_string_lossy().to_string());
        filter_complex.push_str(&format!(
            ";[{current_label}][{sticker_idx}:v]overlay=(W-w)/2:{sticker_y}[with_sticker]"
        ));
        current_label = "with_sticker";
    }

    if let Some(sub) = ass_subtitle_path.filter(|p| p.exists()) {
        let escaped = escape_ffmpeg_filter_path(sub);
        filter_complex.push_str(&format!(";[{current_label}]subtitles='{escaped}'[v]"));
    } else {
        filter_complex.push_str(&format!(";[{current_label}]copy[v]"));
    }

    FilterGraphResult {
        filter_complex,
        inputs,
        sticker_y,
    }
}

/// Erzeugt ein 9:16 JPEG-Vorschaubild aus dem fertigen Short (oder Rohclip als Fallback).
pub fn generate_thumbnail(clip_id: &str, force: bool) -> Option<PathBuf> {
    let thumb_dir = get_data_root().join("thumbnails");
    let _ = std::fs::create_dir_all(&thumb_dir);
    let thumb_path = thumb_dir.join(format!("{clip_id}.jpg"));

    if thumb_path.exists() && !force {
        return Some(thumb_path);
    }

    let short_path = get_shorts_dir().join(format!("short_{clip_id}.mp4"));
    let video_path = if short_path.exists() {
        short_path
    } else {
        let raw_path = get_raw_clips_dir().join(format!("{clip_id}.mp4"));
        if !raw_path.exists() {
            return None;
        }
        raw_path
    };

    let ffmpeg = resolve_binary("ffmpeg");
    for timestamp in ["00:00:01.000", "00:00:00.200", "00:00:00.000"] {
        let mut cmd = Command::new(&ffmpeg);
        cmd.args(["-y", "-ss", timestamp, "-i"])
            .arg(&video_path)
            .args(["-frames:v", "1", "-update", "1", "-q:v", "2"])
            .arg(&thumb_path)
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let _ = cmd.status();
        if let Ok(meta) = std::fs::metadata(&thumb_path) {
            if meta.len() > 0 {
                return Some(thumb_path);
            }
        }
    }

    None
}

#[derive(Debug, Clone)]
pub struct RenderOptions {
    pub clip_id: String,
    pub raw_video_path: PathBuf,
    pub ass_subtitle_path: Option<PathBuf>,
    pub layout_mode: String,
    pub custom_crops: Option<Value>,
    pub header_sticker_text: Option<String>,
    pub streamer_name: Option<String>,
}

/// Rendert den fertigen 9:16 Short mit Hardware-Encoder-Fallback und Live-Progress.
pub fn render_short<F>(opts: &RenderOptions, mut on_progress: F) -> Result<PathBuf, String>
where
    F: FnMut(u8, u64, &str),
{
    if !opts.raw_video_path.exists() {
        return Err(format!(
            "Rohvideo existiert nicht: {}",
            opts.raw_video_path.display()
        ));
    }

    let shorts_dir = get_shorts_dir();
    std::fs::create_dir_all(&shorts_dir).map_err(|e| e.to_string())?;
    let output_file = shorts_dir.join(format!("short_{}.mp4", opts.clip_id));
    let temp_output_file = shorts_dir.join(format!("short_{}.tmp.mp4", opts.clip_id));

    let cfg = load_config();
    let audio_normalize = cfg.video.audio_normalize;
    let hw_pref = if !cfg.video.use_nvenc && cfg.video.hardware_encoder == "auto" {
        "cpu".to_string()
    } else {
        cfg.video.hardware_encoder.clone()
    };

    let video_info = probe_video(&opts.raw_video_path);
    let total_duration = video_info.duration.max(1.0);

    let mut layout_mode = if opts.layout_mode.is_empty() {
        "auto".to_string()
    } else {
        opts.layout_mode.clone()
    };
    let mut custom_crops = opts.custom_crops.clone();

    if custom_crops.is_none() {
        let meta_file = get_metadata_dir().join(format!("{}.json", opts.clip_id));
        if meta_file.exists() {
            if let Ok(raw) = std::fs::read_to_string(&meta_file) {
                if let Ok(meta) = serde_json::from_str::<Value>(&raw) {
                    if let Some(mc) = meta.get("custom_crops").filter(|v| !v.is_null()) {
                        custom_crops = Some(mc.clone());
                    }
                    if layout_mode == "auto" {
                        if let Some(ml) = meta.get("layout_mode").and_then(|v| v.as_str()) {
                            if !ml.is_empty() && ml != "auto" {
                                layout_mode = ml.to_string();
                            }
                        }
                    }
                }
            }
        }
    }

    if custom_crops.is_none() {
        if let Some(ref sname) = opts.streamer_name {
            if let Some(st) = cfg
                .streamers
                .iter()
                .find(|s| s.name.eq_ignore_ascii_case(sname))
            {
                let st_layout = st.layout.as_str();
                if let Some(preset) = preset_corner_crops(st_layout) {
                    custom_crops = serde_json::to_value(preset).ok();
                    layout_mode = "custom".to_string();
                } else if let Some(ref sc) = st.custom_crops {
                    custom_crops = Some(sc.clone());
                    if layout_mode == "auto" {
                        layout_mode = if st_layout.is_empty() {
                            "custom".to_string()
                        } else {
                            st_layout.to_string()
                        };
                    }
                } else if layout_mode == "auto" && st_layout != "auto" && !st_layout.is_empty() {
                    layout_mode = st_layout.to_string();
                }
            }
        }
    }

    if custom_crops.is_none() {
        if let Some(preset) = preset_corner_crops(&layout_mode) {
            custom_crops = serde_json::to_value(preset).ok();
        }
    }

    let face_box = if layout_mode == "split_cam_top" {
        Some((0, 0, 320, 240))
    } else {
        None
    };

    let sticker_png = if let Some(ref txt) = opts.header_sticker_text {
        let trimmed = txt.trim();
        if !trimmed.is_empty() {
            let p = opts
                .raw_video_path
                .parent()
                .unwrap_or(&shorts_dir)
                .join(format!("sticker_{}.png", opts.clip_id));
            create_tiktok_sticker(trimmed, &p)?;
            Some(p)
        } else {
            None
        }
    } else {
        None
    };

    let fg = build_filter_graph(
        &opts.raw_video_path,
        &video_info,
        &layout_mode,
        custom_crops.as_ref(),
        face_box,
        sticker_png.as_deref(),
        opts.ass_subtitle_path.as_deref(),
    );

    let audio_filter = if audio_normalize {
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=50,loudnorm=I=-14:TP=-1.5:LRA=11"
    } else {
        "anull"
    };

    let best = select_best_encoder(&hw_pref);
    let attempt_profiles = build_runtime_fallback_chain(&best);
    let ffmpeg = resolve_binary("ffmpeg");

    let mut last_err = String::from("Kein FFmpeg-Encoder erfolgreich");

    for profile in &attempt_profiles {
        if is_render_cancelled(&opts.clip_id) {
            consume_render_cancelled(&opts.clip_id);
            cleanup_temp_files(&temp_output_file, sticker_png.as_deref());
            return Err("Rendering durch Benutzer abgebrochen".to_string());
        }

        let mut speed_factor = if profile.codec.contains("nvenc") {
            2.5
        } else if profile.codec.contains("amf")
            || profile.codec.contains("mf")
            || profile.codec.contains("qsv")
        {
            2.0
        } else {
            0.9
        };

        on_progress(5, (total_duration / speed_factor) as u64, &profile.name);

        let mut cmd = Command::new(&ffmpeg);
        cmd.args(["-y", "-progress", "pipe:1", "-nostats"]);
        for arg in &fg.inputs {
            cmd.arg(arg);
        }
        cmd.args(["-filter_complex", &fg.filter_complex, "-map", "[v]", "-map", "0:a?"]);
        cmd.args(["-c:a", "aac", "-b:a", "192k", "-af", audio_filter]);
        for arg in &profile.ffmpeg_args {
            cmd.arg(arg);
        }
        cmd.args(["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
            .arg(&temp_output_file)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                last_err = format!("FFmpeg Startfehler ({}): {}", profile.name, e);
                continue;
            }
        };

        register_active_render(&opts.clip_id, child.id());

        let stderr_handle = child.stderr.take().map(|stderr| {
            std::thread::spawn(move || {
                let mut buf = String::new();
                let mut reader = BufReader::new(stderr);
                let _ = std::io::Read::read_to_string(&mut reader, &mut buf);
                buf
            })
        });

        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                if is_render_cancelled(&opts.clip_id) {
                    let _ = child.kill();
                    break;
                }
                let trimmed = line.trim();
                if let Some(us_str) = trimmed.strip_prefix("out_time_us=") {
                    if let Ok(us) = us_str.parse::<u64>() {
                        let current_sec = us as f64 / 1_000_000.0;
                        let pct = ((current_sec / total_duration) * 100.0).clamp(5.0, 99.0) as u8;
                        let rem = (total_duration - current_sec).max(0.0);
                        let eta = (rem / speed_factor.max(0.5)).max(0.0) as u64;
                        on_progress(pct, eta, &format!("{speed_factor:.1}x"));
                    }
                } else if let Some(spd_str) = trimmed.strip_prefix("speed=") {
                    let clean = spd_str.replace('x', "");
                    if let Ok(spd) = clean.trim().parse::<f64>() {
                        if spd > 0.01 {
                            speed_factor = spd;
                        }
                    }
                } else if trimmed == "progress=end" {
                    on_progress(100, 0, &format!("{speed_factor:.1}x"));
                }
            }
        }

        let status = child.wait();
        let stderr_out = stderr_handle
            .and_then(|h| h.join().ok())
            .unwrap_or_default();

        clear_active_render(&opts.clip_id);
        if consume_render_cancelled(&opts.clip_id) {
            cleanup_temp_files(&temp_output_file, sticker_png.as_deref());
            return Err("Rendering durch Benutzer abgebrochen".to_string());
        }

        let ok_status = status.map(|s| s.success()).unwrap_or(false);
        let file_ok = std::fs::metadata(&temp_output_file)
            .map(|m| m.len() > 1000)
            .unwrap_or(false);

        if ok_status && file_ok {
            if let Some(sp) = sticker_png.as_deref() {
                let _ = std::fs::remove_file(sp);
            }
            replace_with_retry(&temp_output_file, &output_file)?;
            let _ = generate_thumbnail(&opts.clip_id, true);
            on_progress(100, 0, &format!("{speed_factor:.1}x"));
            return Ok(output_file);
        }

        let _ = std::fs::remove_file(&temp_output_file);
        let tail: String = stderr_out
            .chars()
            .rev()
            .take(500)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
        last_err = format!("FFmpeg Fehler ({}): {}", profile.name, tail.trim());
    }

    cleanup_temp_files(&temp_output_file, sticker_png.as_deref());
    Err(last_err)
}

fn cleanup_temp_files(temp_out: &Path, sticker_png: Option<&Path>) {
    let _ = std::fs::remove_file(temp_out);
    if let Some(sp) = sticker_png {
        let _ = std::fs::remove_file(sp);
    }
}

fn replace_with_retry(src: &Path, dst: &Path) -> Result<(), String> {
    for _ in 0..8 {
        if dst.exists() {
            let _ = std::fs::remove_file(dst);
        }
        match std::fs::rename(src, dst) {
            Ok(_) => return Ok(()),
            Err(_) => std::thread::sleep(Duration::from_millis(150)),
        }
    }
    std::fs::rename(src, dst).map_err(|e| format!("Ausgabedatei konnte nicht verschoben werden: {e}"))
}
