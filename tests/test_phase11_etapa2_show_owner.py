from __future__ import annotations

import pytest

pytest.importorskip("aiogram")

from app.bot.setup_commands import command_scope_summary
from app.bot.show_owner import ShowPalcoStatus, is_show_owner_allowed, render_show_owner_text
from app.config import settings


def test_show_command_is_private_only_command_listing() -> None:
    summary = command_scope_summary()
    assert "show" in summary["private"]
    assert "show" not in summary["public"]
    assert "owner" not in summary["public"]


def test_show_owner_allowed_uses_maestro_ids(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TR4_EQUALIZADOR_MAESTRO_IDS_SET", {12345})
    assert is_show_owner_allowed(12345)
    assert not is_show_owner_allowed(67890)


def test_render_show_owner_text_hides_raw_refs_and_lists_capabilities() -> None:
    text = render_show_owner_text(
        [
            ShowPalcoStatus(
                grp_ref="grp_secret_ref_should_not_render",
                titulo="Grupo Teste",
                estado="afinado",
                disponiveis=("apagar", "ban/unban"),
                faltando=("convites",),
            )
        ],
        config_ok=True,
    )
    assert "TR4 /town" in text
    assert "Grupo Teste" in text
    assert "apagar" in text
    assert "ban/unban" in text
    assert "convites" in text
    assert "grp_secret_ref_should_not_render" not in text


def test_render_show_owner_empty_state_is_safe() -> None:
    text = render_show_owner_text([], config_ok=False, total_config_errors=2)
    assert "Configuração: com avisos" in text
    assert "Avisos de configuração: 2" in text
    assert "Nenhum grupo conhecido" in text
