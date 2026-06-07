from pathlib import Path

import pytest


def test_phase55_2_source_defines_governance_windows():
    text = Path("app/equalizador/governanca.py").read_text(encoding="utf-8")
    assert "Governante de perfil" in text
    assert "Governante de mensagens" in text
    assert "Governante de pessoas" in text
    assert "Governante do Radio" in text
    assert "Governante de segurança" in text


def test_phase55_2_frontend_has_governance_sections():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert "Governantes deste grupo" in text
    assert "config_governantes" in text
    assert "/governantes" in text
    assert "renderGovernanca" in text


def test_phase55_2_governance_payload_is_sanitized_shape(monkeypatch):
    pytest.importorskip("sqlalchemy")
    from app.equalizador.governanca import governantes_publicos

    monkeypatch.setattr("app.config.settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET", frozenset({8505890439}))
    monkeypatch.setattr("app.config.settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET", frozenset({1759115970}))
    monkeypatch.setattr("app.config.settings.equalizador_allowed_palco_ids", lambda: {-1001234567890})
    monkeypatch.setattr("app.config.settings.equalizador_canais_raw", lambda: "8505890439:*:*;1759115970:*:mensagens.enviar,fixados.criar")
    monkeypatch.setattr("app.config.settings.group_alias_for_chat", lambda chat_id: "radio")
    monkeypatch.setattr("app.config.settings.group_aliases", lambda: {"radio": -1001234567890})
    data = governantes_publicos(alias_secret="test-secret")
    assert data["resumo"]["governantes"] == 2
    assert data["governantes"]
    assert "telegram_user_id" not in repr(data)
    assert any("mensagens" in row.get("perfis_ativos", []) for row in data["governantes"])
