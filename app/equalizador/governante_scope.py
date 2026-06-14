from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.governante_webapp import CUSTOM_ALLOWED_ACTIONS, CUSTOM_PACKAGE, WEBAPP_PACKAGES, package_actions, sanitize_custom_actions
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables, get_operador_public_by_user_id, get_palco_internal_by_ref, list_equalizador_palcos


class GovernanteScopeError(PermissionError):
    def __init__(self, code: str, public_detail: str):
        super().__init__(code)
        self.code = code
        self.public_detail = public_detail


class GovernanteLimitError(GovernanteScopeError):
    def __init__(self, *, action: str, daily_limit: int, used_count: int, remaining: int = 0):
        super().__init__(
            "limite_diario_atingido",
            "Limite diário atingido para esta ação neste grupo.",
        )
        self.action = str(action or "")
        self.daily_limit = max(0, int(daily_limit))
        self.used_count = max(0, int(used_count))
        self.remaining = max(0, int(remaining))

    def payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "public_detail": self.public_detail,
            "action": self.action,
            "daily_limit": self.daily_limit,
            "used_count": self.used_count,
            "remaining": self.remaining,
        }


@dataclass(frozen=True)
class GovernanteAssignment:
    assignment_ref: str
    telegram_user_id: int
    telegram_chat_id: int
    pacote: str
    actions: tuple[str, ...]
    habilitado: bool
    daily_limits: dict[str, int]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_key() -> str:
    # Limite diário do produto foi decidido para o contexto do usuário/projeto no Brasil.
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()


def _parse_iso(value: object) -> datetime | None:
    try:
        text_value = str(value or "").strip()
        if not text_value:
            return None
        return datetime.fromisoformat(text_value)
    except Exception:
        return None


def _clean_pacote(value: object) -> str:
    pacote = str(value or "").strip().lower()
    return pacote if pacote in WEBAPP_PACKAGES else ""


def _actions_from_json(value: object, *, pacote: str) -> tuple[str, ...]:
    if pacote != CUSTOM_PACKAGE:
        return package_actions(pacote)
    try:
        raw = json.loads(str(value or "[]"))
    except Exception:
        raw = []
    actions = sanitize_custom_actions(raw)
    return actions


def _assignment_ref(*, user_id: int, chat_id: int, alias_secret: str) -> str:
    # Corrige Etapa 6: Python hash() é randomizado por processo.
    # A referência persistente precisa ser estável entre restarts.
    seed = f"governante:{int(user_id)}:{int(chat_id)}:{alias_secret}".encode("utf-8")
    number = int(hashlib.sha256(seed).hexdigest()[:15], 16) % (10**12)
    return make_ui_ref("gpk", number, alias_secret)


def _limit_exception_ref(*, assignment_ref: str, action: str, created_at: str, alias_secret: str = "") -> str:
    seed = f"limite:{assignment_ref}:{action}:{created_at}:{alias_secret}".encode("utf-8")
    number = int(hashlib.sha256(seed).hexdigest()[:15], 16) % (10**12)
    return make_ui_ref("gex", number, alias_secret)


def ensure_governante_scope_tables(db_engine: Engine = default_engine) -> None:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governante_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_ref TEXT NOT NULL UNIQUE,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    pacote TEXT NOT NULL,
                    actions_json TEXT NOT NULL DEFAULT '[]',
                    granted_by_ref TEXT,
                    motivo TEXT,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_user_id, telegram_chat_id)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governante_assignments_user ON eq_governante_assignments(telegram_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governante_assignments_chat ON eq_governante_assignments(telegram_chat_id)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governante_daily_limits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    daily_limit INTEGER NOT NULL,
                    updated_by_ref TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_user_id, telegram_chat_id, action)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governante_daily_limits_scope ON eq_governante_daily_limits(telegram_user_id, telegram_chat_id)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governante_daily_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usage_date TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(usage_date, telegram_user_id, telegram_chat_id, action)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governante_daily_usage_scope ON eq_governante_daily_usage(telegram_user_id, telegram_chat_id, usage_date)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governante_limit_exceptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exception_ref TEXT NOT NULL UNIQUE,
                    assignment_ref TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_by_ref TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revoked_by_ref TEXT
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governante_limit_exceptions_scope ON eq_governante_limit_exceptions(telegram_user_id, telegram_chat_id, action, expires_at)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governante_daily_summary_dispatch (
                    summary_date TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL,
                    sent_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )


