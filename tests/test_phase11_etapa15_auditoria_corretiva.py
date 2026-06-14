from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
WEBAPP = (ROOT / "app/equalizador/governante_webapp.py").read_text(encoding="utf-8")


def _function_block(name: str) -> str:
    marker = f"def {name}"
    start = ROUTER.index(marker)
    next_def = ROUTER.find("\ndef ", start + 1)
    next_async = ROUTER.find("\nasync def ", start + 1)
    candidates = [pos for pos in (next_def, next_async) if pos != -1]
    end = min(candidates) if candidates else len(ROUTER)
    return ROUTER[start:end]


def test_owner_only_read_endpoints_are_backend_guarded() -> None:
    for fn, module in {
        "equalizador_historico": "historico",
        "equalizador_historico_exportar": "historico",
        "equalizador_entradas_listar": "entradas",
        "equalizador_convites_listar": "convites",
        "equalizador_topicos_listar": "topicos",
        "equalizador_sender_chats_listar": "canais_remetentes",
        "equalizador_novos_membros_status": "novos_membros",
        "equalizador_reacoes_auditoria": "reacoes",
    }.items():
        block = _function_block(fn)
        assert f'_require_owner_only_module(identity, module="{module}")' in block


def test_load_palco_data_does_not_call_owner_only_reads_for_governante() -> None:
    block = ROUTER.split("async function loadPalcoData()", 1)[1].split("function renderAfinacao", 1)[0]
    owner_only_paths = [
        '"/equalizador/api/historico"',
        'base + "/entradas"',
        'base + "/convites"',
        'base + "/topicos"',
        'base + "/canais-remetentes"',
        'base + "/radio/rascunhos"',
        'base + "/radio/templates"',
        'base + "/radio/historico"',
        'base + "/radio/agendamentos"',
        'base + "/radio/silencio"',
        'base + "/reacoes/auditoria"',
        'base + "/novos-membros"',
    ]
    for path in owner_only_paths:
        idx = block.index(path)
        prefix = block[max(0, idx - 80):idx]
        assert "modoMaestroPermitido ?" in prefix


def test_convites_export_primary_no_longer_uses_create_channel() -> None:
    block = ROUTER.split("async def _execute_convite_extra_endpoint", 1)[1].split("@router.post", 1)[0]
    assert '"exportar_primario": "convites.ver"' in block
    assert '"exportar_primario": "convites.criar"' not in block


def test_advanced_and_custom_packages_are_operational_and_do_not_expose_owner_only_refs() -> None:
    assert '"membros.silenciar"' in WEBAPP
    assert '"fixados.criar"' in WEBAPP
    advanced_section = WEBAPP.split("ADVANCED_ACTIONS", 1)[1].split("CUSTOM_PACKAGE", 1)[0]
    for removed in [
        '"convites.editar"',
        '"convites.revogar"',
        '"reacoes.mensagem.limpar"',
        '"reacoes.recentes.limpar"',
        '"reacoes.reactor.silenciar"',
        '"canais_remetentes.banir"',
        '"canais_remetentes.liberar"',
    ]:
        assert removed not in advanced_section
    for forbidden in [
        '"logs.ver"',
        '"historico.ver"',
        '"ddx.configurar"',
        '"entradas.aprovar"',
        '"mensagens.apagar_lote"',
        '"radio.broadcast"',
        '"topicos.criar"',
        '"convites.exportar_primario"',
    ]:
        assert forbidden in WEBAPP
    custom_section = WEBAPP.split("CUSTOM_ALLOWED_ACTIONS", 1)[1].split("WEBAPP_PACKAGES", 1)[0]
    assert "ADVANCED_ACTIONS" in custom_section


def test_ui_uses_banir_not_remover_member_label() -> None:
    assert "Banir membro" in ROUTER
    assert "Remover membro" not in ROUTER
    assert "Membro removido" not in ROUTER
    assert "Novo membro removido" not in ROUTER
