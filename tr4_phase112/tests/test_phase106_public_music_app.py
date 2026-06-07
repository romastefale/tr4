from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_public_music_app_route_and_header_exist():
    assert '@router.get("/player"' in ROUTER
    assert 'tigraoRADIO' in ROUTER
    assert 'can_open_equalizador' in ROUTER
    assert 'Painel</a>' in ROUTER


def test_public_music_app_uses_initdata_not_equalizador_allowlist_for_home():
    assert 'def _public_identity_from_authorization' in ROUTER
    assert '@router.get("/api/public/home")' in ROUTER
    assert 'settings.equalizador_user_is_allowed(identity.user_id)' in ROUTER
