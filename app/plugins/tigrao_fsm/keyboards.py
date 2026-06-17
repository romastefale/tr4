"""Teclados seguros do Tigrão FSM isolado."""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Literal

try:  # aiogram é opcional nesta fase isolada; fallback não deve quebrar import.
    from aiogram.types import CopyTextButton as _AiogramCopyTextButton
    from aiogram.types import InlineKeyboardButton as _AiogramInlineKeyboardButton
    from aiogram.types import InlineKeyboardMarkup as _AiogramInlineKeyboardMarkup
except Exception:  # pragma: no cover - depende da instalação local do aiogram.
    _AiogramCopyTextButton = None
    _AiogramInlineKeyboardButton = None
    _AiogramInlineKeyboardMarkup = None

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
    *(f"g{i}" for i in range(50)),
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


def _copy_text_button(value: str) -> Any | None:
    """Constrói CopyTextButton real ou informa que o fallback deve preservar o spec.

    A Bot API/aiogram esperam um objeto CopyTextButton; nunca passe string crua
    para InlineKeyboardButton.copy_text.
    """
    if _AiogramCopyTextButton is None:
        return None
    try:
        return _AiogramCopyTextButton(text=value)
    except TypeError:
        return None


def _button_kwargs(spec: TigraoButtonSpec) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {"text": spec.text}
    if spec.callback_data is not None:
        kwargs["callback_data"] = spec.callback_data
    elif spec.url is not None:
        kwargs["url"] = spec.url
    elif spec.copy_text is not None:
        copy_text_button = _copy_text_button(spec.copy_text)
        if copy_text_button is None:
            return None
        kwargs["copy_text"] = copy_text_button
    return kwargs


def to_inline_keyboard_button(spec: TigraoButtonSpec) -> Any:
    if _AiogramInlineKeyboardButton is None:
        return spec

    kwargs = _button_kwargs(spec)
    if kwargs is None:
        return spec
    try:
        sig = inspect.signature(_AiogramInlineKeyboardButton)
        if "style" in sig.parameters:
            kwargs["style"] = spec.style
    except (TypeError, ValueError):
        kwargs["style"] = spec.style
    try:
        return _AiogramInlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        try:
            return _AiogramInlineKeyboardButton(**kwargs)
        except TypeError:
            return spec


def to_inline_keyboard_markup(rows: list[list[TigraoButtonSpec]]) -> Any:
    keyboard = [[to_inline_keyboard_button(spec) for spec in row] for row in rows]
    if _AiogramInlineKeyboardMarkup is None:
        return keyboard
    try:
        return _AiogramInlineKeyboardMarkup(inline_keyboard=keyboard)
    except TypeError:
        return keyboard


def home_keyboard(session_id: str) -> list[list[TigraoButtonSpec]]:
    return [
        [button("Selecionar grupo", make_callback(session_id, "grp"), style="primary")],
        [button("Fechar", make_callback(session_id, "close"), style="danger")],
    ]


def group_selection_keyboard(session_id: str, groups: list[dict]) -> list[list[TigraoButtonSpec]]:
    rows: list[list[TigraoButtonSpec]] = []
    for idx, group in enumerate(groups[:50]):
        title = str(group.get("title") or group.get("username") or group.get("chat_id") or "Grupo")[:40]
        rows.append([button(title, make_callback(session_id, f"g{idx}"), style="primary")])
    rows.append([button("Voltar", make_callback(session_id, "back"), style="primary")])
    rows.append([button("Fechar", make_callback(session_id, "close"), style="danger")])
    return rows


def back_close_keyboard(session_id: str) -> list[list[TigraoButtonSpec]]:
    return [
        [button("Voltar", make_callback(session_id, "back"), style="primary")],
        [button("Fechar", make_callback(session_id, "close"), style="danger")],
    ]


def group_admin_keyboard(session_id: str) -> list[list[TigraoButtonSpec]]:
    return [
        [button("Logs", make_callback(session_id, "logs"), style="primary")],
        [button("Solicitações de entrada", make_callback(session_id, "join"), style="primary")],
        [button("Voltar", make_callback(session_id, "back"), style="primary")],
        [button("Fechar", make_callback(session_id, "close"), style="danger")],
    ]


def logs_keyboard(session_id: str) -> list[list[TigraoButtonSpec]]:
    return [
        [button("Moderação", make_callback(session_id, "log_mod"), style="primary")],
        [button("Música", make_callback(session_id, "log_music"), style="primary")],
        [button("Uso", make_callback(session_id, "log_use"), style="primary")],
        [button("Entradas", make_callback(session_id, "log_join"), style="primary")],
        [button("Erros", make_callback(session_id, "log_err"), style="primary")],
        [button("Voltar", make_callback(session_id, "back"), style="primary")],
        [button("Fechar", make_callback(session_id, "close"), style="danger")],
    ]
