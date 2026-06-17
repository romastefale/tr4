from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.utils.datetime import utcnow_naive as _utcnow_naive


class LyricsSnippetCache(Base):
    """Cache persistente de trechos de letra usados pelo /tly.

    Guarda apenas o trecho/snippet exibido no quote, não a letra completa.
    Linhas com snippet NULL representam cache negativo de curta duração.
    """

    __tablename__ = "lyrics_snippet_cache"

    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    artist_norm: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title_norm: Mapped[str] = mapped_column(String, nullable=False, index=True)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    channel_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    channel_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
