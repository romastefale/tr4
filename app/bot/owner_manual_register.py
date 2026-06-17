from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config.settings import is_code_owner
from app.db.database import SessionLocal
from app.models.lastfm_profile import LastfmProfile
from app.models.spotify_token import SpotifyToken
from app.services.lastfm import _clean_username, lastfm_service

logger = logging.getLogger(__name__)
router = Router(name="owner_manual_register")


def _parse_tmn_args(text: str | None) -> tuple[int, str]:
    parts = (text or "").strip().split(maxsplit=2)
    if len(parts) != 3:
        raise ValueError("uso")
    try:
        user_id = int(parts[1])
    except Exception as exc:
        raise ValueError("user_id") from exc
    if user_id <= 0:
        raise ValueError("user_id")
    username = _clean_username(parts[2])
    return user_id, username


async def _deny_if_needed(message: Message) -> bool:
    if not message.from_user:
        return True
    if not is_code_owner(message.from_user.id):
        if message.chat.type == "private":
            await message.answer("Função exclusiva do dono do código.")
        return True
    if message.chat.type != "private":
        try:
            if message.bot:
                await message.bot.send_message(
                    message.from_user.id,
                    "Use <code>/tmn user_id perfil_musical</code> na DM do bot.",
                    parse_mode="HTML",
                )
        except Exception:
            logger.debug("TMN_OWNER_DM_HINT_FAILED", exc_info=True)
        return True
    return False


def _clear_music_registration_rows(user_id: int) -> tuple[int, int]:
    with SessionLocal() as db:
        lastfm_deleted = (
            db.query(LastfmProfile)
            .filter(LastfmProfile.user_id == user_id)
            .delete(synchronize_session=False)
        )
        spotify_deleted = (
            db.query(SpotifyToken)
            .filter(SpotifyToken.user_id == user_id)
            .delete(synchronize_session=False)
        )
        db.commit()
    return int(lastfm_deleted or 0), int(spotify_deleted or 0)


@router.message(Command("tmn"))
async def tmn_manual_register(message: Message) -> None:
    if await _deny_if_needed(message):
        return

    try:
        target_user_id, lastfm_username = _parse_tmn_args(message.text)
    except ValueError:
        await message.answer(
            "Uso correto:\n"
            "<code>/tmn user_id perfil_musical</code>\n\n"
            "Exemplo:\n"
            "<code>/tmn 8505890439 usuario_exemplo</code>\n"
            "Também aceita <code>@usuario</code> ou URL do perfil musical.",
            parse_mode="HTML",
        )
        return

    try:
        lastfm_deleted, spotify_deleted = _clear_music_registration_rows(target_user_id)
        clean_username, _previous = await lastfm_service.set_username(target_user_id, lastfm_username)
    except Exception:
        logger.exception(
            "TMN_MANUAL_REGISTER_FAILED | owner_id=%s | target_user_id=%s",
            message.from_user.id,
            target_user_id,
        )
        await message.answer("Falha ao cadastrar manualmente. Verifique o user_id e o perfil musical informado.")
        return

    logger.info(
        "TMN_MANUAL_REGISTER_OK | owner_id=%s | target_user_id=%s | lastfm=%s | lastfm_deleted=%s | spotify_deleted=%s",
        message.from_user.id,
        target_user_id,
        clean_username,
        lastfm_deleted,
        spotify_deleted,
    )
    await message.answer(
        "✓ Cadastro manual limpo aplicado.\n\n"
        f"Telegram user_id: <code>{target_user_id}</code>\n"
        "Perfil musical atualizado.\n"
        f"Limpeza técnica: perfil_musical={lastfm_deleted}, conexao_musical={spotify_deleted}",
        parse_mode="HTML",
    )
