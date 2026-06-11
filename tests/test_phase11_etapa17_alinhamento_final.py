from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
WEBAPP = (ROOT / "app/equalizador/governante_webapp.py").read_text(encoding="utf-8")
PAINEL = (ROOT / "app/equalizador/painel.py").read_text(encoding="utf-8")


def test_governante_packages_do_not_advertise_actions_that_need_owner_only_lists() -> None:
    advanced_section = WEBAPP.split("ADVANCED_ACTIONS", 1)[1].split("CUSTOM_PACKAGE", 1)[0]
    for action in [
        '"convites.editar"',
        '"convites.revogar"',
        '"reacoes.mensagem.limpar"',
        '"reacoes.recentes.limpar"',
        '"reacoes.reactor.silenciar"',
        '"canais_remetentes.banir"',
        '"canais_remetentes.liberar"',
    ]:
        assert action not in advanced_section


def test_custom_package_actions_are_driven_by_sanitized_backend_payload() -> None:
    render_block = ROUTER.split("function renderGovernantePackageActions()", 1)[1].split("function selectedGovernanteAssignment()", 1)[0]
    assert "custom_allowed_actions" in render_block
    assert "gov-pkg-action" in render_block
    advanced_section = WEBAPP.split("ADVANCED_ACTIONS", 1)[1].split("CUSTOM_PACKAGE", 1)[0]
    for expected in ["mensagens.enviar", "mensagens.enviar_foto", "mensagens.apagar", "fixados.criar", "membros.remover", "convites.criar"]:
        assert expected in WEBAPP
    for forbidden in [
        "convites.editar",
        "convites.revogar",
        "convites.exportar_primario",
        "entradas.aprovar",
        "entradas.recusar",
        "reacoes.mensagem.limpar",
        "reacoes.recentes.limpar",
        "canais_remetentes.banir",
        "canais_remetentes.liberar",
        "mensagens.apagar_lote",
    ]:
        assert forbidden not in advanced_section


def test_resolvers_cover_only_current_governante_operational_actions() -> None:
    msg_block = ROUTER.split('async def equalizador_resolver_mensagem', 1)[1].split('@router.post("/api/palcos/{grp_ref}/alvos/resolver")', 1)[0]
    assert 'actions=("mensagens.apagar", "fixados.criar", "fixados.remover")' in msg_block
    assert "reacoes.mensagem.limpar" not in msg_block


def test_duplicate_alvos_return_removed_and_member_label_corrected() -> None:
    alvos_block = ROUTER.split('def equalizador_palco_alvos', 1)[1].split('@router.post("/api/palcos/{grp_ref}/mensagens/resolver")', 1)[0]
    assert alvos_block.count('return {"alvos"') == 1
    assert "Restringir/remover membros" not in PAINEL
    assert "Restringir/banir membros" in PAINEL


def test_stage17_document_exists() -> None:
    doc = ROOT / "docs/FASE11_ETAPA17_ALINHAMENTO_FINAL_UI_BACKEND.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "Etapa 17" in text
    assert "ações que dependem de listagens owner-only" in text
