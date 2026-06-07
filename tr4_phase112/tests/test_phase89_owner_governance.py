from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_governance_sensitive_routes_are_maestro_only():
    for route in [
        '@router.get("/api/configuracao")',
        '@router.get("/api/palcos/{grp_ref}/governantes")',
        '@router.get("/api/permissoes/matriz")',
        '@router.get("/api/canais/distribuicao")',
    ]:
        idx = ROUTER.index(route)
        block = ROUTER[idx: idx + 900]
        assert 'if not _is_maestro(identity):' in block
        assert 'raise HTTPException(status_code=403, detail="Acesso indisponível.")' in block


def test_frontend_does_not_fetch_governantes_for_non_owner():
    assert 'modoMaestroPermitido ? api(base + "/governantes")' in ROUTER
    assert 'Promise.resolve({ governantes: [] })' in ROUTER


def test_owner_can_add_governante_from_panel_without_public_raw_id_summary():
    assert '@router.post("/api/rbac/operadores")' in ROUTER
    assert 'id="rbac_adicionar_governante"' in ROUTER
    assert 'Adicionar governante conhecido' in ROUTER
    assert 'O identificador informado é usado só para cadastro interno' in ROUTER
    assert 'telegram_user_id' in ROUTER
    assert '"usr_ref": operador["ui_ref"]' in ROUTER


def test_owner_panel_phase_class_enabled():
    assert 'phase89-owner-governance' in ROUTER
