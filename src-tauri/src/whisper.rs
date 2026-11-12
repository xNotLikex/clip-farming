use serde_json::Value;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::config::{get_models_dir, load_config, resolve_binary};
use crate::subtitles::{TranscriptSegment, WordSegment};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Lädt bei Bedarf das GGML-Modell für whisper.cpp herunter und gibt den lokalen Pfad zurück.
pub async fn ensure_whisper_model(model_name: &str) -> Result<PathBuf, String> {
    let clean_name = match model_name.trim().to_lowercase().as_str() {
        "tiny" => "tiny",
        "base" => "base",
        "small" => "small",
        "medium" => "medium",
        "large" | "large-v3" => "large-v3",
        "large-v3-turbo" | "turbo" => "large-v3-turbo",
        _ => "small",
    };

    let models_dir = get_models_dir();
    std::fs::create_dir_all(&models_dir).map_err(|e| e.to_string())?;
    let model_path = models_dir.join(format!("ggml-{clean_name}.bin"));

    if let Ok(meta) = std::fs::metadata(&model_path) {
        if meta.len() > 10_000_000 {
            return Ok(model_path);
        }
    }

    let url = format!(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{clean_name}.bin"
    );
    let tmp_path = models_dir.join(format!("ggml-{clean_name}.bin.tmp"));

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(600))
        .build()
        .map_err(|e| format!("HTTP-Client Fehler: {e}"))?;

    let mut resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Whisper-Modell Download fehlgeschlagen ({clean_name}): {e}"))?;

    if !resp.status().is_success() {
        return Err(format!(
            "Whisper-Modell Download HTTP-Fehler {} für {}",
            resp.status(),
            clean_name
        ));
    }

    let mut file = std::fs::File::create(&tmp_path).map_err(|e| e.to_string())?;
    while let Some(chunk) = resp.chunk().await.map_err(|e| e.to_string())? {
        file.write_all(&chunk).map_err(|e| e.to_string())?;
    }
    file.flush().map_err(|e| e.to_string())?;
    drop(file);

    if model_path.exists() {
        let _ = std::fs::remove_file(&model_path);
    }
    std::fs::rename(&tmp_path, &model_path).map_err(|e| e.to_string())?;
    Ok(model_path)
}

/// Extrahiert 16kHz Mono PCM WAV für whisper-cli.
pub fn extract_wav_16k(video_path: &Path, wav_path: &Path) -> Result<(), String> {
    let ffmpeg = resolve_binary("ffmpeg");
    let mut cmd = Command::new(&ffmpeg);
    cmd.args(["-y", "-i"])
        .arg(video_path)
        .args(["-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"])
        .arg(wav_path)
        .stdout(Stdio::null())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let output = cmd
        .output()
        .map_err(|e| format!("FFmpeg Audio-Extraktion fehlgeschlagen: {e}"))?;

    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(format!("FFmpeg Audio-Extraktion Fehler: {}", err.trim()));
    }
    Ok(())
}

