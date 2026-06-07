from __future__ import annotations

from pathlib import Path


def test_phase42_router_exposes_friendly_maestro_configuration_form() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert "Assistente de configuração" in router
    assert 'id="cfg_aliases"' in router
    assert 'id="cfg_canais"' in router
    assert '@router.post("/api/configuracao/raw-preview")' in router
    assert "Gerar Raw Editor" in router
    assert "Raw Editor final" in router


def test_phase42_raw_preview_function_generates_final_block(monkeypatch) -> None:
    import pytest
    pytest.importorskip("sqlalchemy")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    from app.equalizador.configuracao import raw_editor_from_form_payload

    payload = raw_editor_from_form_payload(
        {
            "app_name": "equalizador",
            "enabled": "true",
            "aliases_linhas": "radio=-1003818494866",
            "palco_ids": "-1003818494866",
            "maestro_ids": "8505890439",
            "operador_ids": "8505890439,1759115970",
            "canais": "8505890439:*:*;1759115970:*:palco.ver,mensagens.apagar",
            "rate_limit_per_minute": "30",
        }
    )
    raw = str(payload["raw_editor"])
    assert 'TR4_EQUALIZADOR_APP_NAME="equalizador"' in raw
    assert 'TR4_EQUALIZADOR_PALCO_IDS="-1003818494866"' in raw
    assert 'TR4_EQUALIZADOR_MAESTRO_IDS="8505890439"' in raw
    assert 'TR4_EQUALIZADOR_OPERADOR_IDS="1759115970,8505890439"' in raw
    assert "GROUP_ALIASES" in raw
    assert payload["resumo"]["palcos"] == 1
