from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
SETTINGS = Path("app/config/settings.py").read_text(encoding="utf-8")
SCRIPT = Path("scripts/tr4_release_readiness.py").read_text(encoding="utf-8")


def test_public_music_status_route_exists_and_is_sanitized():
    assert '@router.get("/api/public/status")' in ROUTER
    assert 'def public_music_status()' in ROUTER
    assert 'musica_publica_sem_curtidas' in ROUTER
    assert 'visivel_apenas_para_operador_autorizado' in ROUTER


def test_led_reactions_disabled_by_default():
    assert 'TR4_MUSIC_REACTIONS_ENABLED = _bool_env("TR4_MUSIC_REACTIONS_ENABLED", False' in SETTINGS


def test_release_readiness_script_checks_known_regressions():
    assert 'governance_persistence_public' in SCRIPT
    assert '/equalizador/player' in SCRIPT
    assert 'musica_publica_sem_curtidas' in SCRIPT
