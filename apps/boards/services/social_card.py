"""Generate share-card images for public board URLs."""

from __future__ import annotations

from io import BytesIO
import re

from PIL import Image, ImageDraw, ImageFont

from apps.schools.services import safe_accent_color


WIDTH = 1200
HEIGHT = 630
INK = "#171717"
PAPER = "#fbfaf7"
WHITE = "#ffffff"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Use Pillow's bundled scalable fallback so the card works in slim containers."""
    del bold  # Pillow's bundled font is intentionally used for deterministic deployment.
    return ImageFont.load_default(size=size)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, *, max_size: int, min_size: int, max_width: int, bold: bool = False):
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold=bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(min_size, bold=bold)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    words = text.split() or ["THIS BOARD IS OPEN."]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return lines

    lines = lines[:max_lines]
    last = lines[-1]
    while draw.textlength(f"{last}…", font=font) > max_width and last:
        shortened = re.sub(r"\s+\S+$", "", last).strip()
        last = shortened if shortened != last else last[:-1]
    lines[-1] = f"{last or words[0]}…"
    return lines


def render_board_social_card(board) -> bytes:
    """Render a 1200x630 PNG suitable for Open Graph and X link previews."""
    accent = safe_accent_color(board.entity.accent_color)
    image = Image.new("RGB", (WIDTH, HEIGHT), accent)
    draw = ImageDraw.Draw(image)

    # Treat the share card like a rivalry placard: the school accent owns the
    # frame, while the message gets the quiet center field and the largest type.
    draw.rectangle((0, 0, WIDTH, 132), fill=accent)
    draw.rectangle((0, HEIGHT - 94, WIDTH, HEIGHT), fill=accent)
    draw.rectangle((48, 132, WIDTH - 48, HEIGHT - 94), fill=PAPER)

    small = _font(20)
    label = _font(22, bold=True)
    school_name = board.entity.name.upper()
    school = _fit_font(draw, school_name, max_size=76, min_size=42, max_width=790, bold=True)
    message_font = _font(80, bold=True)
    quote = _font(126, bold=True)
    footer = _font(20)
    if getattr(board, "bidding_enabled", True):
        cta_price = getattr(board, "next_takeover_dollars", board.current_amount_dollars)
        cta = f"TAKE THE BOARD FOR ${cta_price:.0f}"
    else:
        cta = "TAKEOVERS PAUSED"
    cta_font = _fit_font(draw, cta, max_size=26, min_size=18, max_width=370, bold=True)
    message_x = 148
    opening_quote_x = message_x - draw.textlength("“", font=quote) - 10

    draw.text((78, 20), "TAKE THE BOARD", font=small, fill=WHITE)
    draw.text((78, 48), school_name, font=school, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    draw.text((1122, 42), "LIVE FAN BOARD", font=label, fill=WHITE, anchor="ra")
    draw.text((78, 159), "THE MESSAGE", font=small, fill=accent)
    draw.text((opening_quote_x, 191), "“", font=quote, fill=accent)

    message_lines = _wrap_text(draw, board.current_message, message_font, 920)
    message_y = 234
    for line in message_lines:
        draw.text((message_x, message_y), line, font=message_font, fill=INK, stroke_width=1, stroke_fill=INK)
        message_y += 88
    last_line = message_lines[-1]
    closing_quote_x = message_x + draw.textlength(last_line, font=message_font) + 18
    draw.text((closing_quote_x, message_y - 102), "”", font=quote, fill=accent)

    draw.line((78, 508, 1122, 508), fill="#ded9cf", width=2)
    if board.current_controller:
        controller = f"OWNED BY {board.current_controller.display_name.upper()}"
    else:
        controller = "OPEN FOR THE FIRST TAKEOVER"
    draw.text((78, 546), controller, font=footer, fill=WHITE)
    draw.rounded_rectangle((720, 538, 1122, 590), radius=8, fill=WHITE)
    draw.text((921, 564), cta, font=cta_font, fill=accent, anchor="mm", stroke_width=1, stroke_fill=accent)
    draw.text((78, 580), "A public message. A live rivalry. TAKE YOUR SHOT.", font=footer, fill=WHITE)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
