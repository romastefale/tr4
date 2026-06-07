from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase95_owner_only_permissions_audit_endpoint_exists():
    assert '@router.get("/api/permissoes/auditoria")' in ROUTER
    block = ROUTER[ROUTER.index('@router.get("/api/permissoes/auditoria")'):ROUTER.index('@router.get("/api/configuracao")')]
    assert 'if not _is_maestro(identity):' in block
    assert 'Acesso indisponível.' in block


def test_phase95_sensitive_manifest_includes_governance_and_config_routes():
    assert '"rota": "/api/configuracao"' in ROUTER
    assert '"rota": "/api/rbac/runtime"' in ROUTER
    assert '"rota": "/api/rbac/operadores"' in ROUTER
    assert '"rota": "/api/palcos/{grp_ref}/governantes"' in ROUTER
    assert '"exposicao": "sem ids brutos, sem tokens, sem caminhos absolutos"' in ROUTER


def test_phase95_config_panel_renders_permissions_audit_without_sensitive_paths():
    assert 'config_permissoes_auditoria_resumo' in ROUTER
    assert 'config_permissoes_auditoria' in ROUTER
    assert 'auditoria_permissoes' in ROUTER
    assert 'sem exposição sensível' in ROUTER
