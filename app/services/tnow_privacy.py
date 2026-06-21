from __future__ import annotations

import logging
from dataclasses import dataclass

from app.db.database import SessionLocal
from app.models.tnow_private_visibility import TnowPrivateVisibility
from app.utils.datetime import utcnow_naive as _utcnow_naive

logger = logging.getLogger(__name__)

TPV_DEFAULT_LABEL = "User"
TPV_SURFACE_ALIASES: dict[str, str] = {
    "tnow": "tnow",
    "mosaico": "mosaic",
    "mosaic": "mosaic",
    "all": "all",
    "todos": "all",
    "tudo": "all",
}


def normalize_tpv_mode(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    return TPV_SURFACE_ALIASES.get(raw)


def _applies(mode: str | None, surface: str) -> bool:
    clean_mode = normalize_tpv_mode(mode) or "all"
    clean_surface = normalize_tpv_mode(surface) or surface
    if clean_mode == "all":
        return True
    if clean_mode == clean_surface:
        return True
    # /tnow renders the mosaic image; treat the two words as aliases for this
    # card, while still preserving the requested mode in the database.
    return {clean_mode, clean_surface} == {"tnow", "mosaic"}


@dataclass(frozen=True, slots=True)
class TpvRule:
    telegram_user_id: int
    mode: str
    display_label: str
    enabled: bool


class TnowPrivacyService:
    def get_rule(self, *, telegram_user_id: int) -> TpvRule | None:
        try:
            with SessionLocal() as db:
                row = db.get(TnowPrivateVisibility, int(telegram_user_id))
                if not row:
                    return None
                return TpvRule(
                    telegram_user_id=int(row.telegram_user_id),
                    mode=str(row.mode or "all"),
                    display_label=str(row.display_label or TPV_DEFAULT_LABEL),
                    enabled=bool(row.enabled),
                )
        except Exception:
            logger.debug("TPV_RULE_GET_FAILED | user_id=%s", telegram_user_id, exc_info=True)
            return None

    def label_for(self, *, telegram_user_id: int, surface: str) -> str | None:
        rule = self.get_rule(telegram_user_id=telegram_user_id)
        if not rule or not rule.enabled:
            return None
        if not _applies(rule.mode, surface):
            return None
        label = str(rule.display_label or TPV_DEFAULT_LABEL).strip()
        return label or TPV_DEFAULT_LABEL

    def set_rule(
        self,
        *,
        telegram_user_id: int,
        mode: str,
        display_label: str = TPV_DEFAULT_LABEL,
        owner_id: int | None = None,
    ) -> TpvRule:
        clean_mode = normalize_tpv_mode(mode)
        if clean_mode is None or clean_mode == "off":
            raise ValueError("invalid_tpv_mode")
        clean_label = str(display_label or TPV_DEFAULT_LABEL).strip() or TPV_DEFAULT_LABEL
        now = _utcnow_naive()
        with SessionLocal() as db:
            row = db.get(TnowPrivateVisibility, int(telegram_user_id))
            if row is None:
                row = TnowPrivateVisibility(
                    telegram_user_id=int(telegram_user_id),
                    mode=clean_mode,
                    display_label=clean_label,
                    enabled=True,
                    created_by_owner_id=owner_id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.mode = clean_mode
                row.display_label = clean_label
                row.enabled = True
                row.created_by_owner_id = owner_id or row.created_by_owner_id
                row.updated_at = now
            db.commit()
            logger.info(
                "TPV_RULE_SET | user_id=%s | mode=%s | label=%s | owner_id=%s",
                int(telegram_user_id), clean_mode, clean_label, owner_id,
            )
            return TpvRule(
                telegram_user_id=int(telegram_user_id),
                mode=clean_mode,
                display_label=clean_label,
                enabled=True,
            )

    def disable_rule(self, *, telegram_user_id: int, owner_id: int | None = None) -> bool:
        now = _utcnow_naive()
        changed = False
        try:
            with SessionLocal() as db:
                row = db.get(TnowPrivateVisibility, int(telegram_user_id))
                if row:
                    row.enabled = False
                    row.updated_at = now
                    changed = True
                    db.commit()
        except Exception:
            logger.debug("TPV_RULE_DISABLE_FAILED | user_id=%s", telegram_user_id, exc_info=True)
            return False
        logger.info("TPV_RULE_OFF | user_id=%s | owner_id=%s | changed=%s", int(telegram_user_id), owner_id, changed)
        return changed


tnow_privacy_service = TnowPrivacyService()
