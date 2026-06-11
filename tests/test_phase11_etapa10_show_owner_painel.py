from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")


def test_show_owner_has_button_fsm_for_groups_users_packages_limits_and_exceptions():
    assert "CallbackQuery" in SHOW
    assert "InlineKeyboardMarkup" in SHOW
    assert 'callback_data="show:groups"' in SHOW
    assert 'callback_data="show:users"' in SHOW
    assert 'callback_data="show:packages"' in SHOW
    assert 'callback_data="show:limits"' in SHOW
    assert 'callback_data="show:exceptions"' in SHOW
    assert "grant_governante_package(" in SHOW
    assert "set_governante_daily_limit(" in SHOW
    assert "grant_governante_limit_exception(" in SHOW
    assert "revoke_governante_limit_exception(" in SHOW


def test_show_owner_custom_package_is_click_based_not_manual_payload():
    assert "CUSTOM_ALLOWED_ACTIONS" in SHOW
    assert 'callback_data=f"show:a:{idx}"' in SHOW
    assert 'callback_data="show:save_custom"' in SHOW
    assert "actions=list(state.get(\"actions\") or [])" in SHOW
    assert "pacote=CUSTOM_PACKAGE" in SHOW


def test_router_exposes_owner_visual_package_editor():
    assert 'id="gov_pkg_editor"' in ROUTER
    assert 'id="gov_pkg_usr_ref"' in ROUTER
    assert 'id="gov_pkg_grp_ref"' in ROUTER
    assert 'id="gov_pkg_pacote"' in ROUTER
    assert 'id="gov_pkg_actions"' in ROUTER
    assert 'id="gov_pkg_daily_limit"' in ROUTER
    assert 'id="gov_pkg_excecao_criar"' in ROUTER
    assert 'id="gov_pkg_excecao_revogar"' in ROUTER


def test_router_owner_visual_editor_calls_existing_owner_only_endpoints():
    assert "function renderGovernantePackages(data)" in ROUTER
    assert "function salvarGovernantePackageVisual()" in ROUTER
    assert "function salvarGovernanteDailyLimitVisual()" in ROUTER
    assert "function criarGovernanteExceptionVisual()" in ROUTER
    assert "function revogarGovernanteExceptionVisual()" in ROUTER
    assert 'api("/equalizador/api/governantes/pacotes"' in ROUTER
    assert '"/limites"' in ROUTER
    assert '"/excecoes"' in ROUTER
    assert '"/equalizador/api/governantes/excecoes/"' in ROUTER


def test_config_payload_includes_governante_scope_for_owner_editor():
    assert '"governante_scope": list_governante_scope_public' in ROUTER
    assert "renderGovernantePackages(data);" in ROUTER
    assert "ownerGovernanteScopePayload" in ROUTER
