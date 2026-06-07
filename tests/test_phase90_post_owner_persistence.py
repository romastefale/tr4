from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
SETTINGS = Path("app/config/settings.py").read_text(encoding="utf-8")
PERSISTENCE_GUARD = Path("scripts/persistence_guard.py").read_text(encoding="utf-8")


def test_phase90_bot_summary_hides_governante_count_for_non_owner():
    assert "async def _bot_public_summary(*, is_maestro: bool = False)" in ROUTER
    assert "if is_maestro:" in ROUTER
    assert '"operadores_autorizados"' in ROUTER
    assert 'return await _bot_public_summary(is_maestro=_is_maestro(identity))' in ROUTER
    assert 'if (typeof stats.operadores_autorizados === "number") partes.push' in ROUTER


def test_phase90_raw_preview_is_owner_only():
    start = ROUTER.index('@router.post("/api/configuracao/raw-preview")')
    block = ROUTER[start:start + 500]
    assert 'if not _is_maestro(identity):' in block
    assert 'raise HTTPException(status_code=403' in block
    assert 'filter_palco_ids_by_canal_effective' not in block


def test_phase90_persistence_status_is_owner_only_and_translated():
    assert '@router.get("/api/persistencia/status")' in ROUTER
    start = ROUTER.index('@router.get("/api/persistencia/status")')
    block = ROUTER[start:start + 450]
    assert 'if not _is_maestro(identity):' in block
    assert '"persistencia": _persistence_status_public()' in block
    assert '"local": "volume" if under_volume else "container"' in ROUTER
    assert '"persistente": under_volume' in ROUTER


def test_phase90_configuration_includes_persistence_panel():
    assert 'id="persistencia_status"' in ROUTER
    assert 'function renderPersistencia(persistencia)' in ROUTER
    assert 'renderPersistencia(data.persistencia || {})' in ROUTER
    assert '"persistencia": _persistence_status_public()' in ROUTER


def test_phase90_persistence_prefers_data_volume():
    assert 'RAILWAY_VOLUME_MOUNT_PATH' in SETTINGS
    assert 'return data_path' in SETTINGS
    assert 'under_data' in PERSISTENCE_GUARD
    assert 'database_not_under_data_volume' in PERSISTENCE_GUARD
