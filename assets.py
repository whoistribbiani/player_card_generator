from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

from scoutastic_api_config import SCOUTASTIC_BASE_URL

COUNTRY_TO_ISO2: Dict[str, str] = {
    "argentina": "AR",
    "austria": "AT",
    "belgium": "BE",
    "brazil": "BR",
    "czech republic": "CZ",
    "croatia": "HR",
    "denmark": "DK",
    "england": "GB",
    "france": "FR",
    "germany": "DE",
    "ghana": "GH",
    "greece": "GR",
    "holland": "NL",
    "hungary": "HU",
    "ireland": "IE",
    "italy": "IT",
    "ivory coast": "CI",
    "japan": "JP",
    "mexico": "MX",
    "morocco": "MA",
    "netherlands": "NL",
    "nigeria": "NG",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "scotland": "GB",
    "serbia": "RS",
    "slovakia": "SK",
    "slovenia": "SI",
    "south korea": "KR",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "turkey": "TR",
    "ukraine": "UA",
    "united kingdom": "GB",
    "united states": "US",
    "uruguay": "UY",
}


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def preferred_image_url(record: Dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return ""
    return _safe_text(record.get("imageUrlV2")) or _safe_text(record.get("imageUrl"))


def resolve_absolute_url(raw_url: str, *, base_url: str = SCOUTASTIC_BASE_URL) -> str:
    raw = _safe_text(raw_url)
    if not raw:
        return ""
    if raw.lower().startswith(("http://", "https://")):
        return raw
    parsed = urlparse(_safe_text(base_url))
    if not parsed.scheme or not parsed.netloc:
        return raw
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return urljoin(f"{origin}/", raw)


def get_player_image_url(player: Dict[str, Any]) -> str:
    return resolve_absolute_url(preferred_image_url(player))


def get_team_logo_url(team: Dict[str, Any]) -> str:
    return resolve_absolute_url(preferred_image_url(team))


def normalize_country_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", _safe_text(value))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-zA-Z ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def nationality_to_iso2(value: Any) -> Optional[str]:
    raw = _safe_text(value)
    if not raw:
        return None
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    normalized = normalize_country_name(raw)
    return COUNTRY_TO_ISO2.get(normalized)


def build_flag_url(iso2: str) -> str:
    code = _safe_text(iso2).lower()
    if len(code) != 2 or not code.isalpha():
        return ""
    return f"https://flagcdn.com/w80/{code}.png"


def build_flag_urls(iso2: str) -> List[str]:
    code = _safe_text(iso2)
    if len(code) != 2 or not code.isalpha():
        return []
    return [
        f"https://flagcdn.com/w80/{code.lower()}.png",
        f"https://flagsapi.com/{code.upper()}/flat/64.png",
    ]


def download_image_bytes(
    url: str,
    *,
    access_key: str = "",
    session: Optional[requests.Session] = None,
    timeout: int = 20,
) -> bytes:
    final_url = _safe_text(url)
    if not final_url:
        return b""

    http = session or requests.Session()
    auth_header = {"Authorization": f"Bearer {_safe_text(access_key)}"} if _safe_text(access_key) else {}
    for headers in (auth_header, {}):
        try:
            response = http.get(final_url, headers=headers, timeout=timeout)
        except Exception:
            continue
        if response.status_code != 200 or not response.content:
            continue
        content_type = _safe_text(response.headers.get("Content-Type")).lower()
        if content_type and "image" not in content_type:
            continue
        return response.content
    return b""
