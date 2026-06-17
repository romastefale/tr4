from __future__ import annotations

import base64
import html
import io
import math
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

CARD_WIDTH = 1080
MAX_CARD_ASPECT_HEIGHT_OVER_WIDTH = 16 / 9
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "tnow_card.html"

# Menor matriz confortável para cada quantidade real de tiles. A capacidade
# pode ser maior que a quantidade renderizada, mas nunca menor.
_GRID_LAYOUTS: tuple[tuple[int, int], ...] = (
    (1, 1),   # 1
    (1, 2),   # 2
    (1, 3),   # 3
    (2, 2),   # 4
    (2, 3),   # 5-6
    (2, 4),   # 7-8
    (3, 3),   # 9
    (2, 5),   # 10
    (3, 4),   # 11-12
    (3, 5),   # 13-15
    (4, 4),   # 16
    (4, 5),   # 17-20
    (5, 5),   # 21-25
)


@dataclass(frozen=True)
class TnowEntry:
    user_id: int
    display_name: str
    track_name: str
    artist: str
    cover_bytes: bytes | None
    source: str  # provedor técnico interno; não aparece visualmente no card
    status: str = "live"
    age_minutes: int | None = None


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


FALLBACK_COVER = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 240'>"
    "<defs><linearGradient id='g' x1='0' x2='1' y1='0' y2='1'>"
    "<stop offset='0%' stop-color='%235B9CFF'/>"
    "<stop offset='55%' stop-color='%23B58CFE'/>"
    "<stop offset='100%' stop-color='%233FE0A6'/>"
    "</linearGradient></defs>"
    "<rect width='240' height='240' fill='url(%23g)'/>"
    "<circle cx='120' cy='120' r='52' fill='rgba(255,255,255,.18)'/>"
    "</svg>"
)

_STATUS_CLASS = {
    "live": "live",
    "recent_15": "recent-15",
    "recent_30": "recent-30",
    "recent_45": "recent-45",
    "recent_120": "recent-120",
}

_STATUS_LABEL = {
    "live": "AO VIVO",
    "recent_15": "até 15min",
    "recent_30": "15–30min",
    "recent_45": "30–45min",
    "recent_120": "45min–2h",
}


def _cover_data_uri(raw: bytes | None, *, max_dim: int = 480) -> str | None:
    """Encode cover bytes into an inline JPEG data URI, safe for Chromium."""
    if not raw:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            largest = max(img.size)
            if largest > max_dim:
                scale = max_dim / largest
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        logger.debug("TNOW_COVER_ENCODE_FAILED", exc_info=True)
        return None


def _choose_grid_layout(n: int) -> tuple[int, int, int]:
    """Menor grade com capacidade suficiente para n tiles reais."""
    if n <= 0:
        return 0, 0, 0
    needed = min(max(1, int(n)), 25)
    for rows, columns in _GRID_LAYOUTS:
        capacity = rows * columns
        if capacity >= needed:
            return rows, columns, capacity
    return 5, 5, 25


def _columns_for(n: int) -> int:
    """Colunas da grade adaptativa.

    O layout acomoda a quantidade real de usuários válidos. Pode sobrar pouco
    espaço visual, mas a grade nunca corta usuário válido para fechar matriz.
    """
    _rows, columns, _capacity = _choose_grid_layout(n)
    return max(1, columns)


def _status_class(entry: TnowEntry) -> str:
    return _STATUS_CLASS.get(entry.status, "recent-120")


def _age_label(entry: TnowEntry) -> str:
    if entry.status == "live":
        return "AO VIVO"
    minutes = int(entry.age_minutes or 0)
    if minutes < 60:
        return f"há {minutes}min"
    hours = minutes // 60
    rest = minutes % 60
    if rest:
        return f"há {hours}h{rest:02d}"
    return f"há {hours}h"


def _tile_html(entry: TnowEntry) -> str:
    cover = _cover_data_uri(entry.cover_bytes) or FALLBACK_COVER
    status_class = _status_class(entry)
    status_label = _STATUS_LABEL.get(entry.status, "45min–2h")
    age_label = _age_label(entry)
    return (
        '<div class="tile">'
        '<div class="cover-wrap">'
        f'<img class="cover" src="{_esc(cover)}" alt=""/>'
        f'<span class="status-dot status-{_esc(status_class)}" title="{_esc(status_label)}"></span>'
        f'<span class="age-pill age-{_esc(status_class)}">{_esc(age_label)}</span>'
        '</div>'
        '<div class="info">'
        f'<div class="who">{_esc(entry.display_name)}</div>'
        f'<div class="track">{_esc(entry.track_name)}</div>'
        f'<div class="artist">{_esc(entry.artist)}</div>'
        '</div>'
        '</div>'
    )


