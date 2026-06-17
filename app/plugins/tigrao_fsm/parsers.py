"""Parsers isolados do Tigrão FSM."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SPLIT_RE = re.compile(r"[\s,]+")

@dataclass(frozen=True, slots=True)
class ParsedUserIds:
    valid: list[int]
    invalid: list[str]


def parse_user_ids(text: str) -> ParsedUserIds:
    seen: set[int] = set()
    valid: list[int] = []
    invalid: list[str] = []
    for token in [t for t in _SPLIT_RE.split((text or "").strip()) if t]:
        if not token.isdecimal():
            invalid.append(token)
            continue
        value = int(token)
        if value <= 0:
            invalid.append(token)
            continue
        if value not in seen:
            seen.add(value)
            valid.append(value)
    return ParsedUserIds(valid=valid, invalid=invalid)


def parse_x9_query(query: str) -> str | None:
    raw = query or ""
    clean = raw.strip()
    lowered = clean.casefold()
    if lowered == "x9":
        return ""
    if not lowered.startswith("x9 "):
        return None
    return clean[3:].strip()
