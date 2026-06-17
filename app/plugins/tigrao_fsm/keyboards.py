"""Teclados seguros do Tigrão FSM isolado."""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Literal

ButtonStyle = Literal["primary", "success", "danger"]
CALLBACK_PREFIX = "tgf:"
MAX_CALLBACK_DATA_BYTES = 64
ALLOWED_BUTTON_STYLES: tuple[ButtonStyle, ...] = ("primary", "success", "danger")
_ALLOWED_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
CALLBACK_ACTIONS = frozenset({
    "home",
    "grp",
    "grp_sel",
    "logs",
    "log_mod",
    "log_music",
    "log_use",
    "log_join",
    "log_err",
    "join",
    "join_link",
    "join_auto",
    "join_pending",
    "ddx",
    "confirm",
    "back",
    "close",
})


@dataclass(frozen=True, slots=True)
class TigraoButtonSpec:
    text: str
    callback_data: str | None = None
    url: str | None = None
    copy_text: str | None = None
    style: ButtonStyle = "primary"


def _valid_token(value: str | None) -> bool:
    return bool(value) and ":" not in value and bool(_ALLOWED_TOKEN_RE.fullmatch(value))


def _callback_is_valid(data: str) -> bool:
    if not data or len(data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
        return False
    if not data.startswith(CALLBACK_PREFIX):
        return False
    tail = data[len(CALLBACK_PREFIX):]
    pieces = tail.split(":")
    if len(pieces) != 2:
        return False
    sid, action = pieces
    return _valid_token(sid) and _valid_token(action) and action in CALLBACK_ACTIONS


def make_callback(session_id: str, *parts: str) -> str:
    if not _valid_token(session_id):
        raise ValueError("invalid Tigrão session_id")
    if len(parts) != 1 or not _valid_token(parts[0]) or parts[0] not in CALLBACK_ACTIONS:
        raise ValueError("invalid Tigrão callback action")
    callback = f"{CALLBACK_PREFIX}{session_id}:{parts[0]}"
    if not _callback_is_valid(callback):
        raise ValueError("invalid or too long Tigrão callback_data")
    return callback


def parse_callback(data: str) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(data, str) or not _callback_is_valid(data):
        return None
    sid, action = data[len(CALLBACK_PREFIX):].split(":")
    return sid, (action,)


def _validate_single_action(callback_data: str | None, url: str | None, copy_text: str | None) -> None:
    actions = [callback_data is not None, url is not None, copy_text is not None]
    if sum(actions) != 1:
        raise ValueError("exactly one button action is required")
    if callback_data is not None and not _callback_is_valid(callback_data):
        raise ValueError("invalid internal Tigrão callback_data")
    if copy_text is not None and not (1 <= len(copy_text) <= 256):
        raise ValueError("copy_text must contain 1 to 256 characters")


def button(
    text: str,
    callback_data: str | None = None,
    *,
    url: str | None = None,
    copy_text: str | None = None,
    style: ButtonStyle = "primary",
) -> TigraoButtonSpec:
    if style not in ALLOWED_BUTTON_STYLES:
        raise ValueError(f"unsupported Tigrão button style: {style}")
    _validate_single_action(callback_data, url, copy_text)
    return TigraoButtonSpec(text=text, callback_data=callback_data, url=url, copy_text=copy_text, style=style)


def _button_kwargs(spec: TigraoButtonSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"text": spec.text}
    if spec.callback_data is not None:
        kwargs["callback_data"] = spec.callback_data
    elif spec.url is not None:
        kwargs["url"] = spec.url
    elif spec.copy_text is not None:
        try:
            from aiogram.types import CopyTextButton
        except Exception:
            kwargs["copy_text"] = spec.copy_text
        else:
            kwargs["copy_text"] = CopyTextButton(text=spec.copy_text)
    return kwargs


def to_inline_keyboard_button(spec: TigraoButtonSpec) -> Any:
    try:
        from aiogram.types import InlineKeyboardButton
    except Exception:
        return spec

    kwargs = _button_kwargs(spec)
    try:
        sig = inspect.signature(InlineKeyboardButton)
        if "style" in sig.parameters:
            kwargs["style"] = spec.style
    except (TypeError, ValueError):
        kwargs["style"] = spec.style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def to_inline_keyboard_markup(rows: list[list[TigraoButtonSpec]]) -> Any:
    keyboard = [[to_inline_keyboard_button(spec) for spec in row] for row in rows]
    try:
        from aiogram.types import InlineKeyboardMarkup
    except Exception:
        return keyboard
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def home_keyboard(session_id: str) -> list[list[TigraoButtonSpec]]:
    return [
        [button("Selecionar grupo", make_callback(session_id, "grp"), style="primary")],
        [button("Fechar", make_callback(session_id, "close"), style="danger")],
    ]
