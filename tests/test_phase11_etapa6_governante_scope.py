from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
SCOPE = (ROOT / "app/equalizador/governante_scope.py").read_text(encoding="utf-8")
WEBAPP = (ROOT / "app/equalizador/governante_webapp.py").read_text(encoding="utf-8")


def test_governante_scope_has_persistent_assignment_and_limit_tables() -> None:
    assert "CREATE TABLE IF NOT EXISTS eq_governante_assignments" in SCOPE
    assert "telegram_user_id INTEGER NOT NULL" in SCOPE
    assert "telegram_chat_id INTEGER NOT NULL" in SCOPE
    assert "pacote TEXT NOT NULL" in SCOPE
    assert "CREATE TABLE IF NOT EXISTS eq_governante_daily_limits" in SCOPE
    assert "CREATE TABLE IF NOT EXISTS eq_governante_daily_usage" in SCOPE


def test_backend_enforces_package_scope_on_operational_actions() -> None:
    assert "def _require_governante_scope_for_action" in ROUTER
    assert "require_governante_action(" in ROUTER
    assert 'action=ajuste' in ROUTER
    assert 'action="broadcast.musical.webapp"' in ROUTER
    assert 'action="mensagens.apagar_lote"' in ROUTER
    assert 'action_code = f"convites.{acao}"' in ROUTER


def test_owner_endpoints_manage_governante_package_and_daily_limit_base() -> None:
    assert '@router.get("/api/governantes/pacotes")' in ROUTER
    assert '@router.post("/api/governantes/pacotes")' in ROUTER
    assert '@router.delete("/api/governantes/pacotes/{assignment_ref}")' in ROUTER
    assert '@router.post("/api/governantes/pacotes/{assignment_ref}/limites")' in ROUTER
    assert "grant_governante_package(" in ROUTER
    assert "set_governante_daily_limit(" in ROUTER


def test_me_payload_exposes_governante_scope_for_ui_gating() -> None:
    assert '"governante_scope": scope_for_user_public(' in ROUTER
    assert "governanteActionsPorPalco" in ROUTER
    assert "packageAllowsAction" in ROUTER
    assert "applyGovernanteScopeUI" in ROUTER
    assert "Ação fora do pacote governante" in ROUTER or "ação fora do pacote governante" in ROUTER


def test_forbidden_webapp_actions_remain_out_of_packages() -> None:
    assert '"mensagens.apagar_lote"' in WEBAPP
    assert '"ddx.configurar"' in WEBAPP
    assert '"logs.ver"' in WEBAPP
    for forbidden in ("mensagens.apagar_lote", "ddx.configurar", "logs.ver", "kick"):
        assert forbidden not in WEBAPP.split("WEBAPP_PACKAGES", 1)[1].split("OWNER_ONLY_ACTIONS", 1)[0]
