from __future__ import annotations

from typing import MutableMapping


def reset_cascade_state(session_state: MutableMapping[str, object], *, changed_level: str) -> None:
    if changed_level == "season":
        keys = (
            "pcg_competition_id",
            "pcg_team_id",
            "pcg_player_id",
            "pcg_bundle",
            "pcg_role_badge",
            "pcg_role_badge_player",
            "pcg_error",
        )
    elif changed_level == "competition":
        keys = (
            "pcg_team_id",
            "pcg_player_id",
            "pcg_bundle",
            "pcg_role_badge",
            "pcg_role_badge_player",
            "pcg_error",
        )
    elif changed_level == "team":
        keys = (
            "pcg_player_id",
            "pcg_bundle",
            "pcg_role_badge",
            "pcg_role_badge_player",
            "pcg_error",
        )
    else:
        keys = ()

    for key in keys:
        session_state.pop(key, None)