def _resolve_usr_ref(usr_ref: str, *, db_engine: Engine = default_engine) -> int | None:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT telegram_user_id FROM eq_operadores WHERE ui_ref=:usr_ref AND habilitado=1 LIMIT 1"),
            {"usr_ref": str(usr_ref or "").strip()},
        ).mappings().first()
    return int(row["telegram_user_id"]) if row else None


def _resolve_grp_ref(grp_ref: str, *, db_engine: Engine = default_engine) -> int | None:
    palco = get_palco_internal_by_ref(grp_ref=str(grp_ref or "").strip(), db_engine=db_engine)
    if not palco:
        return None
    return int(palco["telegram_chat_id"])


def _limits_for(*, user_id: int, chat_id: int, db_engine: Engine = default_engine) -> dict[str, int]:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT action, daily_limit
                FROM eq_governante_daily_limits
                WHERE telegram_user_id=:user_id AND telegram_chat_id=:chat_id
                """
            ),
            {"user_id": int(user_id), "chat_id": int(chat_id)},
        ).mappings().all()
    return {str(row["action"]): max(0, int(row["daily_limit"] or 0)) for row in rows}


def _public_palco(chat_id: int, *, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    rows = list_equalizador_palcos(palco_ids={int(chat_id)}, alias_secret=alias_secret, db_engine=db_engine)
    if rows:
        return {"grp_ref": rows[0].get("grp_ref"), "titulo": rows[0].get("titulo") or "Grupo"}
    return {"grp_ref": make_ui_ref("grp", int(chat_id), alias_secret), "titulo": "Grupo"}


def _row_to_assignment(row: object, *, alias_secret: str, db_engine: Engine = default_engine) -> GovernanteAssignment:
    pacote = _clean_pacote(row["pacote"])
    actions = _actions_from_json(row.get("actions_json", "[]"), pacote=pacote)
    return GovernanteAssignment(
        assignment_ref=str(row["assignment_ref"]),
        telegram_user_id=int(row["telegram_user_id"]),
        telegram_chat_id=int(row["telegram_chat_id"]),
        pacote=pacote,
        actions=actions,
        habilitado=bool(int(row["habilitado"] or 0)),
        daily_limits=_limits_for(user_id=int(row["telegram_user_id"]), chat_id=int(row["telegram_chat_id"]), db_engine=db_engine),
    )


def grant_governante_package(
    *,
    usr_ref: str,
    grp_ref: str,
    pacote: str,
    granted_by_ref: str,
    alias_secret: str,
    motivo: str = "",
    actions: object = None,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    clean_pacote = _clean_pacote(pacote)
    if not clean_pacote:
        raise GovernanteScopeError("pacote_indisponivel", "Escolha um pacote válido: básico, moderador, avançado ou personalizado.")
    user_id = _resolve_usr_ref(usr_ref, db_engine=db_engine)
    if not user_id:
        raise GovernanteScopeError("governante_indisponivel", "Escolha um governante conhecido antes de liberar pacote.")
    chat_id = _resolve_grp_ref(grp_ref, db_engine=db_engine)
    if not chat_id:
        raise GovernanteScopeError("grupo_indisponivel", "Escolha um grupo válido antes de liberar pacote.")
    now = _now_iso()
    assignment_ref = _assignment_ref(user_id=int(user_id), chat_id=int(chat_id), alias_secret=alias_secret)
    selected_actions = sanitize_custom_actions(actions) if clean_pacote == CUSTOM_PACKAGE else package_actions(clean_pacote)
    if clean_pacote == CUSTOM_PACKAGE and not selected_actions:
        raise GovernanteScopeError("acoes_personalizadas_invalidas", "Escolha ao menos uma ação permitida para o pacote personalizado.")
    actions_json = json.dumps(list(selected_actions), ensure_ascii=False)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_governante_assignments (
                    assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json,
                    granted_by_ref, motivo, habilitado, created_at, revoked_at, updated_at
                ) VALUES (
                    :assignment_ref, :user_id, :chat_id, :pacote, :actions_json,
                    :granted_by_ref, :motivo, 1, :created_at, NULL, :updated_at
                )
                ON CONFLICT(telegram_user_id, telegram_chat_id) DO UPDATE SET
                    assignment_ref=excluded.assignment_ref,
                    pacote=excluded.pacote,
                    actions_json=excluded.actions_json,
                    granted_by_ref=excluded.granted_by_ref,
                    motivo=excluded.motivo,
                    habilitado=1,
                    revoked_at=NULL,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "assignment_ref": assignment_ref,
                "user_id": int(user_id),
                "chat_id": int(chat_id),
                "pacote": clean_pacote,
                "actions_json": actions_json,
                "granted_by_ref": str(granted_by_ref or ""),
                "motivo": str(motivo or "").strip()[:240],
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_governante_assignment_public(assignment_ref=assignment_ref, alias_secret=alias_secret, db_engine=db_engine) or {"assignment_ref": assignment_ref, "pacote": clean_pacote}


def revoke_governante_package(*, assignment_ref: str, revoked_by_ref: str, db_engine: Engine = default_engine) -> bool:
    ensure_governante_scope_tables(db_engine)
    now = _now_iso()
    with db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE eq_governante_assignments
                SET habilitado=0, revoked_at=:revoked_at, updated_at=:updated_at, motivo=:motivo
                WHERE assignment_ref=:assignment_ref AND habilitado=1
                """
            ),
            {"assignment_ref": str(assignment_ref or "").strip(), "revoked_at": now, "updated_at": now, "motivo": f"revogado por {revoked_by_ref}"[:240]},
        )
    return bool(getattr(result, "rowcount", 0))


