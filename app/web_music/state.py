from __future__ import annotations

from aiogram import Bot

_bot: Bot | None = None


def set_web_music_bot(bot: Bot | None) -> None:
    global _bot
    _bot = bot


def get_web_music_bot() -> Bot | None:
    return _bot
