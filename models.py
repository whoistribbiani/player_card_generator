from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PlayerBundle:
    player_id: str
    player: Dict[str, Any]
    primary_team: Dict[str, Any]
    team: Dict[str, Any]


@dataclass
class CardPayload:
    team_name: str
    player_name: str
    height_text: str
    foot: str
    top_badge: str
    level_badge: str
    level_badge_color_hex: str
    footer_id: str
    flag_iso2: str
    team_logo_bytes: Optional[bytes] = None
    player_image_bytes: Optional[bytes] = None
    flag_image_bytes: Optional[bytes] = None
    player_image_source: str = "placeholder"
    flag_image_source: str = "text_fallback"
    height_source: str = "api"
