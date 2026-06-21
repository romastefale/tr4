from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.utils.datetime import utcnow_naive as _utcnow_naive


class TnowRecentTrack(Base):
    """Última atividade musical real observada para o mosaico /tnow.

    A tabela guarda um registro por usuário musical. O canal técnico/cache de
    capa pode guardar a mídia; esta tabela é a fonte de verdade para decidir se
    a pessoa aparece no mosaico e em qual janela de cor.
    """

    __tablename__ = "tnow_recent_tracks"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    lastfm_username: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    track_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    track_name: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    album_name: Mapped[str | None] = mapped_column(String, nullable=True)
    track_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, default=_utcnow_naive)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, default=_utcnow_naive)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    raw_age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
