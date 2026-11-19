from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent.parent / "fonts" / "Inter.ttf"
CELL, GAP, PAD, LABEL = 300, 14, 20, 44
BG = (14, 15, 19)
CARD = (28, 30, 38)


def _font(size: int):
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default()


def _fit(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def grid(images: list[bytes], labels: list[str], start: int = 1, cols: int = 3, badges: list[str] | None = None) -> bytes:
    n = len(images)
    rows = max(1, -(-n // cols))
    w = PAD * 2 + cols * CELL + (cols - 1) * GAP
    h = PAD * 2 + rows * (CELL + LABEL) + (rows - 1) * GAP
    canvas = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(canvas)
    f_num, f_lab = _font(34), _font(24)
    for i, (raw, label) in enumerate(zip(images, labels)):
        x = PAD + (i % cols) * (CELL + GAP)
        y = PAD + (i // cols) * (CELL + LABEL + GAP)
        draw.rounded_rectangle((x, y, x + CELL, y + CELL + LABEL), 22, fill=CARD)
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA").resize((CELL, CELL), Image.LANCZOS)
            mask = Image.new("L", (CELL, CELL), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, CELL, CELL), 22, fill=255)
            canvas.paste(im, (x, y), mask)
        except Exception:
            pass
        num = str(start + i)
        bw = max(56, int(draw.textlength(num, font=f_num)) + 28)
        draw.rounded_rectangle((x + 12, y + 12, x + 12 + bw, y + 64), 26, fill=(0, 0, 0, 170))
        draw.text((x + 12 + bw / 2, y + 38), num, font=f_num, fill=(255, 255, 255), anchor="mm")
        draw.text((x + CELL / 2, y + CELL + LABEL / 2), _fit(draw, label, f_lab, CELL - 20), font=f_lab,
                  fill=(220, 224, 235), anchor="mm")
        if badges and i < len(badges) and badges[i]:
            tw = int(draw.textlength(badges[i], font=f_lab)) + 24
            draw.rounded_rectangle((x + CELL - 12 - tw, y + 14, x + CELL - 12, y + 58), 22, fill=(255, 255, 255))
            draw.text((x + CELL - 12 - tw / 2, y + 36), badges[i], font=f_lab, fill=(20, 22, 28), anchor="mm")
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def pages(images: list[bytes], labels: list[str], per: int = 9):
    for i in range(0, len(images), per):
        yield grid(images[i:i + per], labels[i:i + per], start=i + 1)
