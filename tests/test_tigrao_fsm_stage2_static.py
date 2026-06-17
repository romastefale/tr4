from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_callback_valid() -> None:
    from app.plugins.tigrao_fsm.keyboards import make_callback, parse_callback

    callback = make_callback("sid_123", "home")
    assert callback == "tgf:sid_123:home"
    assert parse_callback(callback) == ("sid_123", ("home",))


def test_callback_above_64_bytes_rejected() -> None:
    from app.plugins.tigrao_fsm.keyboards import make_callback, parse_callback

    with pytest.raises(ValueError):
        make_callback("s" * 60, "confirm")
    assert parse_callback("tgf:" + "s" * 60 + ":confirm") is None


def test_callback_with_internal_colon_rejected() -> None:
    from app.plugins.tigrao_fsm.keyboards import make_callback, parse_callback

    with pytest.raises(ValueError):
        make_callback("sid:bad", "home")
    with pytest.raises(ValueError):
        make_callback("sid", "ho:me")
    assert parse_callback("tgf:sid:home:extra") is None


def test_empty_callback_rejected() -> None:
    from app.plugins.tigrao_fsm.keyboards import parse_callback

    assert parse_callback("") is None


def test_internal_button_rejects_url_with_callback_data() -> None:
    from app.plugins.tigrao_fsm.keyboards import button, make_callback

    with pytest.raises(ValueError):
        button("bad", make_callback("sid", "home"), url="https://example.com")


def test_parse_multiple_ids_and_invalids() -> None:
    from app.plugins.tigrao_fsm.parsers import parse_user_ids

    parsed = parse_user_ids("123456789 987654321, 555444333\n777888999 123456789")
    assert parsed.valid == [123456789, 987654321, 555444333, 777888999]
    assert parsed.invalid == []


def test_parse_user_ids_rejects_negative_username_and_text() -> None:
    from app.plugins.tigrao_fsm.parsers import parse_user_ids

    parsed = parse_user_ids("123 -456 @usuario texto -100987")
    assert parsed.valid == [123]
    assert parsed.invalid == ["-456", "@usuario", "texto", "-100987"]


def test_x9_only_accepts_explicit_prefix() -> None:
    from app.plugins.tigrao_fsm.parsers import parse_x9_query

    assert parse_x9_query("x9 123 456") == "123 456"
    assert parse_x9_query("123 456") is None
    assert parse_x9_query("xx9 123") is None


def test_private_panel_surface_only_private() -> None:
    from app.plugins.tigrao_fsm.permissions import is_private_panel_surface

    assert is_private_panel_surface("private") is True
    assert is_private_panel_surface("group") is False
    assert is_private_panel_surface("supergroup") is False
    assert is_private_panel_surface("channel") is False


def test_main_py_does_not_import_tigrao_plugin() -> None:
    assert "app.plugins.tigrao_fsm" not in read("app/main.py")


def test_telegram_py_not_altered_for_tigrao() -> None:
    assert "tigrao_fsm" not in read("app/bot/telegram.py").lower()


def test_music_files_do_not_reference_tigrao() -> None:
    paths = [
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
