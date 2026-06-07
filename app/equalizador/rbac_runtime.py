from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.configuracao import nome_canal_publico
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables, get_operador_public_by_user_id, get_palco_internal_by_ref, list_equalizador_palcos
from app.equalizador.permissions import CANAL_BY_CODE, CANAL_DEFINITIONS, CRITICAL_CANAL_CODES, canal_is_allowed, canais_for_palco, parse_equalizador_canais




class RbacRuntimeError(ValueError):
    def __init__(self, code: str, public_detail: str):
        super().__init__(code)
        self.code = code
        self.public_detail = public_detail


def rbac_runtime_error_payload(exc: BaseException) -> dict[str, str]:
    code = str(exc) or exc.__class__.__name__
    public = getattr(exc, "public_detail", "Concessão inválida ou alvo indisponível.")
    return {"code": code, "public_detail": str(public)}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_rbac_runtime_tables(db_engine: Engine = default_engine) -> None:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_runtime_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    grant_ref TEXT NOT NULL UNIQUE,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_chat_id INTEGER,
                    canal_codigo TEXT NOT NULL,
                    granted_by_ref TEXT,
                    motivo TEXT,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(telegram_user_id, telegram_chat_id, canal_codigo)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_runtime_grants_user ON eq_runtime_grants(telegram_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_runtime_grants_ref ON eq_runtime_grants(grant_ref)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_governance_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    actor_ref TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    action TEXT NOT NULL,
                    public_detail TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_governance_audit_created ON eq_governance_audit(created_at)"))


def _grant_ref(*, user_id: int, chat_id: int | None, canal_codigo: str, alias_secret: str) -> str:
    base = f"{int(user_id)}:{'*' if chat_id is None else int(chat_id)}:{canal_codigo}"
    # Use the existing ref helper so raw IDs never leave the API.
    return make_ui_ref("exp", abs(hash((base, alias_secret))) % (10**12), alias_secret)


def _resolve_usr_ref(usr_ref: str, *, db_engine: Engine = default_engine) -> int | None:
    ensure_rbac_runtime_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT telegram_user_id FROM eq_operadores WHERE ui_ref=:ui_ref AND habilitado=1 LIMIT 1"),
            {"ui_ref": str(usr_ref or "").strip()},
        ).mappings().first()
    if not row:
        return None
    return int(row["telegram_user_id"])


def _operator_public_by_usr_ref(usr_ref: str, *, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object] | None:
    ensure_rbac_runtime_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_user_id, ui_ref, nome, username, perfil, habilitado, updated_at
                FROM eq_operadores
                WHERE ui_ref=:ui_ref
                LIMIT 1
                """
            ),
            {"ui_ref": str(usr_ref or "").strip()},
        ).mappings().first()
    if not row:
        return None
    payload = get_operador_public_by_user_id(
        user_id=int(row["telegram_user_id"]),
        alias_secret=alias_secret,
        perfil=str(row["perfil"] or "Governante"),
        db_engine=db_engine,
    )
    payload["habilitado"] = bool(int(row["habilitado"] or 0))
    payload["updated_at"] = row["updated_at"]
    return payload


def _record_governance_audit(
    *,
    actor_ref: str,
    subject_ref: str,
    action: str,
    public_detail: str = "",
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> None:
    ensure_rbac_runtime_tables(db_engine)
    now = _now_iso()
    seed = f"{actor_ref}:{subject_ref}:{action}:{now}"
    event_ref = make_ui_ref("exp", abs(hash((seed, alias_secret))) % (10**12), alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO eq_governance_audit (event_ref, actor_ref, subject_ref, action, public_detail, created_at)
                VALUES (:event_ref, :actor_ref, :subject_ref, :action, :public_detail, :created_at)
                """
            ),
            {
                "event_ref": event_ref,
                "actor_ref": str(actor_ref or ""),
                "subject_ref": str(subject_ref or ""),
                "action": str(action or "")[:80],
                "public_detail": str(public_detail or "")[:240],
                "created_at": now,
            },
        )


def _resolve_grp_ref(grp_ref: str | None, *, db_engine: Engine = default_engine) -> int | None:
    value = str(grp_ref or "*").strip()
    if not value or value == "*":
        return None
    palco = get_palco_internal_by_ref(grp_ref=value, db_engine=db_engine)
    if not palco:
        return None
    return int(palco["telegram_chat_id"])


