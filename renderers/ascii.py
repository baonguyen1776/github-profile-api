from __future__ import annotations

import math
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from renderers.shared import MONO


FONT_PATH = Path(__file__).resolve().parents[1] / "assets/fonts/NotoSans-Bold.ttf"
NAME_MAX_WIDTH = 515
NAME_LINE_HEIGHT = 74
NAME_LEFT = 54
NAME_TOP = 174
NAME_LINE_GAP = 90
CELL_WIDTH = 2.8
CELL_HEIGHT = 3.4
GLYPH_SIZE = 4.8


@lru_cache(maxsize=1)
def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=192)


def _split_name(name: str) -> list[str]:
    words = name.split()
    if len(words) < 2:
        return [name]
    # Preserve the original two-line word grouping while measuring glyphs below for sizing.
    index = min(
        range(1, len(words)),
        key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))),
    )
    return [" ".join(words[:index]), " ".join(words[index:])]


def _name_masks(name: str) -> list[Image.Image]:
    name = unicodedata.normalize("NFC", " ".join(name.split())) or "Developer"
    font = _font()
    lines = _split_name(name)
    boxes = [font.getbbox(line) for line in lines]
    top = min(box[1] for box in boxes)
    bottom = max(box[3] for box in boxes)
    source_height = max(1, math.ceil(bottom - top))
    widest = max(max(1, math.ceil(box[2] - box[0])) for box in boxes)
    # One scale for both lines keeps letter proportions and line sizes consistent.
    scale = min(NAME_MAX_WIDTH / widest, NAME_LINE_HEIGHT / source_height)
    target_height = max(1, round(source_height * scale))
    masks: list[Image.Image] = []
    for line, box in zip(lines, boxes):
        source_width = max(1, math.ceil(box[2] - box[0]))
        mask = Image.new("L", (source_width, source_height))
        ImageDraw.Draw(mask).text((-box[0], -top), line, font=font, fill=255)
        width = max(1, min(NAME_MAX_WIDTH, round(source_width * scale)))
        masks.append(mask.resize((width, target_height), Image.Resampling.LANCZOS))
    return masks


def render_ascii_name(name: str, color: str) -> str:
    """Sample the letter mask into tightly packed ASCII cells with no pattern clipping."""
    parts = [
        f'<g fill="{color}" font-family="{MONO}" font-size="{GLYPH_SIZE}" '
        'font-weight="700" aria-hidden="true">'
    ]
    for line_index, mask in enumerate(_name_masks(name)):
        columns = max(1, math.ceil(mask.width / CELL_WIDTH))
        rows = max(1, math.ceil(mask.height / CELL_HEIGHT))
        # BOX averages each cell's coverage, keeping fine accents and antialiased edges.
        coverage = mask.resize((columns, rows), Image.Resampling.BOX)
        step_x = mask.width / columns
        step_y = mask.height / rows
        for row in range(rows):
            for column in range(columns):
                value = coverage.getpixel((column, row))
                if not isinstance(value, int) or value < 40:
                    continue
                char = "#" if value >= 170 else ("+" if value >= 85 else ":")
                opacity = 0.72 + value / 255 * 0.28
                x = NAME_LEFT + column * step_x
                y = NAME_TOP + line_index * NAME_LINE_GAP + (row + 1) * step_y
                parts.append(f'<text x="{x:.2f}" y="{y:.2f}" opacity="{opacity:.2f}">{char}</text>')
    parts.append('</g>')
    return "".join(parts)
