from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from player_card_generator.models import CardPayload

_RESAMPLING = getattr(Image, "Resampling", Image)
HEIGHT_ICON_PATH = Path(__file__).resolve().parent / "assets" / "height.png"

DEFAULT_PRIMARY = (200, 16, 46, 255)
DEFAULT_SECONDARY = (0, 58, 143, 255)
DEFAULT_ACCENT = (242, 201, 76, 255)
BG_DARK = (6, 10, 16, 255)
PANEL_BG = (8, 14, 24, 228)
WHITE = (248, 250, 252, 255)
MUTED = (202, 210, 222, 255)
BLACK = (0, 0, 0, 255)
GREEN_BADGE = (67, 145, 84, 255)


def _font_candidates(weight: str) -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    fonts_dir = root / "apps" / "launcher" / "Scouting Monitoring" / "assets" / "fonts"
    if weight == "black":
        return [fonts_dir / "Lato-Black.ttf", fonts_dir / "Lato-Bold.ttf"]
    if weight == "bold":
        return [fonts_dir / "Lato-Bold.ttf", fonts_dir / "Lato-Black.ttf"]
    return [fonts_dir / "Lato-Regular.ttf", fonts_dir / "Lato-Light.ttf"]


def _load_font(size: int, weight: str = "regular") -> ImageFont.ImageFont:
    for path in _font_candidates(weight):
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
    *,
    shadow: bool = False,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x0, y0, x1, y1 = box
    x = x0 + (x1 - x0 - text_w) // 2 - bbox[0]
    y = y0 + (y1 - y0 - text_h) // 2 - bbox[1]
    if shadow:
        draw.text((x + 2, y + 3), text, fill=(0, 0, 0, 125), font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _truncate_text_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    trimmed = text
    while len(trimmed) > 1:
        trimmed = trimmed[:-1]
        candidate = f"{trimmed}..."
        if _text_size(draw, candidate, font)[0] <= max_width:
            return candidate
    return "..."


def _open_rgba(image_bytes: Optional[bytes]) -> Optional[Image.Image]:
    if not image_bytes:
        return None
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            return image.convert("RGBA")
    except Exception:
        return None


def _hex_to_rgba(color_hex: str, fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    raw = str(color_hex or "").strip().lstrip("#")
    if len(raw) == 8:
        raw = raw[:6]
    if len(raw) != 6:
        return fallback
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 255)
    except Exception:
        return fallback


def _blend(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int], amount: float) -> Tuple[int, int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return (
        int(a[0] * (1.0 - amount) + b[0] * amount),
        int(a[1] * (1.0 - amount) + b[1] * amount),
        int(a[2] * (1.0 - amount) + b[2] * amount),
        int(a[3] * (1.0 - amount) + b[3] * amount),
    )


def _luminance(color: Tuple[int, int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _extract_logo_palette(logo_bytes: Optional[bytes]) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    logo = _open_rgba(logo_bytes)
    if logo is None:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_ACCENT

    small = logo.resize((64, 64), _RESAMPLING.LANCZOS).convert("RGBA")
    buckets: dict[Tuple[int, int, int], int] = {}
    pixels = small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata()
    for r, g, b, a in pixels:
        if a < 90 or max(r, g, b) > 244 or max(r, g, b) < 20:
            continue
        saturation = max(r, g, b) - min(r, g, b)
        if saturation < 26:
            continue
        key = (int(round(r / 24) * 24), int(round(g / 24) * 24), int(round(b / 24) * 24))
        buckets[key] = buckets.get(key, 0) + 1

    if not buckets:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_ACCENT

    ranked = sorted(buckets.items(), key=lambda item: (item[1] * (max(item[0]) - min(item[0])), item[1]), reverse=True)
    primary_rgb = ranked[0][0]
    primary = (primary_rgb[0], primary_rgb[1], primary_rgb[2], 255)
    secondary = DEFAULT_SECONDARY
    for rgb, _count in ranked[1:]:
        candidate = (rgb[0], rgb[1], rgb[2], 255)
        if abs(_luminance(candidate) - _luminance(primary)) > 35:
            secondary = candidate
            break
    accent = _blend(primary, DEFAULT_ACCENT, 0.35)
    return primary, secondary, accent


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _polygon_mask(size: Tuple[int, int], points: list[Tuple[int, int]]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(points, fill=255)
    return mask


def _masked_color_layer(
    size: Tuple[int, int],
    color: Tuple[int, int, int, int],
    mask: Image.Image,
    alpha: int,
) -> Image.Image:
    layer = Image.new("RGBA", size, (color[0], color[1], color[2], 0))
    layer.putalpha(mask.point(lambda value: int(value * alpha / 255)))
    return layer


def _trim_transparent(image: Image.Image, *, padding: int = 0) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image
    x0, y0, x1, y1 = bbox
    return image.crop((max(0, x0 - padding), max(0, y0 - padding), min(image.width, x1 + padding), min(image.height, y1 + padding)))


def _paste_contain(target: Image.Image, image: Optional[Image.Image], box: Tuple[int, int, int, int], *, rounded: int = 0) -> None:
    if image is None:
        return
    x0, y0, x1, y1 = box
    fitted = ImageOps.contain(image, (max(1, x1 - x0), max(1, y1 - y0)), method=_RESAMPLING.LANCZOS)
    px = x0 + (x1 - x0 - fitted.width) // 2
    py = y0 + (y1 - y0 - fitted.height) // 2
    if rounded:
        mask = _rounded_mask(fitted.size, rounded)
        target.paste(fitted, (px, py), mask)
    else:
        target.paste(fitted, (px, py), fitted)


def _paste_cover(target: Image.Image, image: Optional[Image.Image], box: Tuple[int, int, int, int]) -> None:
    if image is None:
        return
    x0, y0, x1, y1 = box
    box_w, box_h = max(1, x1 - x0), max(1, y1 - y0)
    scale = max(box_w / image.width, box_h / image.height)
    resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), _RESAMPLING.LANCZOS)
    px = x0 + (box_w - resized.width) // 2
    py = y0 + (box_h - resized.height) // 2
    target.paste(resized, (px, py), resized)


def _draw_text(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int], *, shadow: bool = True) -> None:
    x, y = xy
    if shadow:
        draw.text((x + 2, y + 3), text, fill=(0, 0, 0, 125), font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, weight: str) -> ImageFont.ImageFont:
    size = start_size
    while size > 16:
        font = _load_font(size, weight)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
        size -= 2
    return _load_font(size, weight)


def _draw_halftone(card: Image.Image, *, width: int, height: int, primary: Tuple[int, int, int, int], secondary: Tuple[int, int, int, int]) -> None:
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    spacing = max(12, width // 48)
    for y in range(int(height * 0.52), int(height * 0.93), spacing):
        for x in range(18, int(width * 0.34), spacing):
            fade = 1.0 - ((x / max(width * 0.34, 1)) * 0.25 + ((height - y) / max(height * 0.41, 1)) * 0.45)
            radius = max(1, int(spacing * 0.17 * max(0.35, fade)))
            alpha = int(68 * max(0.0, min(1.0, fade)))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(primary[0], primary[1], primary[2], alpha))
    for y in range(int(height * 0.36), int(height * 0.78), spacing):
        for x in range(int(width * 0.72), width - 22, spacing):
            fade = 1.0 - (((x - width * 0.72) / max(width * 0.28, 1)) * 0.55 + ((y - height * 0.36) / max(height * 0.42, 1)) * 0.20)
            radius = max(1, int(spacing * 0.18 * max(0.35, fade)))
            alpha = int(72 * max(0.0, min(1.0, fade)))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(secondary[0], secondary[1], secondary[2], alpha))
    card.alpha_composite(overlay)


