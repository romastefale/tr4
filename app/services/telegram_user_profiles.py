from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.db.database import SessionLocal
from app.models.telegram_user_profile import TelegramUserProfile
from app.services.tnow_privacy import TPV_DEFAULT_LABEL, tnow_privacy_service
from app.utils.datetime import utcnow_naive

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramProfileHit:
    user_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    full_name: str | None = None
    photo_url: str | None = None
    language_code: str | None = None
    source: str | None = None


def _clean_text(value: object, *, max_len: int = 512) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return raw[:max_len]


def _compose_full_name(first_name: str | None, last_name: str | None, explicit: str | None = None) -> str | None:
    explicit = _clean_text(explicit, max_len=256)
    if explicit and explicit not in {"Usuário", "User"}:
        return explicit
    parts = [p for p in (_clean_text(first_name, max_len=128), _clean_text(last_name, max_len=128)) if p]
    return " ".join(parts).strip() or explicit or None


def _profile_display_name(profile: TelegramUserProfile | TelegramProfileHit | None) -> str | None:
    if not profile:
        return None
    full_name = _clean_text(getattr(profile, "full_name", None), max_len=256)
    if full_name and full_name not in {"Usuário", "User"}:
        return full_name
    first_name = _clean_text(getattr(profile, "first_name", None), max_len=128)
    last_name = _clean_text(getattr(profile, "last_name", None), max_len=128)
    composed = _compose_full_name(first_name, last_name)
    if composed and composed not in {"Usuário", "User"}:
        return composed
    username = _clean_text(getattr(profile, "username", None), max_len=64)
    if username:
        return username if username.startswith("@") else f"@{username}"
    return None


class TelegramUserProfileService:
    def upsert_profile(
        self,
        *,
        user_id: int | str | None,
        first_name: object = None,
        last_name: object = None,
        username: object = None,
        full_name: object = None,
        photo_url: object = None,
        language_code: object = None,
        source: str = "unknown",
    ) -> TelegramProfileHit | None:
        try:
            uid = int(user_id) if user_id is not None else 0
        except Exception:
            return None
        if uid <= 0:
            return None

        first = _clean_text(first_name, max_len=128)
        last = _clean_text(last_name, max_len=128)
        uname = _clean_text(username, max_len=64)
        if uname and uname.startswith("@"):
            uname = uname[1:] or None
        full = _compose_full_name(first, last, _clean_text(full_name, max_len=256))
        photo = _clean_text(photo_url, max_len=2048)
        lang = _clean_text(language_code, max_len=32)
        src = _clean_text(source, max_len=64) or "unknown"
        now = utcnow_naive()

        try:
            with SessionLocal() as db:
                row = db.get(TelegramUserProfile, uid)
                if row is None:
                    row = TelegramUserProfile(
                        user_id=uid,
                        first_name=first,
                        last_name=last,
                        username=uname,
                        full_name=full,
                        photo_url=photo,
                        language_code=lang,
                        source=src,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(row)
                    changed = True
                else:
                    changed = False
                    values = {
                        "first_name": first,
                        "last_name": last,
                        "username": uname,
                        "full_name": full,
                        "photo_url": photo,
                        "language_code": lang,
                        "source": src,
                    }
                    for key, value in values.items():
                        if value is None and key not in {"source"}:
                            continue
                        if getattr(row, key) != value:
                            setattr(row, key, value)
                            changed = True
                    if changed:
                        row.updated_at = now
                db.commit()
                hit = TelegramProfileHit(
                    user_id=uid,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    username=row.username,
                    full_name=row.full_name,
                    photo_url=row.photo_url,
                    language_code=row.language_code,
                    source=row.source,
                )
            logger.info("TELEGRAM_USER_PROFILE_UPSERT | user_id=%s | source=%s | changed=%s", uid, src, str(changed).lower())
            return hit
        except Exception:
            logger.debug("TELEGRAM_USER_PROFILE_UPSERT_FAILED | user_id=%s | source=%s", uid, src, exc_info=True)
            return None

    def upsert_from_telegram_user(self, user: Any, *, source: str = "telegram_update") -> TelegramProfileHit | None:
        if user is None:
            return None
        return self.upsert_profile(
            user_id=getattr(user, "id", None),
            first_name=getattr(user, "first_name", None),
            last_name=getattr(user, "last_name", None),
            username=getattr(user, "username", None),
            full_name=getattr(user, "full_name", None),
            photo_url=getattr(user, "photo_url", None),
            language_code=getattr(user, "language_code", None),
            source=source,
        )

    def get_profile(self, user_id: int | str | None) -> TelegramProfileHit | None:
        try:
            uid = int(user_id) if user_id is not None else 0
        except Exception:
            return None
        if uid <= 0:
            return None
        try:
            with SessionLocal() as db:
                row = db.execute(
                    select(TelegramUserProfile).where(TelegramUserProfile.user_id == uid)
                ).scalar_one_or_none()
                if row is None:
                    return None
                return TelegramProfileHit(
                    user_id=uid,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    username=row.username,
                    full_name=row.full_name,
                    photo_url=row.photo_url,
                    language_code=row.language_code,
                    source=row.source,
                )
        except Exception:
            logger.debug("TELEGRAM_USER_PROFILE_LOOKUP_FAILED | user_id=%s", uid, exc_info=True)
            return None

    def display_name_from_saved_profile(self, user_id: int | str | None) -> str | None:
        return _profile_display_name(self.get_profile(user_id))

    async def resolve_music_display_name(self, bot: Any, user_id: int, *, surface: str = "tnow") -> str:
        """Resolve nome visual para tnow/mosaico sem expor username musical.

        Ordem: máscara /tpv, perfil Telegram salvo, get_chat como reparo, User.
        Provedores musicais permanecem dados técnicos de busca e não são fallback
        visual aqui.
        """
        private_label = tnow_privacy_service.label_for(telegram_user_id=user_id, surface=surface)
        if private_label:
            return private_label

        saved = self.display_name_from_saved_profile(user_id)
        if saved:
            return saved

        if bot is not None:
            try:
                chat = await bot.get_chat(user_id)
                self.upsert_profile(
                    user_id=getattr(chat, "id", user_id),
                    first_name=getattr(chat, "first_name", None),
                    last_name=getattr(chat, "last_name", None),
                    username=getattr(chat, "username", None),
                    full_name=getattr(chat, "full_name", None),
                    photo_url=getattr(chat, "photo_url", None),
                    language_code=None,
                    source="telegram_get_chat",
                )
                fetched = _profile_display_name(
                    TelegramProfileHit(
                        user_id=user_id,
                        first_name=getattr(chat, "first_name", None),
                        last_name=getattr(chat, "last_name", None),
                        username=getattr(chat, "username", None),
                        full_name=getattr(chat, "full_name", None),
                        photo_url=getattr(chat, "photo_url", None),
                        source="telegram_get_chat",
                    )
                )
                if fetched:
                    return fetched
            except Exception:
                logger.debug("TELEGRAM_USER_PROFILE_GET_CHAT_FAILED | user_id=%s", user_id, exc_info=True)

        return TPV_DEFAULT_LABEL


telegram_user_profile_service = TelegramUserProfileService()
