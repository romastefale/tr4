from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')
RBAC = Path('app/equalizador/rbac_runtime.py').read_text(encoding='utf-8')


def test_phase94_governance_catalog_has_edit_remove_routes_owner_only():
    assert '@router.put("/api/rbac/operadores/{usr_ref}")' in ROUTER
    assert '@router.delete("/api/rbac/operadores/{usr_ref}")' in ROUTER
    route_slice = ROUTER[ROUTER.index('@router.put("/api/rbac/operadores/{usr_ref}")'):ROUTER.index('@router.get("/api/rbac/runtime")')]
    assert route_slice.count('if not _is_maestro(identity):') >= 2
    assert 'protected_user_ids=settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET' in route_slice


def test_phase94_governance_audit_table_and_public_output_exist():
    assert 'CREATE TABLE IF NOT EXISTS eq_governance_audit' in RBAC
    assert 'governante.atualizar' in RBAC
    assert 'governante.desativar' in RBAC
    assert 'list_governance_audit_public' in RBAC
    assert 'auditoria_governanca' in RBAC


def test_phase94_frontend_has_owner_catalog_controls_without_raw_log_exposure():
    assert 'Editar governante selecionado' in ROUTER
    assert 'rbac_atualizar_governante' in ROUTER
    assert 'rbac_remover_governante' in ROUTER
    assert 'rbac_auditoria_governanca' in ROUTER
    assert 'telegram_user_id' in ROUTER  # input exists only in owner-only config form
    assert 'console.log' not in ROUTER
