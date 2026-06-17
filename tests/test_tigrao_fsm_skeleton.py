from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "app" / "plugins" / "tigrao_fsm"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tigrao_fsm_folder_exists() -> None:
    assert PLUGIN.is_dir()


def test_plugin_does_not_import_app_main() -> None:
    assert "app.main" not in "\n".join(read(path) for path in PLUGIN.rglob("*.py"))


def test_main_py_not_changed_to_import_internal_tigrao_fsm_plugin() -> None:
    main_py = read(ROOT / "app" / "main.py")
    assert "app.plugins.tigrao_fsm" not in main_py


def test_callback_namespace_is_own_prefix() -> None:
    from app.plugins.tigrao_fsm.keyboards import CALLBACK_PREFIX, make_callback, parse_callback

    callback = make_callback("abc123", "logs")
    assert CALLBACK_PREFIX == "tgf:"
    assert callback == "tgf:abc123:logs"
    assert parse_callback(callback) == ("abc123", ("logs",))


def test_plugin_documentation_exists() -> None:
    readme = PLUGIN / "README.md"
    assert readme.is_file()
    text = read(readme)
    assert "Ainda não conectado ao TR4" in text


def test_no_active_dispatcher_connection_in_skeleton() -> None:
    plugin_text = "\n".join(read(path) for path in PLUGIN.rglob("*.py"))
    assert ".include_router(" not in plugin_text
    assert "feed_update" not in plugin_text


def test_no_public_group_panel_response_is_implemented() -> None:
    from app.plugins.tigrao_fsm.permissions import is_private_panel_surface

    assert is_private_panel_surface("group") is False
    assert is_private_panel_surface("supergroup") is False
    assert is_private_panel_surface("private") is True