def set_governante_daily_limit(
    *,
    assignment_ref: str,
    action: str,
    daily_limit: int,
    updated_by_ref: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    action_value = str(action or "").strip()
    if not action_value:
        raise GovernanteScopeError("acao_indisponivel", "Escolha uma ação para configurar limite.")
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT telegram_user_id, telegram_chat_id, pacote, actions_json FROM eq_governante_assignments WHERE assignment_ref=:assignment_ref AND habilitado=1 LIMIT 1"),
            {"assignment_ref": str(assignment_ref or "").strip()},
        ).mappings().first()
        if not row:
            raise GovernanteScopeError("pacote_indisponivel", "Escolha um pacote ativo para configurar limite.")
        pacote_row = _clean_pacote(row["pacote"])
        allowed_actions = _actions_from_json(row.get("actions_json", "[]"), pacote=pacote_row)
        if action_value not in allowed_actions:
            raise GovernanteScopeError("acao_fora_do_pacote", "A ação não pertence ao pacote governante ativo.")
        conn.execute(
            text(
                """
                INSERT INTO eq_governante_daily_limits (telegram_user_id, telegram_chat_id, action, daily_limit, updated_by_ref, updated_at)
                VALUES (:user_id, :chat_id, :action, :daily_limit, :updated_by_ref, :updated_at)
                ON CONFLICT(telegram_user_id, telegram_chat_id, action) DO UPDATE SET
                    daily_limit=excluded.daily_limit,
                    updated_by_ref=excluded.updated_by_ref,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "user_id": int(row["telegram_user_id"]),
                "chat_id": int(row["telegram_chat_id"]),
                "action": action_value,
                "daily_limit": max(0, int(daily_limit)),
                "updated_by_ref": str(updated_by_ref or ""),
                "updated_at": _now_iso(),
            },
        )
    return {"assignment_ref": str(assignment_ref), "action": action_value, "daily_limit": max(0, int(daily_limit))}


def get_governante_assignment(*, user_id: int, chat_id: int, db_engine: Engine = default_engine) -> GovernanteAssignment | None:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json, habilitado
                FROM eq_governante_assignments
                WHERE telegram_user_id=:user_id AND telegram_chat_id=:chat_id AND habilitado=1
                LIMIT 1
                """
            ),
            {"user_id": int(user_id), "chat_id": int(chat_id)},
        ).mappings().first()
    if not row:
        return None
    return _row_to_assignment(row, alias_secret="", db_engine=db_engine)