/// Parst die JSON-Ausgabe (`-ojf`) von whisper.cpp in Wort-Segmente.
pub fn parse_whisper_json(json_str: &str) -> Result<Vec<TranscriptSegment>, String> {
    let root: Value = serde_json::from_str(json_str)
        .map_err(|e| format!("Whisper JSON konnte nicht geparst werden: {e}"))?;

    let items = root
        .get("transcription")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "Whisper JSON enthält kein 'transcription'-Feld".to_string())?;

    let mut segments = Vec::new();

    for item in items {
        let seg_text = item
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();

        if seg_text.is_empty()
            || seg_text.eq_ignore_ascii_case("[BLANK_AUDIO]")
            || seg_text.eq_ignore_ascii_case("[MUSIK]")
        {
            continue;
        }

        let seg_from_ms = item
            .get("offsets")
            .and_then(|o| o.get("from"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let seg_to_ms = item
            .get("offsets")
            .and_then(|o| o.get("to"))
            .and_then(|v| v.as_f64())
            .unwrap_or(seg_from_ms + 500.0);

        let mut words: Vec<WordSegment> = Vec::new();

        if let Some(tokens) = item.get("tokens").and_then(|t| t.as_array()) {
            for tok in tokens {
                let raw_tok = tok.get("text").and_then(|v| v.as_str()).unwrap_or("");
                let trimmed = raw_tok.trim();
                if trimmed.is_empty()
                    || (trimmed.starts_with("[_") && trimmed.ends_with(']'))
                    || trimmed.starts_with("<|")
                {
                    continue;
                }

                let t_from = tok
                    .get("offsets")
                    .and_then(|o| o.get("from"))
                    .and_then(|v| v.as_f64())
                    .unwrap_or(seg_from_ms)
                    / 1000.0;
                let t_to = tok
                    .get("offsets")
                    .and_then(|o| o.get("to"))
                    .and_then(|v| v.as_f64())
                    .unwrap_or(t_from * 1000.0 + 120.0)
                    / 1000.0;
                let prob = tok.get("p").and_then(|v| v.as_f64()).unwrap_or(1.0);

                let starts_new_word = raw_tok.starts_with(' ') || words.is_empty();
                if starts_new_word {
                    words.push(WordSegment {
                        word: trimmed.to_string(),
                        start: t_from,
                        end: t_to.max(t_from + 0.06),
                        probability: prob,
                    });
                } else if let Some(last) = words.last_mut() {
                    last.word.push_str(trimmed);
                    last.end = last.end.max(t_to);
                }
            }
        }

        if words.is_empty() {
            let split_words: Vec<&str> = seg_text.split_whitespace().collect();
            let count = split_words.len().max(1) as f64;
            let start_s = seg_from_ms / 1000.0;
            let end_s = (seg_to_ms / 1000.0).max(start_s + 0.2);
            let step = (end_s - start_s) / count;
            for (i, w) in split_words.iter().enumerate() {
                let ws = start_s + i as f64 * step;
                let we = (ws + step * 0.92).max(ws + 0.06);
                words.push(WordSegment {
                    word: (*w).to_string(),
                    start: ws,
                    end: we,
                    probability: 1.0,
                });
            }
        }

        segments.push(TranscriptSegment {
            start: seg_from_ms / 1000.0,
            end: seg_to_ms / 1000.0,
            text: seg_text,
            words,
        });
    }

    Ok(segments)
}

/// Transkribiert ein Video lokal über `whisper-cli.exe` mit Wort-Zeitstempeln.
pub async fn transcribe_video(video_path: &Path) -> Result<Vec<TranscriptSegment>, String> {
    if !video_path.exists() {
        return Err(format!(
            "Video für Transkription nicht gefunden: {}",
            video_path.display()
        ));
    }

    let cfg = load_config();
    let model_name = if cfg.video.whisper_model.trim().is_empty() {
        "small".to_string()
    } else {
        cfg.video.whisper_model.clone()
    };
    let language = cfg
        .video
        .extra
        .get("whisper_language")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("de")
        .to_string();

    let model_path = ensure_whisper_model(&model_name).await?;
    let whisper_bin = resolve_binary("whisper-cli");

    let video_path_owned = video_path.to_path_buf();
    tokio::task::spawn_blocking(move || {
        let stem = video_path_owned
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("clip");
        let work_dir = video_path_owned.parent().unwrap_or_else(|| Path::new("."));
        let wav_path = work_dir.join(format!("temp_whisper_{stem}.wav"));
        let out_prefix = work_dir.join(format!("temp_whisper_{stem}_out"));
        let json_path = PathBuf::from(format!("{}.json", out_prefix.display()));

        extract_wav_16k(&video_path_owned, &wav_path)?;

        let mut cmd = Command::new(&whisper_bin);
        cmd.arg("-m")
            .arg(&model_path)
            .arg("-f")
            .arg(&wav_path)
            .args(["-l", &language, "-ojf", "-of"])
            .arg(&out_prefix)
            .stdout(Stdio::null())
            .stderr(Stdio::piped());

        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let output = cmd
            .output()
            .map_err(|e| format!("whisper-cli Startfehler: {e}"))?;

        let _ = std::fs::remove_file(&wav_path);

        if !output.status.success() {
            let _ = std::fs::remove_file(&json_path);
            let err = String::from_utf8_lossy(&output.stderr);
            return Err(format!("whisper-cli Fehler: {}", err.trim()));
        }

        let json_raw = std::fs::read_to_string(&json_path)
            .map_err(|e| format!("Whisper JSON-Ausgabe fehlt: {e}"))?;
        let _ = std::fs::remove_file(&json_path);

        parse_whisper_json(&json_raw)
    })
    .await
    .map_err(|e| format!("Whisper Task Fehler: {e}"))?
}
