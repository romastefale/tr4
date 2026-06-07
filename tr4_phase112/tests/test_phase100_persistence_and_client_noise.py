from pathlib import Path

SETTINGS = Path("app/config/settings.py").read_text(encoding="utf-8")
PERSISTENCIA = Path("app/equalizador/persistencia.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase100_prefers_data_volume_over_ephemeral_explicit_dir():
    assert 'if data_writable:' in SETTINGS
    assert 'return data_path' in SETTINGS
    assert 'DATA_DIR=/app/data' in SETTINGS


def test_phase100_persistence_guard_checks_database_url_path():
    assert 'make_url(DATABASE_URL)' in PERSISTENCIA
    assert 'db_path == "/data/app.db"' in PERSISTENCIA
    assert 'db_path.startswith("/data/")' in PERSISTENCIA


def test_phase100_client_initdata_event_not_logged_as_warning():
    assert 'logger.info if kind in {"initdata_ausente", "initdata_ausente_usando_sessao"}' in ROUTER
    assert 'EQUALIZADOR_CLIENT_EVENT' in ROUTER


def test_phase100_favicon_route_removes_404_noise():
    assert '@router.get("/favicon.ico", include_in_schema=False)' in ROUTER
    assert 'image/svg+xml' in ROUTER