def governante_action_allowed(*, user_id: int, chat_id: int, action: str, is_maestro: bool, db_engine: Engine = default_engine) -> bool:
    if is_maestro:
        return True
    assignment = get_governante_assignment(user_id=int(user_id), chat_id=int(chat_id), db_engine=db_engine)
    if not assignment:
        return False
    action_value = str(action or "").strip()
    return bool(action_value and action_value in assignment.actions)


def require_governante_action(
    *,
    user_id: int,
    chat_id: int,
    action: str,
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> None:
    if is_maestro:
        return
    assignment = get_governante_assignment(user_id=int(user_id), chat_id=int(chat_id), db_engine=db_engine)
    if not assignment:
        raise GovernanteScopeError("pacote_nao_liberado", "O owner ainda não liberou pacote governante para você neste grupo.")
    action_value = str(action or "").strip()
    if action_value not in assignment.actions:
        raise GovernanteScopeError("acao_fora_do_pacote", "Ação fora do pacote liberado pelo owner para este grupo.")


def register_governante_usage(
    *,
    user_id: int,
    chat_id: int,
    action: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    today = _today_key()
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_governante_daily_usage (usage_date, telegram_user_id, telegram_chat_id, action, used_count, updated_at)
                VALUES (:usage_date, :user_id, :chat_id, :action, 1, :updated_at)
                ON CONFLICT(usage_date, telegram_user_id, telegram_chat_id, action) DO UPDATE SET
                    used_count=used_count + 1,
                    updated_at=excluded.updated_at
                """
            ),
            {"usage_date": today, "user_id": int(user_id), "chat_id": int(chat_id), "action": str(action or ""), "updated_at": now},
        )
        row = conn.execute(
            text(
                """
                SELECT used_count FROM eq_governante_daily_usage
                WHERE usage_date=:usage_date AND telegram_user_id=:user_id AND telegram_chat_id=:chat_id AND action=:action
                """
            ),
            {"usage_date": today, "user_id": int(user_id), "chat_id": int(chat_id), "action": str(action or "")},
        ).mappings().first()
    return {"usage_date": today, "used_count": int(row["used_count"] if row else 0)}


def _usage_for(*, user_id: int, chat_id: int, db_engine: Engine = default_engine) -> dict[str, int]:
    ensure_governante_scope_tables(db_engine)
    today = _today_key()
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT action, used_count
                FROM eq_governante_daily_usage
                WHERE usage_date=:usage_date AND telegram_user_id=:user_id AND telegram_chat_id=:chat_id
                """
            ),
            {"usage_date": today, "user_id": int(user_id), "chat_id": int(chat_id)},
        ).mappings().all()
    return {str(row["action"]): max(0, int(row["used_count"] or 0)) for row in rows}


