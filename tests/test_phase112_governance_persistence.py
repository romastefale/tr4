from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
RBAC = Path("app/equalizador/rbac_runtime.py").read_text(encoding="utf-8")


def test_phase112_owner_only_governance_persistence_route_exists():
    assert '"/api/rbac/persistencia"' in ROUTER
    assert 'governance_persistence_public' in ROUTER
    assert 'if not _is_maestro(identity)' in ROUTER


def test_phase112_governance_persistence_is_sanitized_counts_only():
    assert 'governantes_ativos' in RBAC
    assert 'concessoes_ativas' in RBAC
    assert 'eventos_auditoria' in RBAC
    assert 'raw Telegram IDs' in RBAC
    assert 'database paths' in RBAC


def test_phase112_config_shows_governance_persistence_summary():
    assert 'config_governanca_persistencia' in ROUTER
    assert 'governanca_persistencia' in ROUTER
    assert 'Persistência:' in ROUTER