def _draw_neon_border(card: Image.Image, *, width: int, height: int, radius: int, primary: Tuple[int, int, int, int], secondary: Tuple[int, int, int, int]) -> None:
    for blur, line_w, alpha in ((18, 8, 80), (8, 5, 110), (0, 2, 230)):
        line = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(line)
        draw.rounded_rectangle((9, 9, width - 10, height - 10), radius=radius, outline=(255, 255, 255, alpha), width=line_w)
        if blur:
            line = line.filter(ImageFilter.GaussianBlur(blur))
        left = Image.new("RGBA", (width, height), (primary[0], primary[1], primary[2], 0))
        right = Image.new("RGBA", (width, height), (secondary[0], secondary[1], secondary[2], 0))
        left.putalpha(line.getchannel("A"))
        right.putalpha(line.getchannel("A"))
        card.alpha_composite(left.crop((0, 0, width // 2, height)), (0, 0))
        card.alpha_composite(right.crop((width // 2, 0, width, height)), (width // 2, 0))
    ImageDraw.Draw(card).rounded_rectangle((9, 9, width - 10, height - 10), radius=radius, outline=(255, 255, 255, 210), width=1)


def _draw_hexagon(target: Image.Image, box: Tuple[int, int, int, int], *, fill: Tuple[int, int, int, int], outline: Tuple[int, int, int, int], width: int = 3, glow: bool = True) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    points = [
        (x0 + w // 2, y0),
        (x1 - int(w * 0.12), y0 + int(h * 0.22)),
        (x1 - int(w * 0.12), y1 - int(h * 0.22)),
        (x0 + w // 2, y1),
        (x0 + int(w * 0.12), y1 - int(h * 0.22)),
        (x0 + int(w * 0.12), y0 + int(h * 0.22)),
    ]
    if glow:
        glow_layer = Image.new("RGBA", target.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_draw.polygon(points, outline=outline, width=max(6, width * 3))
        target.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(10)))
    draw = ImageDraw.Draw(target)
    draw.polygon(points, fill=fill)
    draw.line(points + [points[0]], fill=outline, width=width, joint="curve")


def _draw_panel(target: Image.Image, box: Tuple[int, int, int, int], *, outline: Tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", target.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=22, fill=PANEL_BG, outline=outline, width=2)
    target.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0)))


def _draw_simple_boot(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, fill: Tuple[int, int, int, int]) -> None:
    points = [
        (x + int(size * 0.12), y + int(size * 0.58)),
        (x + int(size * 0.42), y + int(size * 0.20)),
        (x + int(size * 0.62), y + int(size * 0.40)),
        (x + int(size * 0.85), y + int(size * 0.44)),
        (x + int(size * 0.76), y + int(size * 0.66)),
        (x + int(size * 0.32), y + int(size * 0.72)),
    ]
    draw.line(points + [points[0]], fill=fill, width=max(3, size // 18), joint="curve")
    draw.line((x + int(size * 0.44), y + int(size * 0.30), x + int(size * 0.58), y + int(size * 0.48)), fill=fill, width=max(2, size // 24))
    for i in range(4):
        cx = x + int(size * (0.34 + i * 0.10))
        draw.line((cx, y + int(size * 0.72), cx - 3, y + int(size * 0.80)), fill=fill, width=2)


def _draw_person_icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, fill: Tuple[int, int, int, int]) -> None:
    head = max(3, int(size * 0.18))
    cx = x + size // 2
    draw.ellipse((cx - head, y, cx + head, y + head * 2), fill=fill)
    body_top = y + int(size * 0.32)
    body_bottom = y + int(size * 0.72)
    body_w = max(4, int(size * 0.22))
    draw.rounded_rectangle((cx - body_w, body_top, cx + body_w, body_bottom), radius=max(2, body_w // 2), fill=fill)
    draw.line((cx - body_w, body_bottom, cx - int(size * 0.24), y + size), fill=fill, width=max(2, size // 10))
    draw.line((cx + body_w, body_bottom, cx + int(size * 0.24), y + size), fill=fill, width=max(2, size // 10))


@lru_cache(maxsize=1)
def _read_height_icon() -> Optional[Image.Image]:
    if not HEIGHT_ICON_PATH.exists():
        return None
    try:
        with Image.open(HEIGHT_ICON_PATH) as icon:
            return icon.convert("RGBA")
    except Exception:
        return None


def _build_icon_mask(icon: Image.Image) -> Image.Image:
    alpha = icon.split()[-1]
    if alpha.getextrema() != (255, 255):
        return alpha
    gray = ImageOps.grayscale(icon)
    corner = gray.getpixel((0, 0))
    diff = ImageChops.difference(gray, Image.new("L", gray.size, corner))
    mask = diff.point(lambda v: 255 if v > 16 else 0)
    return mask if mask.getbbox() else alpha


def _draw_height_icon(target: Image.Image, *, x: int, y: int, size: int, color: Tuple[int, int, int, int]) -> int:
    icon = _read_height_icon()
    if icon is None:
        draw = ImageDraw.Draw(target)
        draw.line((x + size // 2, y, x + size // 2, y + size), fill=color, width=max(2, size // 8))
        draw.line((x, y + size // 2, x + size, y + size // 2), fill=color, width=max(2, size // 8))
        return size

    mask = _build_icon_mask(icon)
    bbox = mask.getbbox()
    if bbox:
        icon = icon.crop(bbox)
    fitted = ImageOps.contain(icon, (size, size), method=_RESAMPLING.LANCZOS)
    mask = _build_icon_mask(fitted)
    tinted = Image.new("RGBA", fitted.size, color)
    tinted.putalpha(mask)
    target.paste(tinted, (x, y), tinted)
    return fitted.width


def _draw_player_placeholder(target: Image.Image, box: Tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(target)
    w, h = x1 - x0, y1 - y0
    cx = x0 + w // 2
    head_r = int(h * 0.09)
    head_y = y0 + int(h * 0.24)
    draw.ellipse((cx - head_r, head_y - head_r, cx + head_r, head_y + head_r), fill=(205, 211, 219, 255))
    body_w, body_h = int(w * 0.33), int(h * 0.46)
    draw.rounded_rectangle((cx - body_w // 2, head_y + head_r + 10, cx + body_w // 2, head_y + head_r + body_h), radius=18, fill=(205, 211, 219, 255))


def _draw_player_image(target: Image.Image, box: Tuple[int, int, int, int], image_bytes: Optional[bytes]) -> None:
    player = _open_rgba(image_bytes)
    if player is None:
        _draw_player_placeholder(target, box)
        return
    player = _trim_transparent(player, padding=4)
    _paste_contain(target, player, box)


def _split_player_name(name: str) -> Tuple[str, str]:
    parts = [part for part in (name or "").strip().split() if part]
    if len(parts) <= 1:
        return "", (parts[0] if parts else "PLAYER")
    return " ".join(parts[:-1]), parts[-1]


def render_player_card_png(payload: CardPayload, *, width: int = 900, height: int = 1200) -> bytes:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    margin = max(18, int(width * 0.025))
    card_w, card_h = width - margin * 2, height - margin * 2
    radius = max(38, int(width * 0.065))

    primary, secondary, accent = _extract_logo_palette(payload.team_logo_bytes)
    primary = _blend(primary, DEFAULT_PRIMARY, 0.25)
    secondary = _blend(secondary, DEFAULT_SECONDARY, 0.35)
    accent = _blend(accent, DEFAULT_ACCENT, 0.65)

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    base = Image.new("RGBA", (card_w, card_h), BG_DARK)
    draw = ImageDraw.Draw(base)
    for x in range(card_w):
        t = x / max(card_w - 1, 1)
        color = _blend(_blend(BG_DARK, primary, 0.34), _blend(BG_DARK, secondary, 0.46), t)
        draw.line((x, 0, x, card_h), fill=color)

    left_poly = [(0, 0), (int(card_w * 0.62), 0), (int(card_w * 0.36), card_h), (0, card_h)]
    right_poly = [(int(card_w * 0.58), 0), (card_w, 0), (card_w, card_h), (int(card_w * 0.42), card_h)]
    base.alpha_composite(_masked_color_layer((card_w, card_h), primary, _polygon_mask((card_w, card_h), left_poly), 92))
    base.alpha_composite(_masked_color_layer((card_w, card_h), secondary, _polygon_mask((card_w, card_h), right_poly), 96))

    glow = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((-180, 70, int(card_w * 0.72), int(card_h * 0.84)), fill=(primary[0], primary[1], primary[2], 72))
    glow_draw.ellipse((int(card_w * 0.38), 150, card_w + 150, int(card_h * 0.86)), fill=(secondary[0], secondary[1], secondary[2], 74))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(26)))

    logo = _open_rgba(payload.team_logo_bytes)
    if logo is not None:
        watermark = _trim_transparent(logo)
        watermark = ImageOps.contain(watermark, (int(card_w * 0.42), int(card_w * 0.42)), _RESAMPLING.LANCZOS)
        alpha = watermark.getchannel("A").point(lambda a: int(a * 0.11))
        watermark.putalpha(alpha)
        base.paste(watermark, (card_w // 2 - watermark.width // 2 + 30, int(card_h * 0.28)), watermark)

    card_mask = _rounded_mask((card_w, card_h), radius)
    card.paste(base, (0, 0), card_mask)
    _draw_halftone(card, width=card_w, height=card_h, primary=primary, secondary=secondary)
    _draw_neon_border(card, width=card_w, height=card_h, radius=radius, primary=primary, secondary=secondary)

    draw = ImageDraw.Draw(card)
    pad = int(card_w * 0.052)

    flag_w, flag_h = int(card_w * 0.14), int(card_w * 0.095)
    flag_box = (pad, pad + 14, pad + flag_w, pad + 14 + flag_h)
    flag_image = _open_rgba(payload.flag_image_bytes)
    if flag_image is not None:
        _paste_contain(card, flag_image, flag_box, rounded=7)
    else:
        draw.rounded_rectangle(flag_box, radius=10, fill=(255, 255, 255, 225), width=0)
        flag_label = (payload.flag_iso2 or "--").upper()
        flag_font = _load_font(20, "bold")
        _draw_centered_text(draw, flag_box, flag_label, flag_font, (90, 98, 112, 255))

    logo_size = int(card_w * 0.13)
    logo_x, logo_y = int(card_w * 0.64), pad - 2
    if logo is not None:
        _paste_contain(card, logo, (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size))
    else:
        draw.rounded_rectangle(
            (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size),
            radius=12,
            fill=(255, 255, 255, 238),
            outline=(255, 255, 255, 190),
            width=2,
        )
        logo_font = _load_font(max(16, logo_size // 5), "bold")
        logo_text = "LOGO"
        _draw_centered_text(draw, (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size), logo_text, logo_font, (78, 86, 99, 255))

    role_size = int(card_w * 0.14)
    role_box = (card_w - pad - role_size, pad + 2, card_w - pad, pad + 2 + role_size)
    _draw_hexagon(card, role_box, fill=(8, 14, 24, 235), outline=accent, width=3, glow=False)
    role_font = _fit_font(draw, payload.top_badge or "ROLE", role_size - 24, int(role_size * 0.42), "black")
    role_text = _truncate_text_to_width(draw, payload.top_badge or "ROLE", role_font, role_size - 22)
    _draw_centered_text(draw, role_box, role_text, role_font, WHITE, shadow=True)

    team_font = _fit_font(draw, payload.team_name, int(card_w * 0.34), int(card_h * 0.058), "black")
    team_text = _truncate_text_to_width(draw, payload.team_name, team_font, int(card_w * 0.34))
    _draw_text(draw, (pad + flag_w + 32, pad + 10), team_text, team_font, WHITE)
    comp_font = _load_font(max(18, int(card_h * 0.020)), "bold")
    draw.text((pad + flag_w + 36, pad + 10 + _text_size(draw, team_text, team_font)[1] + 22), "SERIE A", fill=accent, font=comp_font)

    pos_box = (pad + 6, int(card_h * 0.205), pad + int(card_w * 0.205), int(card_h * 0.405))
    foot_box = (pad + 6, int(card_h * 0.435), pad + int(card_w * 0.185), int(card_h * 0.64))
    _draw_panel(card, pos_box, outline=(primary[0], primary[1], primary[2], 220))
    _draw_panel(card, foot_box, outline=(primary[0], primary[1], primary[2], 165))
    draw = ImageDraw.Draw(card)
    label_font = _load_font(max(16, int(card_h * 0.018)), "bold")
    pos_value_font = _fit_font(draw, payload.top_badge or "ROLE", pos_box[2] - pos_box[0] - 34, int(card_h * 0.073), "black")
    _draw_centered_text(draw, (pos_box[0] + 12, pos_box[1] + 24, pos_box[2] - 12, pos_box[1] + 58), "POSIZIONE", label_font, accent)
    pv = _truncate_text_to_width(draw, payload.top_badge or "ROLE", pos_value_font, pos_box[2] - pos_box[0] - 34)
    _draw_centered_text(draw, (pos_box[0] + 10, pos_box[1] + 76, pos_box[2] - 10, pos_box[3] - 58), pv, pos_value_font, WHITE, shadow=True)
    draw.line((pos_box[0] + 42, pos_box[3] - 36, pos_box[2] - 42, pos_box[3] - 36), fill=primary, width=4)

    foot_value = {"left": "SX", "right": "DX", "both": "B"}.get(payload.foot, "--")
    _draw_centered_text(draw, (foot_box[0] + 12, foot_box[1] + 24, foot_box[2] - 12, foot_box[1] + 58), "PIEDE", label_font, accent)
    boot_size = int(card_w * 0.078)
    boot_x = foot_box[0] + (foot_box[2] - foot_box[0] - boot_size) // 2
    _draw_simple_boot(draw, boot_x, foot_box[1] + 82, boot_size, WHITE)
    foot_font = _load_font(max(24, int(card_h * 0.038)), "black")
    _draw_centered_text(draw, (foot_box[0] + 10, foot_box[3] - 78, foot_box[2] - 10, foot_box[3] - 34), foot_value, foot_font, WHITE, shadow=True)
    draw.line((foot_box[0] + 42, foot_box[3] - 28, foot_box[2] - 42, foot_box[3] - 28), fill=primary, width=4)

    height_box = (int(card_w * 0.680), int(card_h * 0.205), card_w - pad - 2, int(card_h * 0.335))
    _draw_panel(card, height_box, outline=(255, 255, 255, 132))
    draw = ImageDraw.Draw(card)
    height_digits = payload.height_text.replace("cm", "").strip() or "--"
    icon_size = max(54, int(card_w * 0.073))
    icon_x = height_box[0] + 22
    icon_y = height_box[1] + (height_box[3] - height_box[1] - icon_size) // 2
    _draw_height_icon(card, x=icon_x, y=icon_y, size=icon_size, color=accent)

    value_x0 = icon_x + icon_size + 16
    value_x1 = height_box[2] - 18
    height_font = _fit_font(draw, height_digits, value_x1 - value_x0, int(card_h * 0.060), "black")
    cm_font = _load_font(max(18, int(card_h * 0.030)), "black")
    _draw_centered_text(draw, (value_x0, height_box[1] + 20, value_x1, height_box[1] + 80), height_digits, height_font, WHITE, shadow=True)
    _draw_centered_text(draw, (value_x0, height_box[1] + 78, value_x1, height_box[3] - 16), "cm", cm_font, accent, shadow=False)

    player_box = (int(card_w * 0.19), int(card_h * 0.15), int(card_w * 0.82), int(card_h * 0.79))
    _draw_player_image(card, player_box, payload.player_image_bytes)

    footer = (pad, int(card_h * 0.775), card_w - pad, card_h - pad)
    footer_layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    footer_draw = ImageDraw.Draw(footer_layer)
    footer_draw.rounded_rectangle(footer, radius=28, fill=(7, 13, 22, 225), outline=(255, 255, 255, 50), width=2)
    footer_layer = footer_layer.filter(ImageFilter.GaussianBlur(0))
    card.alpha_composite(footer_layer)
    draw = ImageDraw.Draw(card)

    first, last = _split_player_name(payload.player_name)
    first_font = _fit_font(draw, first, int(card_w * 0.37), int(card_h * 0.040), "bold") if first else _load_font(10, "bold")
    last_font = _fit_font(draw, last, int(card_w * 0.43), int(card_h * 0.085), "black")
    birth_font = _load_font(max(22, int(card_h * 0.040)), "black")
    name_x = footer[0] + 52
    if first:
        spaced_first = " ".join(first)
        _draw_text(draw, (name_x, footer[1] + 38), _truncate_text_to_width(draw, spaced_first, first_font, int(card_w * 0.38)), first_font, WHITE)
    last_y = footer[1] + 86
    _draw_text(draw, (name_x, last_y), _truncate_text_to_width(draw, last, last_font, int(card_w * 0.43)), last_font, WHITE)
    if payload.footer_id:
        last_w = _text_size(draw, _truncate_text_to_width(draw, last, last_font, int(card_w * 0.43)), last_font)[0]
        _draw_text(draw, (name_x + last_w + 18, last_y + 30), f"({payload.footer_id})", birth_font, primary)
    draw.line((name_x, footer[3] - 28, int(card_w * 0.64), footer[3] - 28), fill=primary, width=4)
    draw.ellipse((int(card_w * 0.385) - 5, footer[3] - 33, int(card_w * 0.385) + 5, footer[3] - 23), fill=accent)

    rating_box = (int(card_w * 0.70), footer[1] + 26, footer[2] - 18, footer[3] - 18)
    level_fill = _hex_to_rgba(payload.level_badge_color_hex, GREEN_BADGE)
    _draw_hexagon(card, rating_box, fill=(10, 16, 28, 242), outline=level_fill, width=3, glow=True)
    draw = ImageDraw.Draw(card)
    rating_font = _fit_font(draw, payload.level_badge or "A1", rating_box[2] - rating_box[0] - 58, int(card_h * 0.070), "black")
    rating_text = _truncate_text_to_width(draw, payload.level_badge or "A1", rating_font, rating_box[2] - rating_box[0] - 46)
    _draw_centered_text(draw, (rating_box[0] + 18, rating_box[1] + 36, rating_box[2] - 18, rating_box[1] + 122), rating_text, rating_font, WHITE, shadow=True)

    canvas.paste(card, (margin, margin), _rounded_mask((card_w, card_h), radius))
    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()