def _active_exceptions_for(*, user_id: int, chat_id: int, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_governante_scope_tables(db_engine)
    now = _now_iso()
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT exception_ref, assignment_ref, action, created_at, expires_at
                FROM eq_governante_limit_exceptions
                WHERE telegram_user_id=:user_id
                  AND telegram_chat_id=:chat_id
                  AND revoked_at IS NULL
                  AND expires_at>:now
                ORDER BY expires_at ASC, id ASC
                """
            ),
            {"user_id": int(user_id), "chat_id": int(chat_id), "now": now},
        ).mappings().all()
    return [
        {
            "exception_ref": str(row["exception_ref"]),
            "assignment_ref": str(row["assignment_ref"]),
            "action": str(row["action"]),
            "created_at": str(row["created_at"]),
            "expires_at": str(row["expires_at"]),
        }
        for row in rows
    ]


def _has_active_exception(*, user_id: int, chat_id: int, action: str, db_engine: Engine = default_engine) -> bool:
    return any(item["action"] == str(action or "") for item in _active_exceptions_for(user_id=user_id, chat_id=chat_id, db_engine=db_engine))


def check_governante_daily_limit(
    *,
    user_id: int,
    chat_id: int,
    action: str,
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    if is_maestro:
        return {"ok": True, "owner_bypass": True}
    assignment = get_governante_assignment(user_id=int(user_id), chat_id=int(chat_id), db_engine=db_engine)
    if not assignment:
        raise GovernanteScopeError("pacote_nao_liberado", "O owner ainda não liberou pacote governante para você neste grupo.")
    action_value = str(action or "").strip()
    daily_limit = int(assignment.daily_limits.get(action_value, 0) or 0)
    used_count = int(_usage_for(user_id=int(user_id), chat_id=int(chat_id), db_engine=db_engine).get(action_value, 0) or 0)
    active_exception = _has_active_exception(user_id=int(user_id), chat_id=int(chat_id), action=action_value, db_engine=db_engine)
    if daily_limit <= 0:
        return {"ok": True, "action": action_value, "daily_limit": 0, "used_count": used_count, "remaining": None, "exception_active": active_exception}
    if active_exception:
        return {"ok": True, "action": action_value, "daily_limit": daily_limit, "used_count": used_count, "remaining": max(0, daily_limit - used_count), "exception_active": True}
    remaining = max(0, daily_limit - used_count)
    if used_count >= daily_limit:
        raise GovernanteLimitError(action=action_value, daily_limit=daily_limit, used_count=used_count, remaining=0)
    return {"ok": True, "action": action_value, "daily_limit": daily_limit, "used_count": used_count, "remaining": max(0, remaining)}


def grant_governante_limit_exception(
    *,
    assignment_ref: str,
    action: str,
    created_by_ref: str,
    alias_secret: str,
    hours: int = 24,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    action_value = str(action or "").strip()
    if not action_value:
        raise GovernanteScopeError("acao_indisponivel", "Escolha uma ação para liberar exceção.")
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json
                FROM eq_governante_assignments
                WHERE assignment_ref=:assignment_ref AND habilitado=1
                LIMIT 1
                """
            ),
            {"assignment_ref": str(assignment_ref or "").strip()},
        ).mappings().first()
        if not row:
            raise GovernanteScopeError("pacote_indisponivel", "Escolha um pacote ativo para liberar exceção.")
        pacote_row = _clean_pacote(row["pacote"])
        allowed_actions = _actions_from_json(row.get("actions_json", "[]"), pacote=pacote_row)
        if action_value not in allowed_actions:
            raise GovernanteScopeError("acao_fora_do_pacote", "A ação não pertence ao pacote governante ativo.")
        created_at = _now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=max(1, min(int(hours or 24), 24)))).isoformat()
        exception_ref = _limit_exception_ref(assignment_ref=str(row["assignment_ref"]), action=action_value, created_at=created_at, alias_secret=alias_secret)
        conn.execute(
            text(
                """
                INSERT INTO eq_governante_limit_exceptions (
                    exception_ref, assignment_ref, telegram_user_id, telegram_chat_id, action,
                    created_by_ref, created_at, expires_at, revoked_at, revoked_by_ref
                ) VALUES (
                    :exception_ref, :assignment_ref, :user_id, :chat_id, :action,
                    :created_by_ref, :created_at, :expires_at, NULL, NULL
                )
                """
            ),
            {
                "exception_ref": exception_ref,
                "assignment_ref": str(row["assignment_ref"]),
                "user_id": int(row["telegram_user_id"]),
                "chat_id": int(row["telegram_chat_id"]),
                "action": action_value,
                "created_by_ref": str(created_by_ref or ""),
                "created_at": created_at,
                "expires_at": expires_at,
            },
        )
    return {"exception_ref": exception_ref, "assignment_ref": str(assignment_ref), "action": action_value, "expires_at": expires_at}


