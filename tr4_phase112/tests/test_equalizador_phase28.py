from __future__ import annotations

from pathlib import Path

from app.equalizador.permissions import CRITICAL_CANAL_CODES, canal_codes_for_operator, canal_is_allowed


ROOT = Path(__file__).resolve().parents[1]


def test_phase28_operator_wildcard_still_cannot_receive_critical_channels() -> None:
    raw = "8505890439:*:*;1759115970:*:*"
    operator_codes = set(
        canal_codes_for_operator(
            raw_canais=raw,
            user_id=1759115970,
            chat_ids={-1002556760909, -1003839856024},
            is_maestro=False,
        )
    )

    assert "mensagens.apagar" in operator_codes
    assert "membros.silenciar" in operator_codes
    assert operator_codes.isdisjoint(CRITICAL_CANAL_CODES)
    assert canal_is_allowed(
        raw_canais=raw,
        user_id=1759115970,
        chat_id=-1002556760909,
        canal_codigo="transmissao.enviar",
        is_maestro=False,
    ) is False


def test_phase28_maestro_mode_requires_maestro_and_critical_grant() -> None:
    raw = "8505890439:*:*;1671386070:*:palco.ver,palco.status,mensagens.apagar"
    maestro_codes = set(
        canal_codes_for_operator(
            raw_canais=raw,
            user_id=8505890439,
            chat_ids={-1002556760909},
            is_maestro=True,
        )
    )
    operator_codes = set(
        canal_codes_for_operator(
            raw_canais=raw,
            user_id=1671386070,
            chat_ids={-1002556760909},
            is_maestro=False,
        )
    )

    assert "silencio.ativar" in maestro_codes
    assert "historico.exportar" in maestro_codes
    assert operator_codes.isdisjoint(CRITICAL_CANAL_CODES)


def test_phase28_router_payload_declares_maestro_mode_without_raw_ids() -> None:
    router = (ROOT / "app/equalizador/router.py").read_text()

    assert '"modo_maestro": modo_maestro' in router
    assert "CRITICAL_CANAL_CODES" in router
    assert "_require_any_canal_for_palco" in router
    assert 'canal_codigos=("palco.afinar", "palco.status")' in router
    assert "modo_maestro" not in "8505890439"


def test_phase28_frontend_hides_maestro_area_for_operator_profiles() -> None:
    router = (ROOT / "app/equalizador/router.py").read_text()

    assert 'id="maestro_nav"' in router
    assert "Modo Maestro indisponível para este perfil." in router
    assert "Distribuição restrita ao Maestro." in router
    assert "modoMaestroPermitido ? api(\"/equalizador/api/canais/distribuicao\")" in router
    assert "Exportação restrita ao Maestro." in router


def test_phase28_frontend_requires_afinacao_before_enabling_actions() -> None:
    router = (ROOT / "app/equalizador/router.py").read_text()

    assert "const canRun = (codigo) => hasCanal(codigo) && afinacaoLoaded && direitosDisponiveis.has(codigo);" in router
    assert "Ação restrita ao Maestro" in router
    assert "Canal ou afinação indisponível" in router