def runtime_canal_is_allowed(
    *,
    user_id: int,
    chat_id: int,
    canal_codigo: str,
    db_engine: Engine = default_engine,
) -> bool:
    if canal_codigo not in CANAL_BY_CODE:
        return False
    ensure_rbac_runtime_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM eq_runtime_grants
                WHERE telegram_user_id=:user_id
                  AND canal_codigo=:canal_codigo
                  AND habilitado=1
                  AND (telegram_chat_id IS NULL OR telegram_chat_id=:chat_id)
                LIMIT 1
                """
            ),
            {"user_id": int(user_id), "chat_id": int(chat_id), "canal_codigo": str(canal_codigo)},
        ).first()
    return bool(row)


def canal_is_allowed_effective(
    *,
    raw_canais: str,
    user_id: int,
    chat_id: int,
    canal_codigo: str,
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> bool:
    if canal_is_allowed(raw_canais=raw_canais, user_id=user_id, chat_id=chat_id, canal_codigo=canal_codigo, is_maestro=is_maestro):
        return True
    return runtime_canal_is_allowed(user_id=user_id, chat_id=chat_id, canal_codigo=canal_codigo, db_engine=db_engine)


def canais_for_palco_effective(
    *,
    raw_canais: str,
    user_id: int,
    chat_id: int,
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for definition in CANAL_DEFINITIONS:
        source = ""
        env_allowed = canal_is_allowed(
            raw_canais=raw_canais,
            user_id=user_id,
            chat_id=chat_id,
            canal_codigo=definition.codigo,
            is_maestro=is_maestro,
        )
        runtime_allowed = runtime_canal_is_allowed(
            user_id=user_id,
            chat_id=chat_id,
            canal_codigo=definition.codigo,
            db_engine=db_engine,
        )
        if env_allowed:
            source = "variável"
        elif runtime_allowed:
            source = "delegação runtime"
        if source:
            rows.append({"codigo": definition.codigo, "nome": definition.nome, "critico": definition.critico, "origem": source})
    return rows


def canal_codes_for_operator_effective(
    *,
    raw_canais: str,
    user_id: int,
    chat_ids: Iterable[int],
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> list[str]:
    codes: set[str] = set()
    for chat_id in chat_ids:
        for canal in canais_for_palco_effective(raw_canais=raw_canais, user_id=user_id, chat_id=int(chat_id), is_maestro=is_maestro, db_engine=db_engine):
            codes.add(str(canal["codigo"]))
    return [definition.codigo for definition in CANAL_DEFINITIONS if definition.codigo in codes]


def filter_palco_ids_by_canal_effective(
    *,
    raw_canais: str,
    user_id: int,
    chat_ids: Iterable[int],
    canal_codigo: str,
    is_maestro: bool,
    db_engine: Engine = default_engine,
) -> set[int]:
    return {
        int(chat_id)
        for chat_id in chat_ids
        if canal_is_allowed_effective(
            raw_canais=raw_canais,
            user_id=user_id,
            chat_id=int(chat_id),
            canal_codigo=canal_codigo,
            is_maestro=is_maestro,
            db_engine=db_engine,
        )
    }


def update_governance_operator(
    *,
    usr_ref: str,
    nome: str,
    username: str = "",
    perfil: str = "Governante designado",
    actor_ref: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_rbac_runtime_tables(db_engine)
    user_id = _resolve_usr_ref(usr_ref, db_engine=db_engine)
    if not user_id:
        raise RbacRuntimeError("operador_indisponivel", "Escolha um governante conhecido antes de conceder permissão.")
    safe_nome = str(nome or "Governante designado").strip()[:80] or "Governante designado"
    safe_username = str(username or "").strip().lstrip("@")[:32]
    safe_perfil = str(perfil or "Governante designado").strip()[:80] or "Governante designado"
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_operadores
                SET nome=:nome, username=:username, perfil=:perfil, habilitado=1, updated_at=:updated_at
                WHERE ui_ref=:usr_ref
                """
            ),
            {"nome": safe_nome, "username": safe_username or None, "perfil": safe_perfil, "updated_at": now, "usr_ref": str(usr_ref)},
        )
    _record_governance_audit(
        actor_ref=actor_ref,
        subject_ref=str(usr_ref),
        action="governante.atualizar",
        public_detail=f"perfil: {safe_perfil}",
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    row = _operator_public_by_usr_ref(str(usr_ref), alias_secret=alias_secret, db_engine=db_engine)
    if not row:
        raise RbacRuntimeError("operador_indisponivel", "Escolha um governante conhecido antes de conceder permissão.")
    return row


def disable_governance_operator(
    *,
    usr_ref: str,
    actor_ref: str,
    alias_secret: str,
    protected_user_ids: set[int] | None = None,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_rbac_runtime_tables(db_engine)
    user_id = _resolve_usr_ref(usr_ref, db_engine=db_engine)
    if not user_id:
        raise RbacRuntimeError("operador_indisponivel", "Escolha um governante conhecido antes de conceder permissão.")
    if protected_user_ids and int(user_id) in {int(v) for v in protected_user_ids}:
        raise ValueError("dono_protegido")
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_operadores SET habilitado=0, updated_at=:updated_at WHERE ui_ref=:usr_ref"),
            {"updated_at": now, "usr_ref": str(usr_ref)},
        )
        conn.execute(
            text(
                """
                UPDATE eq_runtime_grants
                SET habilitado=0, revoked_at=:revoked_at, updated_at=:updated_at, motivo=:motivo
                WHERE telegram_user_id=:user_id AND habilitado=1
                """
            ),
            {"revoked_at": now, "updated_at": now, "motivo": "governante removido pelo dono", "user_id": int(user_id)},
        )
    _record_governance_audit(
        actor_ref=actor_ref,
        subject_ref=str(usr_ref),
        action="governante.desativar",
        public_detail="governante desativado e concessões runtime revogadas",
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {"usr_ref": str(usr_ref), "habilitado": False}


def list_governance_audit_public(*, alias_secret: str, limit: int = 30, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_rbac_runtime_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_ref, actor_ref, subject_ref, action, public_detail, created_at
                FROM eq_governance_audit
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit or 30), 100))},
        ).mappings().all()
    return {
        "eventos": [
            {
                "event_ref": str(row["event_ref"]),
                "ator": str(row["actor_ref"] or ""),
                "alvo": str(row["subject_ref"] or ""),
                "acao": str(row["action"] or ""),
                "detalhe": str(row["public_detail"] or ""),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }


def grant_runtime_canal(
    *,
    usr_ref: str,
    grp_ref: str | None,
    canal_codigo: str,
    granted_by_ref: str,
    alias_secret: str,
    motivo: str = "",
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_rbac_runtime_tables(db_engine)
    canal = CANAL_BY_CODE.get(str(canal_codigo or "").strip())
    if not canal:
        raise RbacRuntimeError("canal_invalido", "Escolha um canal de permissão válido.")
    user_id = _resolve_usr_ref(usr_ref, db_engine=db_engine)
    if not user_id:
        raise RbacRuntimeError("operador_indisponivel", "Escolha um governante conhecido antes de conceder permissão.")
    chat_id = _resolve_grp_ref(grp_ref, db_engine=db_engine)
    if grp_ref and str(grp_ref).strip() != "*" and chat_id is None:
        raise RbacRuntimeError("grupo_indisponivel", "Escolha um grupo válido ou deixe Global.")
    now = _now_iso()
    grant_ref = _grant_ref(user_id=int(user_id), chat_id=chat_id, canal_codigo=canal.codigo, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_runtime_grants (
                    grant_ref, telegram_user_id, telegram_chat_id, canal_codigo, granted_by_ref, motivo,
                    habilitado, created_at, revoked_at, updated_at
                ) VALUES (
                    :grant_ref, :user_id, :chat_id, :canal_codigo, :granted_by_ref, :motivo,
                    1, :created_at, NULL, :updated_at
                )
                ON CONFLICT(telegram_user_id, telegram_chat_id, canal_codigo) DO UPDATE SET
                    grant_ref=excluded.grant_ref,
                    granted_by_ref=excluded.granted_by_ref,
                    motivo=excluded.motivo,
                    habilitado=1,
                    revoked_at=NULL,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "grant_ref": grant_ref,
                "user_id": int(user_id),
                "chat_id": chat_id,
                "canal_codigo": canal.codigo,
                "granted_by_ref": str(granted_by_ref or ""),
                "motivo": str(motivo or "").strip()[:240],
                "created_at": now,
                "updated_at": now,
            },
        )
    rows = list_runtime_grants_public(alias_secret=alias_secret, db_engine=db_engine)
    return next((row for row in rows["concessoes"] if row["grant_ref"] == grant_ref), {"grant_ref": grant_ref, "canal": {"codigo": canal.codigo, "nome": canal.nome}})


def revoke_runtime_canal(
    *,
    grant_ref: str,
    revoked_by_ref: str,
    db_engine: Engine = default_engine,
) -> bool:
    ensure_rbac_runtime_tables(db_engine)
    now = _now_iso()
    with db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE eq_runtime_grants
                SET habilitado=0, revoked_at=:revoked_at, updated_at=:updated_at, motivo=:motivo
                WHERE grant_ref=:grant_ref AND habilitado=1
                """
            ),
            {"grant_ref": str(grant_ref or "").strip(), "revoked_at": now, "updated_at": now, "motivo": f"revogado por {revoked_by_ref}"[:240]},
        )
    return bool(getattr(result, "rowcount", 0))


def _public_palco(chat_id: int | None, *, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    if chat_id is None:
        return {"grp_ref": "*", "titulo": "Todos os grupos autorizados"}
    rows = list_equalizador_palcos(palco_ids={int(chat_id)}, alias_secret=alias_secret, db_engine=db_engine)
    if rows:
        return {"grp_ref": rows[0].get("grp_ref"), "titulo": rows[0].get("titulo") or "Grupo"}
    return {"grp_ref": make_ui_ref("grp", int(chat_id), alias_secret), "titulo": "Grupo"}


def list_runtime_grants_public(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_rbac_runtime_tables(db_engine)
    rows: list[dict[str, object]] = []
    with db_engine.begin() as conn:
        db_rows = conn.execute(
            text(
                """
                SELECT grant_ref, telegram_user_id, telegram_chat_id, canal_codigo, granted_by_ref, motivo, created_at, updated_at
                FROM eq_runtime_grants
                WHERE habilitado=1
                ORDER BY updated_at DESC, id DESC
                """
            )
        ).mappings().all()
    for row in db_rows:
        canal = CANAL_BY_CODE.get(str(row["canal_codigo"]))
        rows.append(
            {
                "grant_ref": str(row["grant_ref"]),
                "operador": get_operador_public_by_user_id(user_id=int(row["telegram_user_id"]), alias_secret=alias_secret, perfil="Governante runtime", db_engine=db_engine),
                "palco": _public_palco(row["telegram_chat_id"], alias_secret=alias_secret, db_engine=db_engine),
                "canal": {
                    "codigo": str(row["canal_codigo"]),
                    "nome": canal.nome if canal else nome_canal_publico(str(row["canal_codigo"])),
                    "critico": bool(canal and canal.codigo in CRITICAL_CANAL_CODES),
                },
                "origem": "runtime",
                "motivo": str(row["motivo"] or ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return {
        "concessoes": rows,
        "resumo": {"ativas": len(rows), "canais_criticos": sum(1 for row in rows if row["canal"].get("critico"))},
        "observacao": "Concessões salvas no banco persistente. Variáveis do Railway continuam como base estável; runtime é camada adicional delegada pelo dono.",
    }


def rbac_runtime_catalogo_publico(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    operadores_ids: set[int] = set(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET | settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET)
    ensure_rbac_runtime_tables(db_engine)
    with db_engine.begin() as conn:
        known = conn.execute(text("SELECT telegram_user_id FROM eq_operadores WHERE habilitado=1")).scalars().all()
    operadores_ids.update(int(value) for value in known if int(value) != 0)
    operadores = [
        get_operador_public_by_user_id(
            user_id=int(user_id),
            alias_secret=alias_secret,
            perfil="Dono do código" if int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET else "Governante",
            db_engine=db_engine,
        )
        for user_id in sorted(operadores_ids)
    ]
    palcos = [{"grp_ref": "*", "titulo": "Todos os grupos autorizados"}] + list_equalizador_palcos(
        palco_ids=settings.equalizador_allowed_palco_ids(),
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return {
        "operadores": operadores,
        "palcos": palcos,
        "canais": [
            {"codigo": canal.codigo, "nome": canal.nome, "critico": canal.critico}
            for canal in CANAL_DEFINITIONS
        ],
        **list_runtime_grants_public(alias_secret=alias_secret, db_engine=db_engine),
        "auditoria_governanca": list_governance_audit_public(alias_secret=alias_secret, db_engine=db_engine),
    }
