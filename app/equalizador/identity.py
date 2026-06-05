from __future__ import annotations

import hashlib
import hmac


def make_ui_ref(kind: str, raw_identifier: int | str, secret: str, *, size: int = 8) -> str:
    """Return a stable, non-reversible UI alias for an internal Telegram object.

    The raw Telegram identifier must stay server-side. This helper provides
    public aliases used by the Equalizador UI, for example ``usr_A91F2C00``
    for people, ``grp_A91F2C00`` for groups, ``ent_A91F2C00`` for join
    requests and ``inv_A91F2C00`` for invite links.
    """
    allowed_kinds = {"usr", "grp", "ent", "inv"}
    if kind not in allowed_kinds:
        raise ValueError("kind must be one of: ent, grp, inv, usr")
    if not secret:
        raise ValueError("secret is required to generate ui_ref")
    digest = hmac.new(
        secret.encode("utf-8"),
        str(raw_identifier).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{kind}_{digest[:size].upper()}"


def safe_public_username(value: object) -> str:
    """Return a public Telegram username without @, or an empty string."""
    raw = str(value or "").strip().lstrip("@")
    if not raw:
        return ""
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
    if 3 <= len(raw) <= 32 and all(ch in allowed for ch in raw):
        return raw
    return ""


def public_tme_url(username: object) -> str:
    """Return a t.me URL only when a valid public username exists."""
    safe_username = safe_public_username(username)
    return f"https://t.me/{safe_username}" if safe_username else ""


def display_name_from_telegram_user(user: dict[str, object], *, fallback: str = "Operador") -> str:
    """Return a safe display name without exposing username or numeric ID."""
    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if full_name:
        return full_name[:80]
    username = safe_public_username(user.get("username"))
    if username:
        return f"@{username}"[:80]
    return fallback[:80] if fallback else "Operador"