def _normalize_card_image(raw: bytes) -> bytes:
    """Garante saída entre quadrada e vertical 9:16, preservando conteúdo.

    A função não corta tiles: só adiciona padding lateral/inferior quando a
    captura fica horizontal demais ou vertical demais. A condição final é
    matemática: 1.0 <= height / width <= 16 / 9.
    """
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            width, height = img.size
            if width <= 0 or height <= 0:
                return raw

            target_width = width
            target_height = height

            # Nunca mais horizontal que quadrado.
            if target_height < target_width:
                target_height = target_width

            # Nunca mais vertical que 9:16. Sem corte: aumenta a largura com
            # padding para cumprir height <= width * 16/9.
            min_width_for_vertical_limit = int(math.ceil(target_height / MAX_CARD_ASPECT_HEIGHT_OVER_WIDTH))
            if target_width < min_width_for_vertical_limit:
                target_width = min_width_for_vertical_limit

            # Reconfirma o limite depois dos arredondamentos.
            max_allowed_height = int(math.floor(target_width * MAX_CARD_ASPECT_HEIGHT_OVER_WIDTH))
            if target_height > max_allowed_height:
                target_width = int(math.ceil(target_height / MAX_CARD_ASPECT_HEIGHT_OVER_WIDTH))

            if (target_width, target_height) != img.size:
                canvas = Image.new("RGB", (target_width, target_height), (11, 10, 26))
                left = max(0, (target_width - img.width) // 2)
                top = max(0, (target_height - img.height) // 2)
                canvas.paste(img, (left, top))
                img = canvas
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, optimize=True)
            return buf.getvalue()
    except Exception:
        logger.debug("TNOW_CARD_ASPECT_NORMALIZE_FAILED", exc_info=True)
        return raw


def build_tnow_card_html(entries: list[TnowEntry], *, now: datetime | None = None) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    columns = _columns_for(len(entries))
    tiles = "\n".join(_tile_html(e) for e in entries) or "<div></div>"
    # Stamp visual: "23/05 • 18:42 BRT" usando hora local Brasília (UTC-3).
    local = now
    try:
        local = now.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-3)))
    except Exception:
        logger.debug("tnow_card timezone conversion failed", exc_info=True)
    stamp_value = local.strftime("%d/%m • %H:%M")
    stamp_iso = local.strftime("%Y-%m-%d %H:%M BRT")
    values = {
        "count": str(len(entries)),
        "columns": str(columns),
        "tiles": tiles,
        "stamp_value": _esc(stamp_value),
        "stamp_iso": _esc(stamp_iso),
    }
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", str(value))
    return template


async def render_tnow_card(entries: list[TnowEntry]) -> bytes | None:
    """Render the /tnow mosaic card to JPEG bytes via Playwright/Chromium.

    Returns None when Playwright is unavailable or rendering fails. Callers
    should fall back to a textual response in that case.
    """
    if not entries:
        return None
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except Exception:
        logger.warning("TNOW_CARD_RENDER_UNAVAILABLE | reason=playwright_import_failed", exc_info=True)
        return None

    html_content = build_tnow_card_html(entries)
    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(args=["--no-sandbox"])
            page = await browser.new_page(
                viewport={"width": CARD_WIDTH, "height": 1920},
                device_scale_factor=2,
            )
            await page.set_content(html_content, wait_until="networkidle", timeout=20000)
            try:
                await page.evaluate("document.fonts && document.fonts.ready")
            except Exception:
                logger.debug("TNOW_CARD_FONTS_READY_FAILED", exc_info=True)
            card = page.locator(".card").first
            await card.wait_for(state="visible", timeout=20000)
            raw = await card.screenshot(type="jpeg", quality=90, timeout=20000)
            return _normalize_card_image(raw)
    except Exception:
        logger.exception("TNOW_CARD_RENDER_FAILED | n=%s", len(entries))
        return None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.warning("TNOW_CARD_BROWSER_CLOSE_FAILED", exc_info=True)
