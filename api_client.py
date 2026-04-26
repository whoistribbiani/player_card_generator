from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import requests

from player_card_generator.models import PlayerBundle
from scoutastic_api_config import SCOUTASTIC_BASE_URL, build_auth_headers, get_access_key

REQUEST_TIMEOUT = 30
MAX_PAGES = 50


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _looks_like_object_id(value: str) -> bool:
    raw = _safe_text(value).lower()
    return len(raw) == 24 and all(ch in "0123456789abcdef" for ch in raw)


def select_primary_team(player: Dict[str, Any]) -> Dict[str, Any]:
    teams = player.get("teams") if isinstance(player, dict) else []
    if not isinstance(teams, list):
        return {}
    for team in teams:
        if isinstance(team, dict) and bool(team.get("isMain")):
            return team
    for team in teams:
        if isinstance(team, dict):
            return team
    return {}


def resolve_team_id(team: Dict[str, Any]) -> str:
    if not isinstance(team, dict):
        return ""
    for key in ("externalId", "teamId", "id", "internalId", "transfermarktId"):
        value = _safe_text(team.get(key))
        if value:
            return value
    return ""


def resolve_competition_id(competition: Dict[str, Any]) -> str:
    if not isinstance(competition, dict):
        return ""
    # Prefer endpoint-safe external identifiers over internal ObjectId-like values.
    preferred_keys = ("externalId", "competitionId", "transfermarktId", "internalId", "id")
    for key in preferred_keys:
        value = _safe_text(competition.get(key))
        if value and not _looks_like_object_id(value):
            return value
    # Final fallback if only internal-style IDs are available.
    for key in preferred_keys:
        value = _safe_text(competition.get(key))
        if value:
            return value
    return ""


