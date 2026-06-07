from __future__ import annotations

from pathlib import Path

from app.equalizador.permissions import (
    canal_codes_for_operator,
    canal_is_allowed,
    canais_for_palco,
    filter_palco_ids_by_canal,
    parse_equalizador_canais,
)


def test_phase4_parse_canais_env_with_wildcards() -> None:
    grants = parse_equalizador_canais("8505890439:*:*;123:-100111:palco.ver,mensagens.apagar")

    assert len(grants) == 2
    assert grants[0].user_id == 8505890439
    assert grants[0].chat_id is None
    assert grants[0].todos_canais is True
    assert grants[1].user_id == 123
    assert grants[1].chat_id == -100111
    assert grants[1].canais == frozenset({"palco.ver", "mensagens.apagar"})


def test_phase4_denies_by_default_without_canais_env() -> None:
    assert canal_is_allowed(
        raw_canais="",
        user_id=8505890439,
        chat_id=-100111,
        canal_codigo="palco.ver",
        is_maestro=True,
    ) is False


def test_phase4_wildcard_grant_still_blocks_critical_channels_for_non_maestro() -> None:
    raw = "123:*:*"

    assert canal_is_allowed(
        raw_canais=raw,
        user_id=123,
        chat_id=-100111,
        canal_codigo="mensagens.apagar",
        is_maestro=False,
    ) is True
    assert canal_is_allowed(
        raw_canais=raw,
        user_id=123,
        chat_id=-100111,
        canal_codigo="transmissao.enviar",
        is_maestro=False,
    ) is False


def test_phase4_maestro_can_use_critical_channel_only_when_granted() -> None:
    assert canal_is_allowed(
        raw_canais="8505890439:*:*",
        user_id=8505890439,
        chat_id=-100111,
        canal_codigo="palco.afinar",
        is_maestro=True,
    ) is True
    assert canal_is_allowed(
        raw_canais="8505890439:*:palco.ver",
        user_id=8505890439,
        chat_id=-100111,
        canal_codigo="palco.afinar",
        is_maestro=True,
    ) is False


def test_phase4_filters_visible_palcos_by_channel() -> None:
    raw = "123:-100111:palco.ver,canais.ver;123:-100222:mensagens.apagar"

    assert filter_palco_ids_by_canal(
        raw_canais=raw,
        user_id=123,
        chat_ids={-100111, -100222},
        canal_codigo="palco.ver",
        is_maestro=False,
    ) == {-100111}


def test_phase4_public_canais_payload_has_no_raw_identifiers() -> None:
    raw = "123:-100111:palco.ver,canais.ver,mensagens.apagar"

    canais = canais_for_palco(raw_canais=raw, user_id=123, chat_id=-100111, is_maestro=False)
    codes = canal_codes_for_operator(raw_canais=raw, user_id=123, chat_ids={-100111}, is_maestro=False)
    rendered = repr({"canais": canais, "codes": codes})

    assert "palco.ver" in codes
    assert any(item["codigo"] == "mensagens.apagar" for item in canais)
    assert "-100111" not in rendered
    assert "123" not in rendered
    assert "telegram" not in rendered.lower()


def test_phase4_files_register_read_only_canais_route() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    settings = (root / "app/config/settings.py").read_text()

    assert "TR4_EQUALIZADOR_CANAIS" in settings
    assert '@router.get("/api/canais")' in router
    assert "canal_is_allowed" in router
