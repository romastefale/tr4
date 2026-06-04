from __future__ import annotations

import hashlib
import hmac


def make_ui_ref(kind: str, raw_identifier: int | str, secret: str, *, size: int = 8) -> str:
    """Return a stable, non-reversible UI alias for a Telegram identifier.

    The raw Telegram identifier must stay server-side. This helper provides the
    public alias used by the Equalizador UI, for example ``usr_A91F2C00``.
    """
    if kind not in {"usr", "grp"}:
        raise ValueError("kind must be 'usr' or 'grp'")
    if not secret:
        raise ValueError("secret is required to generate ui_ref")
    digest = hmac.new(
        secret.encode("utf-8"),
        str(raw_identifier).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{kind}_{digest[:size].upper()}"


def display_name_from_telegram_user(user: dict[str, object]) -> str:
    """Return a safe display name without exposing username or numeric ID."""
    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if full_name:
        return full_name[:80]
    return "Operador"
