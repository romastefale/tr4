from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.services.tnow_card import TnowEntry, build_tnow_card_html
from app.equalizador.erros_telegram import telegram_error_info

ROOT = Path(__file__).resolve().parents[1]


def read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_tnow_card_timezone_shadowing_fixed() -> None:
    html = build_tnow_card_html(
        [TnowEntry(user_id=1, display_name="Pi", track_name="Faixa", artist="Artista", cover_bytes=None, source="spotify")],
        now=datetime(2026, 6, 6, 6, 0, 0),
    )
    assert "03:00" in html
    assert "Pi" in html


def test_admin_title_preflight_is_wired_without_exposing_ids() -> None:
    admin = read("app/equalizador/admin.py")
    router = read("app/equalizador/router.py")
    assert "def ensure_admin_title_target_eligible" in admin
    assert 'if status == "creator"' in admin
    assert 'if status != "administrator"' in admin
    assert 'if ajuste == "admins.titulo"' in admin
    assert "promovido pelo próprio bot" in router


def test_admin_title_right_forbidden_message_is_specific() -> None:
    info = telegram_error_info(description="Bad Request: RIGHT_FORBIDDEN", status_code=400, error_code=400)
    assert info.category == "admin_title_not_bot_promoted"
    assert "promovido pelo próprio bot" in info.public_detail
