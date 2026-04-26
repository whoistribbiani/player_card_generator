from __future__ import annotations

import sys
import inspect
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from player_card_generator.api_client import ScoutasticApiClient, fetch_player_bundle
from player_card_generator.logic import (
    LEVEL_BADGE_OPTIONS,
    birth_year_suffix_prefill,
    build_card_payload,
    role_badge_prefill,
)
from player_card_generator.models import PlayerBundle
from player_card_generator.renderer import render_player_card_png
from player_card_generator.ui_state import reset_cascade_state

st.set_page_config(page_title="Card PNG Builder", layout="wide")


def _safe_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _custom_image_store() -> Dict[str, bytes]:
    store = st.session_state.setdefault("pcg_custom_player_images", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state["pcg_custom_player_images"] = store
    return store


def _custom_flag_store() -> Dict[str, bytes]:
    store = st.session_state.setdefault("pcg_custom_flag_images", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state["pcg_custom_flag_images"] = store
    return store


def _player_url_store() -> Dict[str, str]:
    store = st.session_state.setdefault("pcg_custom_player_image_urls", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state["pcg_custom_player_image_urls"] = store
    return store


def _flag_url_store() -> Dict[str, str]:
    store = st.session_state.setdefault("pcg_custom_flag_image_urls", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state["pcg_custom_flag_image_urls"] = store
    return store


def _height_override_store() -> Dict[str, int]:
    store = st.session_state.setdefault("pcg_custom_height_cm", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state["pcg_custom_height_cm"] = store
    return store


def _parse_height_override(value: str) -> tuple[Optional[int], Optional[str]]:
    raw = _safe_text(value)
    if not raw:
        return None, None
    if not raw.isdigit():
        return None, "Altezza override non valida: usa un numero intero in cm (120..250)."
    cm = int(raw)
    if cm < 120 or cm > 250:
        return None, "Altezza override fuori range: inserisci un valore tra 120 e 250 cm."
    return cm, None


def _build_card_payload_compat(bundle: PlayerBundle, **kwargs):
    params = inspect.signature(build_card_payload).parameters
    supported = {key: value for key, value in kwargs.items() if key in params}
    return build_card_payload(bundle, **supported)


def _ensure_option_key(key: str, options: List[str]) -> None:
    current = _safe_text(st.session_state.get(key))
    if options and current not in options:
        st.session_state[key] = options[0] if options else ""
    if key not in st.session_state:
        st.session_state[key] = options[0] if options else ""


@st.cache_data(ttl=600, show_spinner=False)
def _cached_competitions(season_id: str, gender: str) -> List[Dict[str, object]]:
    client = ScoutasticApiClient()
    return client.list_competitions(season_id=season_id, gender=gender)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_competition_teams(
    competition_id: str,
    season_id: str,
    gender: str,
    competition_api_ids: tuple[str, ...],
) -> List[Dict[str, object]]:
    client = ScoutasticApiClient()
    return client.list_competition_teams(
        competition_id=competition_id,
        season_id=season_id,
        gender=gender,
        competition_api_ids=list(competition_api_ids),
    )


@st.cache_data(ttl=600, show_spinner=False)
def _cached_team_players(team_id: str, season_id: str) -> List[Dict[str, object]]:
    client = ScoutasticApiClient()
    return client.list_team_players(team_id=team_id, season_id=season_id)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_player_bundle(player_id: str) -> PlayerBundle:
    return fetch_player_bundle(player_id)


def _competition_label(competition: Dict[str, object]) -> str:
    name = _safe_text(competition.get("name")) or "Competition"
    area = _safe_text(competition.get("area"))
    season = _safe_text(competition.get("season"))
    parts = [name]
    if area:
        parts.append(area)
    if season:
        parts.append(f"S{season}")
    return " | ".join(parts)


def _team_label(team: Dict[str, object]) -> str:
    return _safe_text(team.get("teamName")) or _safe_text(team.get("teamId")) or "Team"


def _player_label(player: Dict[str, object]) -> str:
    name = _safe_text(player.get("displayName")) or _safe_text(player.get("playerId")) or "Player"
    role = _safe_text(player.get("mainPosition"))
    return f"{name} ({role})" if role else name


def _current_bundle(player_id: str) -> Optional[PlayerBundle]:
    bundle = st.session_state.get("pcg_bundle")
    if not isinstance(bundle, PlayerBundle):
        return None
    if bundle.player_id != _safe_text(player_id):
        return None
    return bundle


def _sync_cascade_reset(season_id: str, competition_id: str, team_id: str) -> None:
    prev_season = _safe_text(st.session_state.get("pcg_prev_season_id"))
    if prev_season != season_id:
        reset_cascade_state(st.session_state, changed_level="season")
        st.session_state["pcg_prev_season_id"] = season_id
        st.session_state["pcg_prev_competition_id"] = ""
        st.session_state["pcg_prev_team_id"] = ""

    prev_competition = _safe_text(st.session_state.get("pcg_prev_competition_id"))
    if prev_competition != competition_id:
        reset_cascade_state(st.session_state, changed_level="competition")
        st.session_state["pcg_prev_competition_id"] = competition_id
        st.session_state["pcg_prev_team_id"] = ""

    prev_team = _safe_text(st.session_state.get("pcg_prev_team_id"))
    if prev_team != team_id:
        reset_cascade_state(st.session_state, changed_level="team")
        st.session_state["pcg_prev_team_id"] = team_id


def main() -> None:
    st.title("Card PNG Builder")
    st.caption("Flusso guidato: Season -> Competizione -> Squadra -> Giocatore, con export PNG.")

    season_default = str(datetime.now().year)
    gender = "male"
    top_row = st.columns([1, 3, 3, 3])
    with top_row[0]:
        season_id = st.text_input("Season ID", value=season_default, key="pcg_season_id").strip()
    if not season_id:
        st.info("Inserisci il Season ID per caricare le competizioni.")
        return

    try:
        competitions = _cached_competitions(season_id=season_id, gender=gender)
    except Exception as exc:
        st.error(f"Errore caricamento competizioni: {exc}")
        return
    if not competitions:
        st.warning("Nessuna competizione trovata per Season ID selezionato.")
        return

    competition_map = {
        _safe_text(row.get("competitionId")): row
        for row in competitions
        if _safe_text(row.get("competitionId"))
    }
    competition_options = sorted(
        competition_map.keys(),
        key=lambda cid: _competition_label(competition_map.get(cid, {})).lower(),
    )
    _ensure_option_key("pcg_competition_id", competition_options)
    with top_row[1]:
        selected_competition_id = st.selectbox(
            "Competizione",
            options=competition_options,
            key="pcg_competition_id",
            format_func=lambda cid: _competition_label(competition_map.get(_safe_text(cid), {})),
        )

    selected_competition = competition_map.get(_safe_text(selected_competition_id), {})
    competition_api_ids = tuple([_safe_text(v) for v in (selected_competition.get("apiIds") or []) if _safe_text(v)])

    _sync_cascade_reset(season_id, _safe_text(selected_competition_id), _safe_text(st.session_state.get("pcg_team_id")))

    try:
        teams = _cached_competition_teams(
            competition_id=_safe_text(selected_competition_id),
            season_id=season_id,
            gender=gender,
            competition_api_ids=competition_api_ids,
        )
    except Exception as exc:
        st.error(f"Errore caricamento squadre: {exc}")
        return
    if not teams:
        st.warning("Nessuna squadra trovata per la competizione selezionata.")
        return

    team_map = {
        _safe_text(row.get("teamId")): row
        for row in teams
        if _safe_text(row.get("teamId"))
    }
    team_options = sorted(team_map.keys(), key=lambda tid: _team_label(team_map.get(tid, {})).lower())
    _ensure_option_key("pcg_team_id", team_options)
    with top_row[2]:
        selected_team_id = st.selectbox(
            "Squadra",
            options=team_options,
            key="pcg_team_id",
            format_func=lambda tid: _team_label(team_map.get(_safe_text(tid), {})),
        )

    _sync_cascade_reset(season_id, _safe_text(selected_competition_id), _safe_text(selected_team_id))

    try:
        players = _cached_team_players(team_id=_safe_text(selected_team_id), season_id=season_id)
    except Exception as exc:
        st.error(f"Errore caricamento giocatori: {exc}")
        return
    if not players:
        st.warning("Nessun giocatore trovato per la squadra selezionata.")
        return

    player_map = {
        _safe_text(row.get("playerId")): row
        for row in players
        if _safe_text(row.get("playerId"))
    }
    player_options = sorted(player_map.keys(), key=lambda pid: _player_label(player_map.get(pid, {})).lower())
    _ensure_option_key("pcg_player_id", player_options)
    with top_row[3]:
        selected_player_id = st.selectbox(
            "Giocatore",
            options=player_options,
            key="pcg_player_id",
            format_func=lambda pid: _player_label(player_map.get(_safe_text(pid), {})),
        )

    if not _safe_text(selected_player_id):
        st.info("Seleziona un giocatore per generare la card.")
        return

    bundle = _current_bundle(_safe_text(selected_player_id))
    if bundle is None:
        with st.spinner("Recupero profilo completo giocatore..."):
            try:
                bundle = _cached_player_bundle(_safe_text(selected_player_id))
            except Exception as exc:
                st.error(f"Errore caricamento profilo giocatore: {exc}")
                return
            st.session_state["pcg_bundle"] = bundle

    st.markdown(
        f"**Selezione:** {_competition_label(selected_competition)} -> {_team_label(team_map.get(_safe_text(selected_team_id), {}))} -> {_player_label(player_map.get(_safe_text(selected_player_id), {}))}"
    )

    if st.session_state.get("pcg_role_badge_player") != bundle.player_id:
        st.session_state["pcg_role_badge"] = role_badge_prefill(bundle.player)
        st.session_state["pcg_role_badge_player"] = bundle.player_id
    if st.session_state.get("pcg_birth_year_player") != bundle.player_id:
        st.session_state["pcg_footer_id"] = birth_year_suffix_prefill(bundle.player)
        st.session_state["pcg_birth_year_player"] = bundle.player_id

    st.markdown("### Configurazione Card")
    details_col, overrides_col, output_col = st.columns([1.1, 1.5, 1.4], gap="large")

    custom_store = _custom_image_store()
    custom_flag_store = _custom_flag_store()
    player_url_store = _player_url_store()
    flag_url_store = _flag_url_store()
    height_store = _height_override_store()

    with details_col:
        st.markdown("#### Dati Card")
        role_badge_text = st.text_input("Ruolo (Top Badge)", key="pcg_role_badge")
        default_level_index = LEVEL_BADGE_OPTIONS.index("A1")
        level_badge = st.selectbox("Level Badge", options=LEVEL_BADGE_OPTIONS, index=default_level_index, key="pcg_level_badge")
        footer_id = st.text_input("Anno nascita (YY)", key="pcg_footer_id")

    with overrides_col:
        left_override, right_override = st.columns(2, gap="medium")
        with left_override:
            st.markdown("#### Override Giocatore")
            uploaded = st.file_uploader(
                "Upload immagine giocatore",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"pcg_uploader_{bundle.player_id}",
            )
            if uploaded is not None:
                custom_store[bundle.player_id] = uploaded.getvalue()

            if bundle.player_id in custom_store and st.button("Reset upload giocatore", key=f"pcg_remove_custom_player_{bundle.player_id}"):
                custom_store.pop(bundle.player_id, None)

            player_url_input = st.text_input(
                "URL immagine giocatore",
                value=player_url_store.get(bundle.player_id, ""),
                key=f"pcg_player_url_{bundle.player_id}",
                placeholder="https://... oppure data:image/...",
            ).strip()
            if player_url_input:
                player_url_store[bundle.player_id] = player_url_input
            else:
                player_url_store.pop(bundle.player_id, None)
            if bundle.player_id in player_url_store and st.button("Reset URL giocatore", key=f"pcg_reset_player_url_{bundle.player_id}"):
                player_url_store.pop(bundle.player_id, None)
                st.session_state.pop(f"pcg_player_url_{bundle.player_id}", None)
                st.rerun()

        with right_override:
            st.markdown("#### Override Bandiera + Altezza")
            uploaded_flag = st.file_uploader(
                "Upload immagine bandiera",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"pcg_flag_uploader_{bundle.player_id}",
            )
            if uploaded_flag is not None:
                custom_flag_store[bundle.player_id] = uploaded_flag.getvalue()

            if bundle.player_id in custom_flag_store and st.button("Reset upload bandiera", key=f"pcg_remove_custom_flag_{bundle.player_id}"):
                custom_flag_store.pop(bundle.player_id, None)

            flag_url_input = st.text_input(
                "URL immagine bandiera",
                value=flag_url_store.get(bundle.player_id, ""),
                key=f"pcg_flag_url_{bundle.player_id}",
                placeholder="https://... oppure data:image/...",
            ).strip()
            if flag_url_input:
                flag_url_store[bundle.player_id] = flag_url_input
            else:
                flag_url_store.pop(bundle.player_id, None)
            if bundle.player_id in flag_url_store and st.button("Reset URL bandiera", key=f"pcg_reset_flag_url_{bundle.player_id}"):
                flag_url_store.pop(bundle.player_id, None)
                st.session_state.pop(f"pcg_flag_url_{bundle.player_id}", None)
                st.rerun()

            height_raw = st.text_input(
                "Altezza override (cm, opzionale)",
                value=str(height_store.get(bundle.player_id, "")),
                key=f"pcg_height_override_{bundle.player_id}",
                placeholder="es. 191",
            )
            height_override_cm, height_warning = _parse_height_override(height_raw)
            if height_warning:
                st.warning(height_warning)
                height_store.pop(bundle.player_id, None)
            elif height_override_cm is not None:
                height_store[bundle.player_id] = height_override_cm
            else:
                height_store.pop(bundle.player_id, None)
            if bundle.player_id in height_store and st.button("Reset altezza", key=f"pcg_reset_height_{bundle.player_id}"):
                height_store.pop(bundle.player_id, None)
                st.session_state.pop(f"pcg_height_override_{bundle.player_id}", None)
                st.rerun()

    payload = _build_card_payload_compat(
        bundle,
        role_badge_text=role_badge_text,
        level_badge=level_badge,
        footer_id=footer_id,
        custom_player_image_bytes=custom_store.get(bundle.player_id),
        custom_player_image_url=player_url_store.get(bundle.player_id),
        custom_flag_image_bytes=custom_flag_store.get(bundle.player_id),
        custom_flag_image_url=flag_url_store.get(bundle.player_id),
        custom_height_cm=height_store.get(bundle.player_id),
    )
    png_bytes = render_player_card_png(payload, width=900, height=1200)

    player_source_label = {
        "custom_upload": "custom_upload",
        "url": "url",
        "api": "api",
        "placeholder": "placeholder",
    }.get(getattr(payload, "player_image_source", "placeholder"), getattr(payload, "player_image_source", "placeholder"))
    flag_source_label = {
        "custom_upload": "custom_upload",
        "url": "url",
        "auto": "auto",
        "text_fallback": "text_fallback",
    }.get(getattr(payload, "flag_image_source", "text_fallback"), getattr(payload, "flag_image_source", "text_fallback"))
    height_source_raw = getattr(payload, "height_source", "api")
    height_source_label = {"override_cm": "override_cm", "api": "api"}.get(height_source_raw, height_source_raw)
    with output_col:
        st.markdown("#### Output")
        st.caption(
            "Sorgenti -> "
            f"player: {player_source_label} | "
            f"flag: {flag_source_label} | "
            f"height: {height_source_label} | "
            f"Level color: {payload.level_badge_color_hex}"
        )
        st.image(png_bytes, caption="Anteprima card", use_container_width=True)
        st.download_button(
            label="Download PNG",
            data=png_bytes,
            file_name=f"player_card_{bundle.player_id}.png",
            mime="image/png",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
