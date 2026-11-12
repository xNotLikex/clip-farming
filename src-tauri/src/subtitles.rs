use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::config::load_config;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WordSegment {
    pub word: String,
    pub start: f64,
    pub end: f64,
    #[serde(default = "default_prob")]
    pub probability: f64,
}

fn default_prob() -> f64 {
    1.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptSegment {
    pub start: f64,
    pub end: f64,
    pub text: String,
    #[serde(default)]
    pub words: Vec<WordSegment>,
}

/// Konvertiert Sekunden in das ASS-Zeitformat: H:MM:SS.cs
pub fn format_ass_time(seconds: f64) -> String {
    let s = seconds.max(0.0);
    let total_centis = (s * 100.0).round() as u64;
    let centis = total_centis % 100;
    let total_secs = total_centis / 100;
    let secs = total_secs % 60;
    let mins = (total_secs / 60) % 60;
    let hrs = total_secs / 3600;
    format!("{hrs}:{mins:02}:{secs:02}.{centis:02}")
}

fn normalize_token(s: &str) -> String {
    s.trim()
        .to_lowercase()
        .trim_matches(|c: char| ".,!?:;\"'()[]".contains(c))
        .to_string()
}

/// Passt die Zeitstempel der bestehenden Whisper-Wörter an einen korrigierten Text an.
pub fn align_words_with_edited_text(
    orig_segments: &[TranscriptSegment],
    new_text: &str,
    total_duration: f64,
) -> Vec<TranscriptSegment> {
    let new_words_raw: Vec<&str> = new_text.split_whitespace().collect();
    if new_words_raw.is_empty() {
        return Vec::new();
    }

    let mut orig_words: Vec<WordSegment> = Vec::new();
    for seg in orig_segments {
        for w in &seg.words {
            if !w.word.trim().is_empty() {
                orig_words.push(w.clone());
            }
        }
    }

    if orig_words.is_empty() {
        let step = (total_duration / new_words_raw.len().max(1) as f64).min(0.6);
        let result_words: Vec<WordSegment> = new_words_raw
            .iter()
            .enumerate()
            .map(|(i, nw)| {
                let st = ((i as f64 * step) * 100.0).round() / 100.0;
                let et = ((st + step * 0.9) * 100.0).round() / 100.0;
                WordSegment {
                    word: (*nw).to_string(),
                    start: st,
                    end: et,
                    probability: 1.0,
                }
            })
            .collect();
        return vec![TranscriptSegment {
            start: 0.0,
            end: total_duration,
            text: new_text.to_string(),
            words: result_words,
        }];
    }

    if new_words_raw.len() == orig_words.len() {
        let result_words: Vec<WordSegment> = new_words_raw
            .iter()
            .enumerate()
            .map(|(i, nw)| WordSegment {
                word: (*nw).to_string(),
                start: orig_words[i].start,
                end: orig_words[i].end.max(orig_words[i].start + 0.08),
                probability: 1.0,
            })
            .collect();
        return vec![TranscriptSegment {
            start: result_words.first().map(|w| w.start).unwrap_or(0.0),
            end: result_words.last().map(|w| w.end).unwrap_or(total_duration),
            text: new_text.to_string(),
            words: result_words,
        }];
    }

    let orig_tokens: Vec<String> = orig_words.iter().map(|w| normalize_token(&w.word)).collect();
    let new_tokens: Vec<String> = new_words_raw.iter().map(|w| normalize_token(w)).collect();

    // LCS-Matching für exakte Token-Zuordnung
    let m = orig_tokens.len();
    let n = new_tokens.len();
    let mut dp = vec![vec![0usize; n + 1]; m + 1];
    for i in (0..m).rev() {
        for j in (0..n).rev() {
            if orig_tokens[i] == new_tokens[j] {
                dp[i][j] = dp[i + 1][j + 1] + 1;
            } else {
                dp[i][j] = dp[i + 1][j].max(dp[i][j + 1]);
            }
        }
    }

    let mut result_words: Vec<Option<WordSegment>> = vec![None; n];
    let (mut i, mut j) = (0, 0);
    while i < m && j < n {
        if orig_tokens[i] == new_tokens[j] {
            result_words[j] = Some(WordSegment {
                word: new_words_raw[j].to_string(),
                start: orig_words[i].start,
                end: orig_words[i].end.max(orig_words[i].start + 0.08),
                probability: 1.0,
            });
            i += 1;
            j += 1;
        } else if dp[i + 1][j] >= dp[i][j + 1] {
            i += 1;
        } else {
            j += 1;
        }
    }

    // Führende Lücke interpolieren
    if let Some(first_matched) = result_words.iter().position(|w| w.is_some()) {
        if first_matched > 0 {
            let end_t = result_words[first_matched].as_ref().unwrap().start;
            let start_t = (end_t - (first_matched as f64 * 0.4)).max(0.0);
            let step = (end_t - start_t) / first_matched as f64;
            for k in 0..first_matched {
                result_words[k] = Some(WordSegment {
                    word: new_words_raw[k].to_string(),
                    start: ((start_t + k as f64 * step) * 100.0).round() / 100.0,
                    end: ((start_t + (k + 1) as f64 * step) * 100.0).round() / 100.0,
                    probability: 1.0,
                });
            }
        }
    }

    // Mittlere und abschließende Lücken interpolieren
    let len = result_words.len();
    for k in 0..len {
        if result_words[k].is_none() {
            let mut prev_idx = k as isize - 1;
            while prev_idx >= 0 && result_words[prev_idx as usize].is_none() {
                prev_idx -= 1;
            }
            let mut next_idx = k + 1;
            while next_idx < len && result_words[next_idx].is_none() {
                next_idx += 1;
            }

            let start_t = if prev_idx >= 0 {
                result_words[prev_idx as usize].as_ref().unwrap().end
            } else {
                0.0
            };
            let mut end_t = if next_idx < len {
                result_words[next_idx].as_ref().unwrap().start
            } else {
                start_t + 2.0
            };
            if end_t <= start_t {
                end_t = start_t + 0.45 * (next_idx as isize - prev_idx) as f64;
            }

            let gap_count = (next_idx as isize - (prev_idx + 1)).max(1) as usize;
            let step = (end_t - start_t) / gap_count as f64;
            for gap_i in 0..gap_count {
                let cur_idx = (prev_idx + 1) as usize + gap_i;
                result_words[cur_idx] = Some(WordSegment {
                    word: new_words_raw[cur_idx].to_string(),
                    start: ((start_t + gap_i as f64 * step) * 100.0).round() / 100.0,
                    end: ((start_t + (gap_i + 1) as f64 * step) * 100.0).round() / 100.0,
                    probability: 1.0,
                });
            }
        }
    }

    let final_words: Vec<WordSegment> = result_words.into_iter().flatten().collect();
    let start_clip = final_words.first().map(|w| w.start).unwrap_or(0.0);
    let end_clip = final_words.last().map(|w| w.end).unwrap_or(total_duration);

    vec![TranscriptSegment {
        start: start_clip,
        end: end_clip,
        text: new_text.to_string(),
        words: final_words,
    }]
}

/// Erstellt eine .ass Untertiteldatei im viralen Karaoke-Highlight-Stil.
pub fn generate_ass(
    segments: &[TranscriptSegment],
    output_ass_path: &Path,
    position: &str,
    style_preset: &str,
) -> Result<PathBuf, String> {
    let cfg = load_config();
    let sub_val = cfg.video.extra.get("subtitles");
    let font_name = sub_val
        .and_then(|v| v.get("font_name"))
        .and_then(|v| v.as_str())
        .unwrap_or("Arial Black");
    let font_size = sub_val
        .and_then(|v| v.get("font_size"))
        .and_then(|v| v.as_u64())
        .unwrap_or(24);
    let default_hl = sub_val
        .and_then(|v| v.get("highlight_color"))
        .and_then(|v| v.as_str())
        .unwrap_or("&H0000FFFF");
    let default_prim = sub_val
        .and_then(|v| v.get("primary_color"))
        .and_then(|v| v.as_str())
        .unwrap_or("&H00FFFFFF");
    let outline_color = sub_val
        .and_then(|v| v.get("outline_color"))
        .and_then(|v| v.as_str())
        .unwrap_or("&H00000000");
    let outline_width = sub_val
        .and_then(|v| v.get("outline_width"))
        .and_then(|v| v.as_u64())
        .unwrap_or(3);
    let max_words = sub_val
        .and_then(|v| v.get("max_words_per_segment"))
        .and_then(|v| v.as_u64())
        .unwrap_or(3)
        .max(1) as usize;

    let (hl_color, prim_color) = match style_preset.to_lowercase().as_str() {
        "yellow" => ("&H0000FFFF", "&H00FFFFFF"),
        "cyan" => ("&H00FFFF00", "&H00FFFFFF"),
        "neon" => ("&H0000FF00", "&H00FFFFFF"),
        "white" => ("&H00FFFFFF", "&H00CCCCCC"),
        _ => (default_hl, default_prim),
    };

    let mut all_words: Vec<WordSegment> = Vec::new();
    for seg in segments {
        for w in &seg.words {
            if !w.word.trim().is_empty() {
                all_words.push(w.clone());
            }
        }
    }

    if all_words.is_empty() {
        for seg in segments {
            if !seg.text.trim().is_empty() {
                all_words.push(WordSegment {
                    word: seg.text.clone(),
                    start: seg.start,
                    end: seg.end,
                    probability: 1.0,
                });
            }
        }
    }

    let margin_v = match position.to_lowercase().as_str() {
        "center" => 820,
        "top" => 1450,
        _ => 380,
    };

    let font = if font_name == "Montserrat-Black" || font_name == "TheBoldFont" {
        "Arial Black"
    } else {
        font_name
    };

    let scaled_font_size = (font_size as f64) * 2.8;
    let scaled_outline = outline_width * 2;

    let mut out = format!(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font},{scaled_font_size:.1},{prim_color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,{scaled_outline},2,2,40,40,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n",
    );

    for chunk in all_words.chunks(max_words) {
        for (active_idx, target_word) in chunk.iter().enumerate() {
            let start_t = format_ass_time(target_word.start);
            let end_t = format_ass_time(target_word.end);
            let mut line_parts = Vec::with_capacity(chunk.len());
            for (idx, w) in chunk.iter().enumerate() {
                let text = w.word.to_uppercase();
                if idx == active_idx {
                    line_parts.push(format!("{{\\c{hl_color}\\b1}}{text}{{\\r}}"));
                } else {
                    line_parts.push(format!("{{\\c{prim_color}}}{text}"));
                }
            }
            let display_line = line_parts.join(" ");
            out.push_str(&format!(
                "Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{display_line}\n"
            ));
        }
    }

    if let Some(parent) = output_ass_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(output_ass_path, out).map_err(|e| e.to_string())?;
    Ok(output_ass_path.to_path_buf())
}
