from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest


def test_phase38_router_exposes_permission_matrix_to_maestro_config() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert '@router.get("/api/permissoes/matriz")' in router
    assert 'matriz_permissoes_publica' in router
    assert 'Matriz completa de permissões' in router
    assert 'config_matriz' in router
    assert 'canais críticos' not in router  # avoid fragile exact prose; rendered dynamically


def test_phase38_permission_matrix_is_sanitized_and_blocks_common_operator_critical_channels(monkeypatch) -> None:
    pytest.importorskip("sqlalchemy")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("GROUP_ALIASES", '{"radio":-1003818494866}')
    monkeypatch.setenv("TR4_EQUALIZADOR_ENABLED", "true")
    monkeypatch.setenv("TR4_EQUALIZADOR_MAESTRO_IDS", "8505890439")
    monkeypatch.setenv("TR4_EQUALIZADOR_OPERADOR_IDS", "8505890439,1759115970")
    monkeypatch.setenv("TR4_EQUALIZADOR_PALCO_IDS", "-1003818494866")
    monkeypatch.setenv("TR4_EQUALIZADOR_CANAIS", "8505890439:*:*;1759115970:*:palco.ver,mensagens.apagar,transmissao.enviar")

    import app.config.settings as settings

    reload(settings)
    from app.equalizador.papeis import matriz_permissoes_publica

    payload = matriz_permissoes_publica(alias_secret=settings.equalizador_alias_secret())
    serialized = repr(payload)
    assert "8505890439" not in serialized
    assert "1759115970" not in serialized
    assert "-1003818494866" not in serialized
    assert payload["resumo"]["operadores"] == 2
    assert payload["resumo"]["palcos"] == 1

    maestro = next(row for row in payload["matriz"] if row["perfil"] == "Maestro")
    operador = next(row for row in payload["matriz"] if row["perfil"] == "Operador")
    maestro_codes = {c["codigo"]: c for c in maestro["palcos"][0]["canais"]}
    operador_codes = {c["codigo"]: c for c in operador["palcos"][0]["canais"]}
    assert maestro_codes["transmissao.enviar"]["concedido"] is True
    assert operador_codes["mensagens.apagar"]["concedido"] is True
    assert operador_codes["transmissao.enviar"]["concedido"] is False
    assert "crítico" in operador_codes["transmissao.enviar"]["motivo"]
