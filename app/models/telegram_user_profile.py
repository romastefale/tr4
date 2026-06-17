from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.utils.datetime import utcnow_naive as _utcnow_naive


class TelegramUserProfile(Base):
    """Perfil Telegram persistente usado como identidade visual do bot.

    A identidade musical permanece técnica (provedores, usernames e tokens).
    Para tnow/mosaico/cards, a chave visual confiável é o Telegram user_id e
    os dados públicos que o próprio Telegram entrega em interações, inline e
    Mini App/WebApp.
    """

    __tablename__ = "telegram_user_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
