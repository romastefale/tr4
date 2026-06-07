from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
RBAC = Path("app/equalizador/rbac_runtime.py").read_text(encoding="utf-8")


def test_phase104_structured_rbac_errors_exist():
    assert "class RbacRuntimeError" in RBAC
    assert "rbac_runtime_error_payload" in RBAC
    assert "operador_indisponivel" in RBAC
    assert "canal_invalido" in RBAC
    assert "grupo_indisponivel" in RBAC


def test_phase104_route_returns_safe_structured_400():
    assert "rbac_runtime_invalido" in ROUTER
    assert "rbac_runtime_error_payload(exc)" in ROUTER
    assert "Concessão inválida ou alvo indisponível." not in ROUTER


def test_phase104_frontend_prevalidates_runtime_grant():
    assert "Escolha um governante conhecido para delegar." in ROUTER
    assert "Escolha o canal de permissão." in ROUTER
    assert "Delegação não aplicada. Revise governante, grupo e canal." in ROUTER
