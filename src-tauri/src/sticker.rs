use ab_glyph::{Font, FontRef, PxScale, ScaleFont};
use image::{Rgba, RgbaImage};
use std::fs;
use std::path::{Path, PathBuf};

fn load_system_font() -> Result<Vec<u8>, String> {
    let candidates = [
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ];
    for p in candidates {
        if Path::new(p).exists() {
            if let Ok(bytes) = fs::read(p) {
                return Ok(bytes);
            }
        }
    }
    Err("Keine System-Schriftart für Sticker gefunden.".to_string())
}

fn measure_text_width(font: &FontRef<'_>, scale: PxScale, text: &str) -> f32 {
    let scaled = font.as_scaled(scale);
    let mut width = 0.0f32;
    let mut prev = None;
    for ch in text.chars() {
        let id = font.glyph_id(ch);
        if let Some(p) = prev {
            width += scaled.kern(p, id);
        }
        width += scaled.h_advance(id);
        prev = Some(id);
    }
    width
}

fn draw_text(
    img: &mut RgbaImage,
    font: &FontRef<'_>,
    scale: PxScale,
    start_x: f32,
    baseline_y: f32,
    text: &str,
    color: Rgba<u8>,
) {
    let scaled = font.as_scaled(scale);
    let mut cursor_x = start_x;
    let mut prev = None;
    let img_w = img.width() as i32;
    let img_h = img.height() as i32;

    for ch in text.chars() {
        let id = font.glyph_id(ch);
        if let Some(p) = prev {
            cursor_x += scaled.kern(p, id);
        }
        let glyph = id.with_scale_and_position(scale, ab_glyph::point(cursor_x, baseline_y));
        if let Some(outlined) = font.outline_glyph(glyph) {
            let bounds = outlined.px_bounds();
            outlined.draw(|gx, gy, coverage| {
                let px = bounds.min.x as i32 + gx as i32;
                let py = bounds.min.y as i32 + gy as i32;
                if px >= 0 && px < img_w && py >= 0 && py < img_h && coverage > 0.01 {
                    let dst = img.get_pixel_mut(px as u32, py as u32);
                    let a = coverage.clamp(0.0, 1.0);
                    let inv = 1.0 - a;
                    dst[0] = (color[0] as f32 * a + dst[0] as f32 * inv) as u8;
                    dst[1] = (color[1] as f32 * a + dst[1] as f32 * inv) as u8;
                    dst[2] = (color[2] as f32 * a + dst[2] as f32 * inv) as u8;
                    dst[3] = ((color[3] as f32 * a).max(dst[3] as f32)) as u8;
                }
            });
        }
        cursor_x += scaled.h_advance(id);
        prev = Some(id);
    }
}

fn fill_rounded_rect(img: &mut RgbaImage, w: u32, h: u32, radius: i32, color: Rgba<u8>) {
    let r = radius.min(w as i32 / 2).min(h as i32 / 2);
    let r_sq = (r * r) as f32;
    for y in 0..h as i32 {
        for x in 0..w as i32 {
            let inside = if x < r && y < r {
                let dx = (r - 1 - x) as f32;
                let dy = (r - 1 - y) as f32;
                dx * dx + dy * dy <= r_sq
            } else if x >= w as i32 - r && y < r {
                let dx = (x - (w as i32 - r)) as f32;
                let dy = (r - 1 - y) as f32;
                dx * dx + dy * dy <= r_sq
            } else if x < r && y >= h as i32 - r {
                let dx = (r - 1 - x) as f32;
                let dy = (y - (h as i32 - r)) as f32;
                dx * dx + dy * dy <= r_sq
            } else if x >= w as i32 - r && y >= h as i32 - r {
                let dx = (x - (w as i32 - r)) as f32;
                let dy = (y - (h as i32 - r)) as f32;
                dx * dx + dy * dy <= r_sq
            } else {
                true
            };
            if inside {
                img.put_pixel(x as u32, y as u32, color);
            }
        }
    }
}

/// Erzeugt ein weißes TikTok-Sticker-Badge mit abgerundeten Ecken, Sprechblasen-Spitze und fettem Text.
pub fn create_tiktok_sticker(text: &str, output_png_path: &Path) -> Result<PathBuf, String> {
    let font_bytes = load_system_font()?;
    let font = FontRef::try_from_slice(&font_bytes).map_err(|e| format!("Font error: {}", e))?;

    let font_size = 54.0f32;
    let scale = PxScale::from(font_size);
    let max_width = 900.0f32;

    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return Err("Sticker-Text ist leer".to_string());
    }

    let mut lines: Vec<String> = Vec::new();
    let mut curr: Vec<&str> = Vec::new();
    for word in words {
        let mut candidate = curr.clone();
        candidate.push(word);
        let test_line = candidate.join(" ");
        if measure_text_width(&font, scale, &test_line) > (max_width - 100.0) && !curr.is_empty() {
            lines.push(curr.join(" "));
            curr = vec![word];
        } else {
            curr.push(word);
        }
    }
    if !curr.is_empty() {
        lines.push(curr.join(" "));
    }

    let line_widths: Vec<f32> = lines.iter().map(|l| measure_text_width(&font, scale, l)).collect();
    let max_text_w = line_widths.iter().cloned().fold(120.0f32, f32::max).ceil() as u32;
    let scaled = font.as_scaled(scale);
    let line_h = (scaled.ascent() - scaled.descent()).ceil() as u32 + 16;
    let total_text_h = line_h * (lines.len() as u32);

    let pad_x = 45u32;
    let pad_y = 28u32;
    let tail_h = 26u32;
    let tail_w = 44u32;
    let badge_w = max_text_w + pad_x * 2;
    let box_h = total_text_h + pad_y * 2;
    let total_h = box_h + tail_h;

    let bg_color = Rgba([255, 255, 255, 255]);
    let text_color = Rgba([15, 15, 15, 255]);

    let mut img = RgbaImage::from_pixel(badge_w, total_h, Rgba([0, 0, 0, 0]));
    fill_rounded_rect(&mut img, badge_w, box_h, 32, bg_color);

    // Sprechblasen-Spitze unten in der Mitte
    let cx = (badge_w / 2) as f32;
    let half_tw = (tail_w / 2) as f32;
    for y in (box_h.saturating_sub(2))..total_h {
        let progress = (y as f32 - (box_h as f32 - 2.0)) / (tail_h as f32 + 2.0);
        let half_span = (half_tw * (1.0 - progress)).max(0.0);
        let x0 = (cx - half_span).floor().max(0.0) as u32;
        let x1 = (cx + half_span).ceil().min((badge_w - 1) as f32) as u32;
        for x in x0..=x1 {
            img.put_pixel(x, y, bg_color);
        }
    }

    let mut curr_y = pad_y as f32 + scaled.ascent();
    for (line, lw) in lines.iter().zip(line_widths.iter()) {
        let start_x = ((badge_w as f32) - lw) / 2.0;
        draw_text(&mut img, &font, scale, start_x, curr_y, line, text_color);
        curr_y += line_h as f32;
    }

    if let Some(parent) = output_png_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    img.save(output_png_path)
        .map_err(|e| format!("Fehler beim Speichern des Stickers: {}", e))?;
    Ok(output_png_path.to_path_buf())
}
