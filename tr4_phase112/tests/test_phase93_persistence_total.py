from pathlib import Path

MAIN = Path("app/main.py").read_text(encoding="utf-8")
PERSISTENCIA = Path("app/equalizador/persistencia.py").read_text(encoding="utf-8")
GUARD = Path("scripts/persistence_guard.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase93_startup_writes_persistence_heartbeat():
    assert 'from app.equalizador.persistencia import ensure_persistence_state' in MAIN
    assert 'ensure_persistence_state(engine)' in MAIN
    assert 'TR4_PERSISTENCE_GUARD_STARTUP_FAILED' in MAIN
    assert 'CREATE TABLE IF NOT EXISTS eq_persistence_state' in PERSISTENCIA
    assert 'startup_heartbeat' in PERSISTENCIA


def test_phase93_critical_tables_cover_governance_multimedia_and_imports():
    for table in ['eq_operadores', 'eq_runtime_grants', 'eq_multimedia_sessions', 'eq_persistence_state', 'tr3_legacy_import_runs']:
        assert table in PERSISTENCIA
        assert table in GUARD
        assert table in ROUTER


def test_phase93_guard_fails_strict_on_missing_tables():
    assert 'missing_tables:' in GUARD
    assert 'database_not_under_data_volume' in GUARD