def resolve_player_id(player: Dict[str, Any]) -> str:
    if not isinstance(player, dict):
        return ""
    for key in ("transfermarktId", "playerId", "externalId", "id", "internalId"):
        value = _safe_text(player.get(key))
        if value:
            return value
    return ""


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        item = _safe_text(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class ScoutasticApiClient:
    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        base_url: str = SCOUTASTIC_BASE_URL,
        access_key: Optional[str] = None,
    ) -> None:
        self.session = session or requests.Session()
        self.base_url = _safe_text(base_url).rstrip("/")
        self.access_key = _safe_text(access_key) or get_access_key()
        self.headers = build_auth_headers(access_key=self.access_key)

    def _full_url(self, path_or_url: str) -> str:
        raw = _safe_text(path_or_url)
        if raw.startswith(("http://", "https://")):
            return raw
        if not raw.startswith("/"):
            raw = f"/{raw}"
        return f"{self.base_url}{raw}"

    def get_json(self, path_or_url: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(
            self._full_url(path_or_url),
            headers=self.headers,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def get_player(self, player_id: str) -> Dict[str, Any]:
        params = {
            "marketValues": "false",
            "performanceData": "false",
            "injuryData": "false",
            "debuts": "false",
        }
        return self.get_json(f"/players/{_safe_text(player_id)}", params=params)

    def get_team(self, team_id: str) -> Dict[str, Any]:
        return self.get_json(f"/teams/{_safe_text(team_id)}", params={"gender": "male"})

    def list_competitions(self, season_id: str, gender: str = "male") -> List[Dict[str, Any]]:
        sid = _safe_text(season_id)
        if not sid:
            return []

        page = 1
        docs: List[Dict[str, Any]] = []
        while page <= MAX_PAGES:
            payload = self.get_json(
                "/competitions",
                params={
                    "seasons": sid,
                    "gender": _safe_text(gender) or "male",
                    "teamIds": "true",
                    "limit": 1000,
                    "page": page,
                },
            )
            current = payload.get("docs") if isinstance(payload.get("docs"), list) else []
            docs.extend([row for row in current if isinstance(row, dict)])

            total_pages_raw = payload.get("totalPages")
            has_next = bool(payload.get("hasNextPage"))
            try:
                total_pages = int(total_pages_raw)
            except Exception:
                total_pages = 0

            if total_pages > 0 and page >= total_pages:
                break
            if total_pages <= 0 and (not has_next or not current):
                break
            page += 1

        out: List[Dict[str, Any]] = []
        for doc in docs:
            competition_id = resolve_competition_id(doc)
            if not competition_id:
                continue
            api_ids = _dedupe(
                [
                    _safe_text(doc.get("externalId")),
                    _safe_text(doc.get("competitionId")),
                    _safe_text(doc.get("transfermarktId")),
                    _safe_text(doc.get("internalId")),
                    _safe_text(doc.get("id")),
                ]
            )
            out.append(
                {
                    "competitionId": competition_id,
                    "name": _safe_text(doc.get("name")) or competition_id,
                    "area": _safe_text(doc.get("area")),
                    "season": _safe_text(doc.get("season") or sid),
                    "apiIds": api_ids,
                    "raw": doc,
                }
            )
        out.sort(key=lambda row: (_safe_text(row.get("name")).lower(), _safe_text(row.get("area")).lower()))
        return out

    def list_competition_teams(
        self,
        competition_id: str,
        season_id: str,
        gender: str = "male",
        *,
        competition_api_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        sid = _safe_text(season_id)
        cid = _safe_text(competition_id)
        if not sid or not cid:
            return []

        candidate_ids = _dedupe([cid, *(competition_api_ids or [])])
        teams: List[Dict[str, Any]] = []
        for candidate in candidate_ids:
            try:
                payload = self.get_json(
                    f"/competitions/{candidate}/teams/{sid}",
                    params={"gender": _safe_text(gender) or "male"},
                )
            except requests.HTTPError:
                continue
            except Exception:
                continue
            current = payload.get("teams") if isinstance(payload.get("teams"), list) else []
            teams = [row for row in current if isinstance(row, dict)]
            if teams:
                break

        out: List[Dict[str, Any]] = []
        for row in teams:
            team_id = resolve_team_id(row)
            team_name = _safe_text(row.get("name") or row.get("teamName")) or team_id
            if not team_id:
                continue
            out.append(
                {
                    "teamId": team_id,
                    "teamName": team_name,
                    "raw": row,
                }
            )
        out.sort(key=lambda row: _safe_text(row.get("teamName")).lower())
        return out

    def list_team_players(self, team_id: str, season_id: str) -> List[Dict[str, Any]]:
        tid = _safe_text(team_id)
        sid = _safe_text(season_id)
        if not tid or not sid:
            return []
        payload = self.get_json(
            f"/teams/{tid}/players/{sid}",
            params={
                "marketValues": "false",
                "performanceData": "false",
                "injuryData": "false",
                "debuts": "false",
            },
        )
        players = payload.get("players") if isinstance(payload.get("players"), list) else []
        out: List[Dict[str, Any]] = []
        for row in players:
            if not isinstance(row, dict):
                continue
            player_id = resolve_player_id(row)
            if not player_id:
                continue
            first_name = _safe_text(row.get("firstName"))
            last_name = _safe_text(row.get("lastName"))
            display_name = " ".join([part for part in (first_name, last_name) if part]).strip() or player_id
            out.append(
                {
                    "playerId": player_id,
                    "displayName": display_name,
                    "mainPosition": _safe_text(row.get("mainPosition")),
                    "raw": row,
                }
            )
        out.sort(key=lambda row: _safe_text(row.get("displayName")).lower())
        return out


def fetch_player_bundle(player_id: str, *, client: Optional[ScoutasticApiClient] = None) -> PlayerBundle:
    pid = _safe_text(player_id)
    if not pid:
        raise ValueError("player_id non valido.")

    api = client or ScoutasticApiClient()
    player = api.get_player(pid)
    primary_team = select_primary_team(player)
    team_id = resolve_team_id(primary_team)
    team = api.get_team(team_id) if team_id else {}
    return PlayerBundle(
        player_id=pid,
        player=player if isinstance(player, dict) else {},
        primary_team=primary_team if isinstance(primary_team, dict) else {},
        team=team if isinstance(team, dict) else {},
    )
