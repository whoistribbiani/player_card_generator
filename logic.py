from __future__ import annotations

import base64
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from player_card_generator.assets import (
    build_flag_urls,
    download_image_bytes,
    get_player_image_url,
    get_team_logo_url,
    nationality_to_iso2,
)
from player_card_generator.models import CardPayload, PlayerBundle
from scoutastic_api_config import get_access_key

LEVEL_BADGE_OPTIONS = ["B2", "B1", "A2", "A2+/A1", "A1"]
LEVEL_BADGE_COLORS = {
    "B2": "#f4cccc",
    "B1": "#c9daf8",
    "A2": "#b6d7a8",
    "A2+/A1": "#6aa84f",
    "A1": "#6aa84f",
}

POSITION_BADGE_MAP = {
    "goalkeeper": "GK",
    "rightback": "RB",
    "leftback": "LB",
    "centerback": "CB",
    "defensivemidfield": "DM",
    "centralmidfield": "CM",
    "attackingmidfield": "AM",
    "rightmidfield": "RM",
    "leftmidfield": "LM",
    "rightwing": "RW",
    "leftwing": "LW",
    "centerforward": "CF",
    "striker": "ST",
}


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _sanitize_role_badge(value: str, *, default: str = "ROLE") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9/+ -]+", "", _safe_text(value).upper())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:12] if cleaned else default


def _sanitize_footer_id(value: str) -> str:
    digits = re.sub(r"[^0-9]+", "", _safe_text(value))
    if len(digits) >= 2:
        return digits[-2:]
    return "02"


def _build_player_name(player: Dict[str, Any]) -> str:
    first = _safe_text(player.get("firstName"))
    last = _safe_text(player.get("lastName"))
    full = " ".join([part for part in (first, last) if part]).strip()
    return full.upper() if full else "PLAYER NAME"


def _build_team_name(team: Dict[str, Any], fallback_team: Dict[str, Any]) -> str:
    team_name = _safe_text(team.get("name")) or _safe_text(fallback_team.get("name"))
    return team_name.upper() if team_name else "TEAM NAME"


def _format_height(value: Any) -> str:
    if isinstance(value, (int, float)):
        cm = int(round(float(value)))
        return f"{cm} cm"
    text = _safe_text(value)
    if text.isdigit():
        return f"{text} cm"
    return "-- cm"


def _normalize_foot(value: Any) -> str:
    raw = _safe_text(value).lower()
    if raw in {"left", "right", "both"}:
        return raw
    return "unknown"


def _is_valid_http_url(value: str) -> bool:
    candidate = _safe_text(value)
    if not candidate:
        return False
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_data_image_url(value: str) -> bool:
    candidate = _safe_text(value).lower()
    return candidate.startswith("data:image/") and "," in candidate


def _manual_image_from_url(value: str) -> bytes:
    candidate = _safe_text(value)
    if not candidate:
        return b""
    if _is_valid_http_url(candidate):
        return download_image_bytes(candidate)
    if _is_data_image_url(candidate):
        header, payload = candidate.split(",", 1)
        if ";base64" not in header.lower():
            return b""
        try:
            return base64.b64decode(payload, validate=False)
        except Exception:
            return b""
    return b""


def _height_override_cm(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        cm = int(value)
    except Exception:
        return None
    if 120 <= cm <= 250:
        return cm
    return None


def role_badge_prefill(player: Dict[str, Any]) -> str:
    raw_role = _safe_text(player.get("mainPosition")).lower()
    if raw_role in POSITION_BADGE_MAP:
        return POSITION_BADGE_MAP[raw_role]
    compact = re.sub(r"[^a-zA-Z0-9]+", "", raw_role).upper()
    if compact:
        return compact[:6]
    return "ROLE"


def normalize_level_badge(value: str) -> str:
    raw = _safe_text(value).upper()
    return raw if raw in LEVEL_BADGE_COLORS else "A1"


def level_badge_color(level_badge: str) -> str:
    return LEVEL_BADGE_COLORS.get(normalize_level_badge(level_badge), "#6aa84f")


def birth_year_suffix_prefill(player: Dict[str, Any]) -> str:
    candidate_fields = (
        player.get("birthDate"),
        player.get("dateOfBirth"),
        player.get("birthday"),
        player.get("dob"),
    )
    for raw in candidate_fields:
        text = _safe_text(raw)
        if not text:
            continue
        match = re.search(r"(19|20)\d{2}", text)
        if match:
            return match.group(0)[-2:]
    return "02"


def build_card_payload(
    bundle: PlayerBundle,
    *,
    role_badge_text: str,
    level_badge: str,
    footer_id: str,
    custom_player_image_bytes: Optional[bytes] = None,
    custom_player_image_url: Optional[str] = None,
    custom_flag_image_bytes: Optional[bytes] = None,
    custom_flag_image_url: Optional[str] = None,
    custom_height_cm: Optional[int] = None,
) -> CardPayload:
    player = bundle.player if isinstance(bundle.player, dict) else {}
    team = bundle.team if isinstance(bundle.team, dict) else {}
    primary_team = bundle.primary_team if isinstance(bundle.primary_team, dict) else {}

    access_key = get_access_key()
    team_logo_url = get_team_logo_url(team) or get_team_logo_url(primary_team)
    team_logo_bytes = download_image_bytes(team_logo_url, access_key=access_key)

    player_image_source = "placeholder"
    player_image_bytes: bytes = b""
    if custom_player_image_bytes:
        player_image_bytes = custom_player_image_bytes
        player_image_source = "custom_upload"
    else:
        player_image_bytes = _manual_image_from_url(_safe_text(custom_player_image_url))
        if player_image_bytes:
            player_image_source = "url"
        if not player_image_bytes:
            player_image_url = get_player_image_url(player)
            player_image_bytes = download_image_bytes(player_image_url, access_key=access_key)
            if player_image_bytes:
                player_image_source = "api"

    nationality = _safe_text(player.get("nationality")) or _safe_text(player.get("secondNationality"))
    flag_iso2 = nationality_to_iso2(nationality) or ""
    flag_image_bytes: bytes = b""
    flag_image_source = "text_fallback"
    if custom_flag_image_bytes:
        flag_image_bytes = custom_flag_image_bytes
        flag_image_source = "custom_upload"
    else:
        flag_image_bytes = _manual_image_from_url(_safe_text(custom_flag_image_url))
        if flag_image_bytes:
            flag_image_source = "url"
        if not flag_image_bytes:
            for flag_url in build_flag_urls(flag_iso2):
                flag_image_bytes = download_image_bytes(flag_url)
                if flag_image_bytes:
                    flag_image_source = "auto"
                    break

    height_override = _height_override_cm(custom_height_cm)
    height_source = "override_cm" if height_override is not None else "api"
    height_value = height_override if height_override is not None else player.get("height")

    normalized_level = normalize_level_badge(level_badge)
    return CardPayload(
        team_name=_build_team_name(team, primary_team),
        player_name=_build_player_name(player),
        height_text=_format_height(height_value),
        foot=_normalize_foot(player.get("foot")),
        top_badge=_sanitize_role_badge(role_badge_text),
        level_badge=normalized_level,
        level_badge_color_hex=level_badge_color(normalized_level),
        footer_id=_sanitize_footer_id(footer_id),
        flag_iso2=flag_iso2,
        team_logo_bytes=team_logo_bytes or None,
        player_image_bytes=player_image_bytes or None,
        flag_image_bytes=flag_image_bytes or None,
        player_image_source=player_image_source,
        flag_image_source=flag_image_source,
        height_source=height_source,
    )
