from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_governance_persistence_public_is_imported_for_config_route():
    import_block = ROUTER.split("from app.equalizador.rbac_runtime import (", 1)[1].split(")", 1)[0]
    assert "governance_persistence_public" in import_block


def test_configuracao_uses_imported_governance_persistence():
    assert '"governanca_persistencia": governance_persistence_public(' in ROUTER
    assert '@router.get("/api/configuracao")' in ROUTER
    assert '@router.get("/api/rbac/persistencia")' in ROUTER
