from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
GOV_WEBAPP = (ROOT / "app/equalizador/governante_webapp.py").read_text(encoding="utf-8")
RBAC = (ROOT / "app/equalizador/rbac_runtime.py").read_text(encoding="utf-8")
SEC = (ROOT / "app/equalizador/seguranca_avancada.py").read_text(encoding="utf-8")


def test_multimidia_owner_only_backend_and_js_guarded():
    assert 'module="multimidia"' in ROUTER
    assert 'if (!currentPalco || !modoMaestroPermitido) { renderMultimediaSessions([]); return; }' in ROUTER
    assert 'Multimídia nativa é restrita ao owner.' in ROUTER


def test_resolvers_pass_through_governante_scope_gate():
    assert '_require_governante_scope_for_any_action' in ROUTER
    assert 'actions=("mensagens.apagar", "fixados.criar", "fixados.remover")' in ROUTER
    assert 'actions=("membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar")' in ROUTER


def test_convite_exportar_primario_channel_aligned_between_js_and_backend():
    assert '"convites.exportar_primario": "convites.ver"' in ROUTER
    assert '"convites.exportar_primario": "convites.criar"' not in ROUTER
    assert '"convites.exportar_primario"' in GOV_WEBAPP
    assert 'convites.exportar_primario' in GOV_WEBAPP and 'FORBIDDEN_WEBAPP_ACTIONS' in GOV_WEBAPP


def test_ddx_temporario_is_legacy_and_not_in_main_diagnostic_group():
    assert 'DDX 10 minutos (legado)' in ROUTER
    assert '["ddx.imediato", "ddx.temporario", "novos.ver"' not in ROUTER


def test_member_label_is_banir_not_remover():
    for rel in [
        "app/equalizador/router.py",
        "app/equalizador/configuracao.py",
        "app/equalizador/painel.py",
        "app/equalizador/permissions.py",
        "app/equalizador/afinacao.py",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Remover membro" not in text
        assert "Remover membros" not in text
    assert "Banir membro" in ROUTER


def test_stable_hash_replaces_python_hash_for_refs():
    assert "import hashlib" in RBAC
    assert "_stable_ref_number" in RBAC
    assert "abs(hash(" not in RBAC
    assert "_stable_ref_number" in SEC
    assert "abs(hash(" not in SEC


def test_final_state_document_exists():
    final_doc = ROOT / "docs/FASE11_ESTADO_FINAL.md"
    assert final_doc.exists()
    text = final_doc.read_text(encoding="utf-8")
    assert "ESTADO FINAL CONSOLIDADO" in text
    assert "Multimídia nativa" in text