def revoke_governante_limit_exception(*, exception_ref: str, revoked_by_ref: str, db_engine: Engine = default_engine) -> bool:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE eq_governante_limit_exceptions
                SET revoked_at=:revoked_at, revoked_by_ref=:revoked_by_ref
                WHERE exception_ref=:exception_ref AND revoked_at IS NULL
                """
            ),
            {"exception_ref": str(exception_ref or "").strip(), "revoked_at": _now_iso(), "revoked_by_ref": str(revoked_by_ref or "")},
        )
    return bool(getattr(result, "rowcount", 0))


def _assignment_public(row: object, *, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    user_id = int(row["telegram_user_id"])
    chat_id = int(row["telegram_chat_id"])
    pacote = _clean_pacote(row["pacote"])
    actions = list(_actions_from_json(row.get("actions_json", "[]"), pacote=pacote))
    limits = _limits_for(user_id=user_id, chat_id=chat_id, db_engine=db_engine)
    usage = _usage_for(user_id=user_id, chat_id=chat_id, db_engine=db_engine)
    remaining: dict[str, int | None] = {}
    for action in actions:
        limit_value = int(limits.get(action, 0) or 0)
        used_value = int(usage.get(action, 0) or 0)
        remaining[action] = None if limit_value <= 0 else max(0, limit_value - used_value)
    return {
        "assignment_ref": str(row["assignment_ref"]),
        "governante": get_operador_public_by_user_id(user_id=user_id, alias_secret=alias_secret, perfil="Governante", db_engine=db_engine),
        "palco": _public_palco(chat_id, alias_secret=alias_secret, db_engine=db_engine),
        "pacote": pacote,
        "actions": actions,
        "daily_limits": limits,
        "daily_usage": usage,
        "daily_remaining": remaining,
        "limit_exceptions": _active_exceptions_for(user_id=user_id, chat_id=chat_id, db_engine=db_engine),
        "habilitado": bool(int(row["habilitado"] or 0)),
        "updated_at": row["updated_at"],
    }


def get_governante_assignment_public(*, assignment_ref: str, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object] | None:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json, habilitado, updated_at
                FROM eq_governante_assignments
                WHERE assignment_ref=:assignment_ref
                LIMIT 1
                """
            ),
            {"assignment_ref": str(assignment_ref or "").strip()},
        ).mappings().first()
    return _assignment_public(row, alias_secret=alias_secret, db_engine=db_engine) if row else None


def list_governante_scope_public(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json, habilitado, updated_at
                FROM eq_governante_assignments
                WHERE habilitado=1
                ORDER BY updated_at DESC, id DESC
                """
            )
        ).mappings().all()
    assignments = [_assignment_public(row, alias_secret=alias_secret, db_engine=db_engine) for row in rows]
    return {
        "packages": {key: list(values) for key, values in WEBAPP_PACKAGES.items()},
        "custom_allowed_actions": list(CUSTOM_ALLOWED_ACTIONS),
        "assignments": assignments,
        "resumo": {"ativos": len(assignments)},
        "limites": {"base_diaria_criada": True, "enforcement": "ativo", "excecao_24h": True},
    }


def daily_limit_summary_public(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_governante_scope_tables(db_engine)
    today = _today_key()
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT u.telegram_user_id, u.telegram_chat_id, u.action, u.used_count,
                       COALESCE(l.daily_limit, 0) AS daily_limit
                FROM eq_governante_daily_usage u
                LEFT JOIN eq_governante_daily_limits l
                  ON l.telegram_user_id=u.telegram_user_id
                 AND l.telegram_chat_id=u.telegram_chat_id
                 AND l.action=u.action
                WHERE u.usage_date=:today
                ORDER BY u.used_count DESC, u.updated_at DESC
            """),
            {"today": today},
        ).mappings().all()
    items: list[dict[str, object]] = []
    total_used = 0
    limit_hits = 0
    for row in rows:
        user_id = int(row["telegram_user_id"])
        chat_id = int(row["telegram_chat_id"])
        used = int(row.get("used_count") or 0)
        daily_limit = int(row.get("daily_limit") or 0)
        remaining = None if daily_limit <= 0 else max(0, daily_limit - used)
        if daily_limit > 0 and used >= daily_limit:
            limit_hits += 1
        total_used += used
        items.append({
            "governante": get_operador_public_by_user_id(user_id=user_id, alias_secret=alias_secret, perfil="Governante", db_engine=db_engine),
            "palco": _public_palco(chat_id, alias_secret=alias_secret, db_engine=db_engine),
            "action": str(row["action"]),
            "used_count": used,
            "daily_limit": daily_limit,
            "remaining": remaining,
        })
    return {"date": today, "total_actions": total_used, "limit_hits": limit_hits, "items": items[:100]}




