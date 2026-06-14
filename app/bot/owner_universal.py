from __future__ import annotations

import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.music_command_runner import execute_universal_songcharts, execute_universal_tnow
from app.config.settings import is_code_owner

router = Router(name="owner_universal_music")


def _period_from_text(text: str | None) -> str:
    raw = (text or "").lower()
    if re.search(r"\b(month|mensal|mes|m[eê]s)\b", raw):
        return "month"
    return "week"


async def _deny_if_needed(message: Message) -> bool:
    if not message.from_user:
        return True
    if not is_code_owner(message.from_user.id):
        if message.chat.type == "private":
            await message.answer("Função musical exclusiva do dono do código.")
        return True
    if message.chat.type != "private":
        await message.answer("Use este comando na DM do bot. O resultado universal não é postado em grupo.")
        return True
    if not message.bot:
        return True
    return False


@router.message(Command("tnowall", "tnowuniversal"))
async def tnow_universal_owner(message: Message) -> None:
    if await _deny_if_needed(message):
        return
    await execute_universal_tnow(
        message.bot,
        requester_id=message.from_user.id,
        requester_name=message.from_user.full_name,
    )
    await message.answer("✓ Pedido aceito. O mosaico universal será enviado aqui na sua DM.")


@router.message(Command("songchartsall", "songchartsuniversal", "weekall", "monthall"))
async def songcharts_universal_owner(message: Message) -> None:
    if await _deny_if_needed(message):
        return
    command = (message.text or "").split(maxsplit=1)[0].lstrip("/").lower()
    if command == "monthall":
        period = "month"
    elif command == "weekall":
        period = "week"
    else:
        period = _period_from_text(message.text)
    await execute_universal_songcharts(
        message.bot,
        requester_id=message.from_user.id,
        requester_name=message.from_user.full_name,
        period=period,
    )
    label = "mensal" if period == "month" else "semanal"
    await message.answer(f"✓ Pedido aceito. O Songcharts universal {label} será enviado aqui na sua DM.")
