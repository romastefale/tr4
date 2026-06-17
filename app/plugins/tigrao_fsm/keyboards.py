"""Utilitários de teclados do Tigrão FSM isolado.

Stub estrutural: cria especificações de botões e tenta usar recursos coloridos quando o aiogram instalado permitir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ButtonStyle = Literal["primary", "success", "danger"]
CALLBACK_PREFIX = "tgf:"
ALLOWED_BUTTON_STYLES: tuple[ButtonStyle, ...] = ("primary", "success", "danger")

@dataclass(frozen=True, slots=True)
class TigraoButtonSpec:
    text: str
    callback_data: str
    style: ButtonStyle = "primary"


def make_callback(session_id: str, *parts: str) -> str:
    clean_parts = [str(part).strip(":") for part in parts if str(part)]
    return f"{CALLBACK_PREFIX}{session_id}:" + ":".join(clean_parts)


def parse_callback(data: str) -> tuple[str, tuple[str, ...]] | None:
    if not data.startswith(CALLBACK_PREFIX):
        return None
    tail = data[len(CALLBACK_PREFIX):]
    if not tail:
        return None
    sid, *parts = tail.split(":")
    if not sid or any(len(part) > 48 for part in parts):
        return None
    return sid, tuple(parts)


def button(text: str, callback_data: str, *, style: ButtonStyle = "primary") -> TigraoButtonSpec:
    if style not in ALLOWED_BUTTON_STYLES:
        raise ValueError(f"unsupported Tigrão button style: {style}")
    if not callback_data.startswith(CALLBACK_PREFIX):
        raise ValueError("Tigrão callback must use the tgf: namespace")
    return TigraoButtonSpec(text=text, callback_data=callback_data, style=style)
