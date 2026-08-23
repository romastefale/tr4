"""Inline musical TR4 — bootstrap public playing/tly."""
from __future__ import annotations

import logging
import urllib.request

logger = logging.getLogger(__name__)

_SRC_URL = (
    "https://raw.githubusercontent.com/romastefale/tr4/"
    "aefc7e2d3ec9860f83310a27635da69276d75b09/app/bot/music_inline.py"
)

def _load_and_patch() -> dict:
    with urllib.request.urlopen(_SRC_URL, timeout=45) as resp:
        src = resp.read().decode("utf-8")

    needle = (
        '_INLINE_MENU_KINDS: tuple[str, ...] = ("playing", "tly", "tcanvas", "week", "month", "mosaic")\n'
    )
    insert = needle + (
        '_INLINE_PUBLIC_KINDS: frozenset[str] = frozenset({"playing", "tly", "pick"})\n'
        '_INLINE_PUBLIC_MENU_KINDS: tuple[str, ...] = ("playing", "tly")\n'
    )
    if needle not in src:
        raise RuntimeError("menu kinds missing")
    src = src.replace(needle, insert, 1)

    old_imq = (
        "def is_music_inline_query(raw: str | None, *, owner: bool = False) -> bool:\n"
        "    if not (raw or \"\").strip():\n"
        "        return True\n"
        "    kind, _arg = _split_query(raw)\n"
        "    if kind is not None:\n"
        "        return True\n"
        "    return bool(owner)"
    )
    new_imq = (
        "def is_music_inline_query(raw: str | None, *, owner: bool = False) -> bool:\n"
        "    if not (raw or \"\").strip():\n"
        "        return True\n"
        "    kind, _arg = _split_query(raw)\n"
        "    if kind is None:\n"
        "        return True\n"
        "    if kind in _INLINE_PUBLIC_KINDS:\n"
        "        return True\n"
        "    return bool(owner)"
    )
    if old_imq not in src:
        raise RuntimeError("imq missing")
    src = src.replace(old_imq, new_imq, 1)

    old_render = (
        "async def _render(bot: Bot, item: _PendingInline) -> _InlineRender:\n"
        "    if not _is_owner(item.user_id):\n"
        '        logger.info("MUSIC_INLINE_RENDER_BLOCKED_NON_OWNER | user_id=%s | kind=%s", item.user_id, item.kind)\n'
        '        text = "Acesso restrito ao dono do código."\n'
        "        return _InlineRender(caption=text, fallback_text=text)\n"
        '    if item.kind == "playing":'
    )
    new_render = (
        "async def _render(bot: Bot, item: _PendingInline) -> _InlineRender:\n"
        "    if item.kind not in _INLINE_PUBLIC_KINDS and not _is_owner(item.user_id):\n"
        '        logger.info("MUSIC_INLINE_RENDER_BLOCKED_NON_OWNER | user_id=%s | kind=%s", item.user_id, item.kind)\n'
        '        text = "Acesso restrito ao dono do código."\n'
        "        return _InlineRender(caption=text, fallback_text=text)\n"
        '    if item.kind == "playing":'
    )
    if old_render not in src:
        raise RuntimeError("render missing")
    src = src.replace(old_render, new_render, 1)

    old_q = (
        "    if not _is_owner(query.from_user.id):\n"
        "        logger.info(\n"
        '            "MUSIC_INLINE_BLOCKED_NON_OWNER | user_id=%s | query=%s",\n'
        "            query.from_user.id,\n"
        '            (query.query or "")[:80],\n'
        "        )\n"
        "        await query.answer([], cache_time=1, is_personal=True)\n"
        "        return\n"
        "\n"
        "    def _make_result(item_kind: str, item_arg: str | None) -> InlineQueryResultArticle | None:\n"
        "        allowed = _is_owner(query.from_user.id)\n"
        "        if not allowed:\n"
        "            return None\n"
    )
    new_q = (
        "    is_owner = _is_owner(query.from_user.id)\n"
        "\n"
        "    def _kind_allowed(item_kind: str) -> bool:\n"
        "        return item_kind in _INLINE_PUBLIC_KINDS or is_owner\n"
        "\n"
        "    def _make_result(item_kind: str, item_arg: str | None) -> InlineQueryResultArticle | None:\n"
        "        if not _kind_allowed(item_kind):\n"
        "            return None\n"
        "        allowed = True\n"
    )
    if old_q not in src:
        raise RuntimeError("query gate missing")
    src = src.replace(old_q, new_q, 1)

    old_menu = (
        "        results = [\n"
        "            result\n"
        "            for item_kind in _INLINE_MENU_KINDS\n"
        "            for result in [_make_result(item_kind, None)]\n"
        "            if result is not None\n"
        "        ]\n"
        "        await query.answer(results, cache_time=0, is_personal=True)\n"
        "        return\n"
        "\n"
        '    if kind == "tly" and arg and not looks_like_spotify_track_reference(arg):'
    )
    new_menu = (
        "        menu_kinds = _INLINE_MENU_KINDS if is_owner else _INLINE_PUBLIC_MENU_KINDS\n"
        "        results = [\n"
        "            result\n"
        "            for item_kind in menu_kinds\n"
        "            for result in [_make_result(item_kind, None)]\n"
        "            if result is not None\n"
        "        ]\n"
        "        await query.answer(results, cache_time=0, is_personal=True)\n"
        "        return\n"
        "\n"
        "    if kind is not None and not _kind_allowed(kind):\n"
        "        logger.info(\n"
        '            "MUSIC_INLINE_BLOCKED_NON_OWNER | user_id=%s | kind=%s | query=%s",\n'
        "            query.from_user.id,\n"
        "            kind,\n"
        '            (query.query or "")[:80],\n'
        "        )\n"
        "        await query.answer([], cache_time=1, is_personal=True)\n"
        "        return\n"
        "\n"
        '    if kind == "tly" and arg and not looks_like_spotify_track_reference(arg):'
    )
    if old_menu not in src:
        raise RuntimeError("menu block missing")
    src = src.replace(old_menu, new_menu, 1)

    ns: dict = {"__name__": "app.bot.music_inline", "__file__": __file__}
    exec(compile(src, __file__, "exec"), ns)
    return ns


_NS = _load_and_patch()
router = _NS["router"]
is_music_inline_query = _NS["is_music_inline_query"]
