from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_storage_tables_are_defined() -> None:
    storage = read("app/plugins/tigrao_fsm/storage.py")
    for table in ["tigrao_logs", "tigrao_join_requests", "tigrao_join_auto_accept"]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in storage


def test_join_request_runtime_is_connected_in_plugin() -> None:
    plugin = read("app/plugins/tigrao_fsm/plugin.py")
    assert "join_request_handle" in plugin
    assert "if await join_request_handle(bot, update):" in plugin
    assert "return await ddx_handle(bot, update)" in plugin


def test_panel_has_join_request_and_log_screens() -> None:
    panel = read("app/plugins/tigrao_fsm/routers/panel.py")
    assert "Solicitações de entrada" in panel
    assert "Pendentes 2h" in panel
    assert "Criar link com solicitação" in panel or "join_link" in panel
    assert "Logs do Tigrão" in panel
    assert "Nenhum registro encontrado" not in panel  # formatado por services/storage


def test_create_join_request_link_removes_member_limit() -> None:
    services = read("app/plugins/tigrao_fsm/services.py")
    assert 'kwargs["creates_join_request"] = True' in services
    assert 'kwargs.pop("member_limit", None)' in services


def test_no_x9_was_added_and_destructive_actions_are_flagged() -> None:
    plugin_text = "\n".join(read(str(path.relative_to(ROOT))) for path in (ROOT / "app/plugins/tigrao_fsm").rglob("*.py"))
    settings = read("app/config/settings.py")
    assert "InlineQueryResult" not in plugin_text
    assert "delete_message_reaction" not in plugin_text
    assert "TIGRAO_FSM_DESTRUCTIVE_ACTIONS_ENABLED = _bool_env" in settings
    assert "TIGRAO_FSM_DDX_HARD_ENABLED = _bool_env" in settings


def test_forbidden_music_files_do_not_reference_tigrao() -> None:
    paths = [
        "app/bot/telegram.py",
        "app/bot/radiofm.py",
        "app/bot/tnow.py",
        "app/bot/tly.py",
        "app/bot/music_inline.py",
    ]
    paths.extend(str(p.relative_to(ROOT)) for p in (ROOT / "app/bot").glob("playing*.py"))
    paths.extend(str(p.relative_to(ROOT)) for p in (ROOT / "app/web_music").rglob("*.py"))
    for path in paths:
        if (ROOT / path).exists():
            assert "tigrao_fsm" not in read(path).lower()
