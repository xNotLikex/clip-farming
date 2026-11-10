import os
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Optional
from src.config import FONTS_DIR

def create_tiktok_sticker(
    text: str,
    output_png_path: Path,
    max_width: int = 900,
    bg_color=(255, 255, 255, 255),
    text_color=(15, 15, 15, 255),
    font_size: int = 54
) -> Path:
    """
    Erstellt ein pixelgenaues, weisses TikTok-Sticker-Badge mit abgerundeten Ecken
    und fettem Text - genau wie im hochgeladenen Screenshot!
    """
    # System-Schriftart suchen (Arial, Segoe UI oder Montserrat)
    font = None
    font_candidates = [
        "C:/Windows/Fonts/ariblk.ttf",       # Arial Black
        "C:/Windows/Fonts/seguiemj.ttf",      # Segoe UI
        "C:/Windows/Fonts/arialbd.ttf",      # Arial Bold
        "C:/Windows/Fonts/arial.ttf"
    ]
    for fc in font_candidates:
        if os.path.exists(fc):
            try:
                font = ImageFont.truetype(fc, font_size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    # Text umbrechen, falls er zu lang ist
    words = text.strip().split()
    lines = []
    curr_line = []
    
    # Dummy Draw zum Messen
    dummy_img = Image.new("RGBA", (1, 1))
    draw_test = ImageDraw.Draw(dummy_img)

    for word in words:
        test_line = " ".join(curr_line + [word])
        bbox = draw_test.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) > (max_width - 100) and curr_line:
            lines.append(" ".join(curr_line))
            curr_line = [word]
        else:
            curr_line.append(word)
    if curr_line:
        lines.append(" ".join(curr_line))

    # Maximale Breite und Gesamthöhe ermitteln
    line_bboxes = [draw_test.textbbox((0, 0), l, font=font) for l in lines]
    max_text_w = max(b[2] - b[0] for b in line_bboxes)
    line_h = max(b[3] - b[1] for b in line_bboxes) + 16
    total_text_h = line_h * len(lines)

    pad_x = 45
    pad_y = 28
    tail_h = 26
    tail_w = 44
    badge_w = max_text_w + pad_x * 2
    box_h = total_text_h + pad_y * 2
    total_h = box_h + tail_h

    # Bild mit transparentem Hintergrund erstellen
    img = Image.new("RGBA", (badge_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Abgerundetes weißes Rechteck zeichnen
    radius = 32
    draw.rounded_rectangle(
        [(0, 0), (badge_w, box_h)],
        radius=radius,
        fill=bg_color
    )

    # Sprechblasen-Spitze (TikTok Speech Bubble Hook) unten in der Mitte
    cx = badge_w // 2
    draw.polygon(
        [
            (cx - tail_w // 2, box_h - 2),
            (cx + tail_w // 2, box_h - 2),
            (cx, box_h + tail_h)
        ],
        fill=bg_color
    )

    # Text zentriert zeichnen
    curr_y = pad_y
    for l, bbox in zip(lines, line_bboxes):
        lw = bbox[2] - bbox[0]
        curr_x = (badge_w - lw) // 2
        draw.text((curr_x, curr_y), l, font=font, fill=text_color)
        curr_y += line_h

    img.save(str(output_png_path), "PNG")
    return output_png_path

if __name__ == "__main__":
    out = Path("data/sample_sticker.png")
    create_tiktok_sticker("Gstastys ki hittet double mace", out)
    print("Sticker erstellt:", out.absolute())
