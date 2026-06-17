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


def test_copy_text_button_builds_real_or_safe_fallback() -> None:
    from app.plugins.tigrao_fsm.keyboards import TigraoButtonSpec, button, to_inline_keyboard_button

    spec = button("Copiar", copy_text="https://example.com/convite")
    built = to_inline_keyboard_button(spec)
    if isinstance(built, TigraoButtonSpec):
        assert built.copy_text == "https://example.com/convite"
    else:
        assert getattr(built, "copy_text", None) is not None
        copy_text = getattr(built, "copy_text")
        assert getattr(copy_text, "text", copy_text) == "https://example.com/convite"


def test_copy_text_size_is_validated() -> None:
    from app.plugins.tigrao_fsm.keyboards import button

    with pytest.raises(ValueError):
        button("vazio", copy_text="")
    with pytest.raises(ValueError):
        button("grande", copy_text="x" * 257)


def test_future_callback_action_is_valid_and_unknown_action_rejected() -> None:
    from app.plugins.tigrao_fsm.keyboards import make_callback, parse_callback

    callback = make_callback("sid", "join_pending")
    assert parse_callback(callback) == ("sid", ("join_pending",))
    with pytest.raises(ValueError):
        make_callback("sid", "unknown")
    assert parse_callback("tgf:sid:unknown") is None


@pytest.mark.asyncio
async def test_approve_pending_join_request_detail_with_and_without_username() -> None:
    from datetime import datetime, timezone

    from app.plugins.tigrao_fsm.models import TigraoJoinRequest
    from app.plugins.tigrao_fsm.services import approve_pending_join_request

    class Bot:
        async def approve_chat_join_request(self, *, chat_id: int, user_id: int) -> None:
            assert chat_id
            assert user_id

    base = dict(
        chat_id=-100123,
        chat_title="Grupo",
        user_id=123,
        full_name="Nome Sobrenome",
        user_chat_id=777,
        bio=None,
        invite_link="https://t.me/+abc",
        request_date=datetime(2026, 6, 17, tzinfo=timezone.utc),
        received_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        expires_at=datetime(2026, 6, 17, 2, tzinfo=timezone.utc),
    )
    with_username = TigraoJoinRequest(username="usuario", **base)
    detail = await approve_pending_join_request(Bot(), with_username, processed_by=1, autoaccept=True, origin="ID autorizado no painel")
    assert detail == with_username.result_detail
    assert "Username: @usuario" in detail
    assert "ID: 123" in detail
    assert "Autoaceite: sim" in detail

    without_username = TigraoJoinRequest(username=None, **{**base, "user_id": 456})
    detail = await approve_pending_join_request(Bot(), without_username, processed_by=1, autoaccept=False, origin="aprovação manual")
    assert detail == without_username.result_detail
    assert "Username: não informado" in detail
    assert "ID: 456" in detail
    assert "Autoaceite: não" in detail


@pytest.mark.asyncio
async def test_ddx_does_not_delete_without_filter_or_permission() -> None:
    from dataclasses import dataclass
    from types import SimpleNamespace

    from app.plugins.tigrao_fsm.runtime.ddx_runtime import DDXConfig, handle

    class Bot:
        def __init__(self) -> None:
            self.deleted = []

        async def delete_message(self, chat_id: int, message_id: int) -> None:
            self.deleted.append((chat_id, message_id))

    @dataclass(frozen=True)
    class Perms:
        can_delete_messages: bool

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-100, type="supergroup"),
        message_id=10,
        text="apagar isto",
        caption=None,
    )
    bot = Bot()
    assert await handle(bot, message, config=DDXConfig(active=True, filter_text=None), permissions=Perms(True)) is False
    assert await handle(bot, message, config=DDXConfig(active=True, filter_text="apagar"), permissions=None) is False
    assert await handle(bot, message, config=DDXConfig(active=True, filter_text="apagar"), permissions=Perms(False)) is False
    assert bot.deleted == []


@pytest.mark.asyncio
async def test_ddx_requires_matching_text_or_caption() -> None:
    from dataclasses import dataclass
    from types import SimpleNamespace

    from app.plugins.tigrao_fsm.runtime.ddx_runtime import DDXConfig, handle

    class Bot:
        async def delete_message(self, chat_id: int, message_id: int) -> None:
            raise AssertionError("should not delete")

    @dataclass(frozen=True)
    class Perms:
        can_delete_messages: bool = True

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-100, type="supergroup"),
        message_id=10,
        text="texto seguro",
        caption="legenda segura",
    )
    assert await handle(Bot(), message, config=DDXConfig(active=True, filter_text="bloqueado"), permissions=Perms()) is False


def test_x9_rejects_colon_and_dash_forms() -> None:
    from app.plugins.tigrao_fsm.parsers import parse_x9_query

    assert parse_x9_query("x9") == ""
    assert parse_x9_query("x9 alvo") == "alvo"
    assert parse_x9_query("x9: alvo") is None
    assert parse_x9_query("x9-alvo") is None
    assert parse_x9_query("xx9 alvo") is None
    assert parse_x9_query("123 456") is None
