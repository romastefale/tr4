from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.utils.datetime import utcnow_naive as _utcnow_naive


class TnowPrivateVisibility(Base):
    """Owner-only visual mask for /tnow/mosaico display names.

    The musical identity is not changed: Last fm/Spotify data remains the
    source for lookup/cache. This table only controls how a selected user is
    rendered in the mosaic/card surface.
    """

    __tablename__ = "tnow_private_visibility"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    mode: Mapped[str] = mapped_column(String, nullable=False, default="all", index=True)
    display_label: Mapped[str] = mapped_column(String, nullable=False, default="User")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
