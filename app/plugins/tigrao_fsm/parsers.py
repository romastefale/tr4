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
    clean = (query or "").strip()
    if not clean.lower().startswith("x9"):
        return None
    if len(clean) > 2 and not clean[2].isspace() and clean[2] not in {":", "-"}:
        return None
    body = clean[2:].lstrip(" :-\t")
    return body or ""