def daily_limit_summary_text(*, alias_secret: str, db_engine: Engine = default_engine) -> str:
    summary = daily_limit_summary_public(alias_secret=alias_secret, db_engine=db_engine)
    date = str(summary.get("date") or _today_key())
    items = list(summary.get("items") or [])
    lines = [
        f"Resumo diário de limites — {date}",
        f"Ações registradas: {int(summary.get('total_actions') or 0)}",
        f"Limites atingidos: {int(summary.get('limit_hits') or 0)}",
    ]
    if not items:
        lines.append("Nenhum uso governante registrado hoje.")
        return "\n".join(lines)[:3900]
    for row in items[:25]:
        gov = row.get("governante") or {}
        palco = row.get("palco") or {}
        nome = str(gov.get("nome") or gov.get("display_name") or "Governante")
        grupo = str(palco.get("titulo") or "Grupo")
        action = str(row.get("action") or "ação")
        used = int(row.get("used_count") or 0)
        daily_limit = int(row.get("daily_limit") or 0)
        remaining = row.get("remaining")
        rest = "sem limite" if remaining is None else f"{remaining} restante(s)"
        lines.append(f"• {nome} · {grupo} · {action}: {used}/{daily_limit or '∞'} · {rest}")
    if len(items) > 25:
        lines.append(f"… +{len(items) - 25} linha(s) no painel owner.")
    return "\n".join(lines)[:3900]


def reserve_daily_limit_summary_dispatch(*, summary_date: str | None = None, db_engine: Engine = default_engine) -> bool:
    ensure_governante_scope_tables(db_engine)
    date_key = str(summary_date or _today_key())
    with db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT OR IGNORE INTO eq_governante_daily_summary_dispatch
                (summary_date, sent_at, sent_count, failed_count)
                VALUES (:summary_date, :sent_at, 0, 0)
                """
            ),
            {"summary_date": date_key, "sent_at": _now_iso()},
        )
    return bool(getattr(result, "rowcount", 0))


def mark_daily_limit_summary_dispatch_result(*, summary_date: str | None = None, sent_count: int = 0, failed_count: int = 0, db_engine: Engine = default_engine) -> None:
    ensure_governante_scope_tables(db_engine)
    date_key = str(summary_date or _today_key())
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_governante_daily_summary_dispatch
                SET sent_at=:sent_at, sent_count=:sent_count, failed_count=:failed_count
                WHERE summary_date=:summary_date
                """
            ),
            {
                "summary_date": date_key,
                "sent_at": _now_iso(),
                "sent_count": max(0, int(sent_count)),
                "failed_count": max(0, int(failed_count)),
            },
        )


def scope_for_user_public(*, user_id: int, chat_ids: Iterable[int], alias_secret: str, is_maestro: bool, db_engine: Engine = default_engine) -> dict[str, object]:
    if is_maestro:
        return {"modo": "owner", "assignments": [], "packages": {key: list(values) for key, values in WEBAPP_PACKAGES.items()}, "custom_allowed_actions": list(CUSTOM_ALLOWED_ACTIONS)}
    ensure_governante_scope_tables(db_engine)
    chat_ids_set = {int(chat_id) for chat_id in chat_ids}
    if not chat_ids_set:
        return {"modo": "governante", "assignments": [], "packages": {key: list(values) for key, values in WEBAPP_PACKAGES.items()}, "custom_allowed_actions": list(CUSTOM_ALLOWED_ACTIONS)}
    placeholders = ",".join(f":chat_{idx}" for idx, _ in enumerate(chat_ids_set))
    params = {f"chat_{idx}": chat_id for idx, chat_id in enumerate(chat_ids_set)}
    params["user_id"] = int(user_id)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT assignment_ref, telegram_user_id, telegram_chat_id, pacote, actions_json, habilitado, updated_at
                FROM eq_governante_assignments
                WHERE telegram_user_id=:user_id AND habilitado=1 AND telegram_chat_id IN ({placeholders})
                ORDER BY updated_at DESC, id DESC
                """
            ),
            params,
        ).mappings().all()
    return {
        "modo": "governante",
        "assignments": [_assignment_public(row, alias_secret=alias_secret, db_engine=db_engine) for row in rows],
        "packages": {key: list(values) for key, values in WEBAPP_PACKAGES.items()},
        "custom_allowed_actions": list(CUSTOM_ALLOWED_ACTIONS),
    }
