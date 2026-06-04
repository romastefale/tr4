import importlib
import sys


def test_invalid_equalizador_ids_do_not_break_settings_import(monkeypatch):
    monkeypatch.setenv("TR4_EQUALIZADOR_ENABLED", "true")
    monkeypatch.setenv("TR4_EQUALIZADOR_PALCO_IDS", "-100SEU_GRUPO_AQUI")
    sys.modules.pop("app.config.settings", None)
    settings = importlib.import_module("app.config.settings")
    assert settings.TR4_EQUALIZADOR_ENABLED is True
    assert settings.equalizador_allowed_palco_ids() == set()
    assert settings.equalizador_config_errors()
