from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref

VALID_SECURITY_MODES = {"normal", "alerta", "restrito"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _safe_text(value: object, *, limit: int = 240, fallback: str = "") -> str:
    text_value = str(value or fallback).replace("\x00", " ").strip()
    text_value = " ".join(text_value.split())
    return text_value[:limit]


def _safe_ref(value: object | None, *, fallback: str = "-") -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    allowed_prefixes = ("usr_", "grp_", "msg_", "evt_", "hist_", "rad_", "ddx_", "sec_", "exp_", "sess_")
    if text_value.startswith(allowed_prefixes):
        return text_value[:80]
    return fallback


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ensure_security_tables(db_engine: Engine = default_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_security_mode (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    modo TEXT NOT NULL DEFAULT 'normal',
                    motivo TEXT,
                    ator_ref TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_security_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    tipo TEXT NOT NULL,
                    area TEXT NOT NULL,
                    ator_ref TEXT,
                    palco_ref TEXT,
                    status TEXT NOT NULL,
                    resumo_publico TEXT NOT NULL,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_security_audit_created ON eq_security_audit(created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_security_audit_ref ON eq_security_audit(event_ref)"))
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO eq_security_mode (id, modo, motivo, ator_ref, updated_at)
                VALUES (1, 'normal', 'modo inicial', NULL, :updated_at)
                """
            ),
            {"updated_at": _now_iso()},
        )


def record_security_audit(
    *,
    tipo: str,
    area: str,
    ator_ref: str | None = None,
    palco_ref: str | None = None,
    status: str = "registrado",
    resumo_publico: str = "Evento registrado.",
    meta: dict[str, Any] | None = None,
    alias_secret: str = "",
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_security_tables(db_engine)
    now = _now_iso()
    seed = f"{now}:{tipo}:{area}:{ator_ref}:{palco_ref}:{os.urandom(8).hex()}"
    event_ref = make_ui_ref("sec", abs(hash((seed, alias_secret))) % (10**12), alias_secret or "seguranca")
    row = {
        "event_ref": event_ref,
        "tipo": _safe_text(tipo, limit=80, fallback="evento"),
        "area": _safe_text(area, limit=80, fallback="seguranca"),
        "ator_ref": _safe_ref(ator_ref),
        "palco_ref": _safe_ref(palco_ref),
        "status": _safe_text(status, limit=60, fallback="registrado"),
        "resumo_publico": _safe_text(resumo_publico, limit=360, fallback="Evento registrado."),
        "meta_json": _json_dumps(_sanitize_meta(meta or {})),
        "created_at": now,
    }
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_security_audit
                  (event_ref, tipo, area, ator_ref, palco_ref, status, resumo_publico, meta_json, created_at)
                VALUES
                  (:event_ref, :tipo, :area, :ator_ref, :palco_ref, :status, :resumo_publico, :meta_json, :created_at)
                """
            ),
            row,
        )
    return _public_audit_row(row)


def _sanitize_meta(meta: dict[str, Any]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in (meta or {}).items():
        k = _safe_text(key, limit=40)
        if not k:
            continue
        if any(token in k.lower() for token in ("token", "secret", "senha", "password", "authorization")):
            clean[k] = "[oculto]"
        elif isinstance(value, bool) or value is None:
            clean[k] = value
        elif isinstance(value, (int, float)):
            clean[k] = value
        else:
            clean[k] = _safe_text(value, limit=180)
    return clean


def _public_audit_row(row: dict[str, Any]) -> dict[str, object]:
    meta: dict[str, object]
    try:
        meta = json.loads(str(row.get("meta_json") or "{}"))
    except json.JSONDecodeError:
        meta = {}
    return {
        "event_ref": str(row.get("event_ref") or ""),
        "tipo": _safe_text(row.get("tipo"), limit=80, fallback="evento"),
        "area": _safe_text(row.get("area"), limit=80, fallback="seguranca"),
        "ator_ref": _safe_ref(row.get("ator_ref")),
        "palco_ref": _safe_ref(row.get("palco_ref")),
        "status": _safe_text(row.get("status"), limit=60, fallback="registrado"),
        "resumo": _safe_text(row.get("resumo_publico"), limit=360, fallback="Evento registrado."),
        "meta": meta,
        "created_at": str(row.get("created_at") or ""),
    }


def get_security_mode(db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_security_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT modo, motivo, ator_ref, updated_at FROM eq_security_mode WHERE id=1 LIMIT 1")).mappings().first()
    if not row:
        return {"modo": "normal", "nome": "Normal", "motivo": "modo inicial", "ator_ref": None, "updated_at": _now_iso()}
    modo = str(row["modo"] or "normal")
    return {
        "modo": modo if modo in VALID_SECURITY_MODES else "normal",
        "nome": {"normal": "Normal", "alerta": "Alerta", "restrito": "Restrito"}.get(modo, "Normal"),
        "motivo": _safe_text(row["motivo"], limit=180, fallback=""),
        "ator_ref": _safe_ref(row["ator_ref"]),
        "updated_at": str(row["updated_at"]),
    }


def set_security_mode(
    *,
    modo: str,
    motivo: str,
    ator_ref: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_security_tables(db_engine)
    value = str(modo or "").strip().lower()
    if value not in VALID_SECURITY_MODES:
        raise ValueError("modo_invalido")
    now = _now_iso()
    clean_reason = _safe_text(motivo, limit=180, fallback=f"modo {value}")
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE eq_security_mode SET modo=:modo, motivo=:motivo, ator_ref=:ator_ref, updated_at=:updated_at WHERE id=1"),
            {"modo": value, "motivo": clean_reason, "ator_ref": _safe_ref(ator_ref), "updated_at": now},
        )
    record_security_audit(
        tipo="modo_seguranca",
        area="seguranca",
        ator_ref=ator_ref,
        status="ok",
        resumo_publico=f"Modo de segurança alterado para {value}.",
        meta={"modo": value, "motivo": clean_reason},
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return get_security_mode(db_engine)


def security_action_allowed(*, is_maestro: bool, action_code: str | None = None, db_engine: Engine = default_engine) -> tuple[bool, str]:
    mode = get_security_mode(db_engine)
    modo = str(mode.get("modo") or "normal")
    if modo != "restrito":
        return True, "liberado"
    if is_maestro:
        return True, "modo restrito: dono do código liberado"
    code = str(action_code or "")
    if code.startswith("seguranca.") or code in {"historico.ver"}:
        return True, "modo restrito: leitura de segurança liberada"
    return False, "Modo restrito ativo. Ações de governantes ficam bloqueadas até o dono retomar normalidade."


def assert_security_action_allowed(*, is_maestro: bool, action_code: str | None = None, db_engine: Engine = default_engine) -> None:
    ok, reason = security_action_allowed(is_maestro=is_maestro, action_code=action_code, db_engine=db_engine)
    if not ok:
        raise PermissionError(reason)


def list_security_audit(*, limit: int = 80, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_security_tables(db_engine)
    safe_limit = max(1, min(int(limit), 300))
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_ref, tipo, area, ator_ref, palco_ref, status, resumo_publico, meta_json, created_at
                FROM eq_security_audit
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).mappings().all()
    return [_public_audit_row(dict(row)) for row in rows]


def cleanup_security_audit(*, older_than_days: int, db_engine: Engine = default_engine) -> int:
    ensure_security_tables(db_engine)
    days = max(1, min(int(older_than_days or 90), 3650))
    cutoff = (_now() - timedelta(days=days)).isoformat()
    with db_engine.begin() as conn:
        result = conn.execute(text("DELETE FROM eq_security_audit WHERE created_at < :cutoff"), {"cutoff": cutoff})
    return int(getattr(result, "rowcount", 0) or 0)


def _table_exists(conn: Any, table_name: str) -> bool:
    try:
        return inspect(conn).has_table(table_name)
    except Exception:
        return False


def _safe_scalar_row(row: Any, columns: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for col in columns:
        try:
            if col in row.keys():
                out[col] = _safe_text(row[col], limit=260)
        except Exception:
            continue
    return out


def _select_public_rows(conn: Any, table_name: str, *, columns: list[str], order_column: str = "id", limit: int = 250) -> list[dict[str, object]]:
    if not _table_exists(conn, table_name):
        return []
    available = [str(row[1]) for row in conn.execute(text(f"PRAGMA table_info({table_name})")).all()]
    selected = [col for col in columns if col in available]
    if not selected:
        return []
    order = "created_at" if "created_at" in available else ("updated_at" if "updated_at" in available else (order_column if order_column in available else "id"))
    sql = f"SELECT {', '.join(selected)} FROM {table_name} ORDER BY {order} DESC LIMIT :limit"
    rows = conn.execute(text(sql), {"limit": max(1, min(int(limit), 500))}).mappings().all()
    return [_safe_scalar_row(row, selected) for row in rows]


def _collect_rows(db_engine: Engine = default_engine, *, limit_per_table: int = 250) -> dict[str, list[dict[str, object]]]:
    ensure_security_tables(db_engine)
    datasets: dict[str, list[dict[str, object]]] = {}
    with db_engine.begin() as conn:
        datasets["seguranca"] = _select_public_rows(
            conn,
            "eq_security_audit",
            columns=["event_ref", "tipo", "area", "ator_ref", "palco_ref", "status", "resumo_publico", "created_at"],
            limit=limit_per_table,
        )
        datasets["mesa"] = _select_public_rows(
            conn,
            "eq_historico",
            columns=["historico_ref", "ator_ref", "palco_ref", "alvo_ref", "ajuste", "status", "resumo_publico", "created_at"],
            limit=limit_per_table,
        )
        datasets["radio"] = _select_public_rows(
            conn,
            "eq_radio_history",
            columns=["event_ref", "palco_ref", "ator_ref", "draft_ref", "msg_ref", "tipo", "resumo_publico", "media_kind", "fixar", "fixado", "created_at"],
            limit=limit_per_table,
        )
        datasets["ddx"] = _select_public_rows(
            conn,
            "eq_ddx_events",
            columns=["event_ref", "scheduled_ref", "palco_ref", "mode", "status", "actor_name", "actor_username", "matched_words_json", "text_preview", "public_detail", "created_at"],
            limit=limit_per_table,
        )
        datasets["reacoes"] = _select_public_rows(
            conn,
            "eq_reaction_events",
            columns=["event_ref", "palco_ref", "msg_ref", "actor_kind", "actor_ref", "actor_label", "username", "old_summary", "new_summary", "status", "created_at"],
            limit=limit_per_table,
        )
        datasets["novos_membros"] = _select_public_rows(
            conn,
            "eq_new_member_events",
            columns=["event_ref", "palco_ref", "watch_ref", "alvo_ref", "msg_ref", "status", "actor_name", "actor_username", "links_json", "text_preview", "created_at"],
            limit=limit_per_table,
        )
    return {key: rows for key, rows in datasets.items() if rows}

def export_security_jsonl(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    datasets = _collect_rows(db_engine)
    lines: list[str] = []
    for area, rows in datasets.items():
        for row in rows:
            lines.append(_json_dumps({"area": area, **row}))
    body = "\n".join(lines) + ("\n" if lines else "")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    signature = hmac.new((alias_secret or "seguranca").encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "formato": "jsonl",
        "linhas": len(lines),
        "sha256": digest,
        "assinatura_hmac_sha256": signature,
        "conteudo": body,
        "created_at": _now_iso(),
    }


def _fernet_from_password(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    return Fernet(key)


def export_security_encrypted(*, password: str, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    if len(str(password or "")) < 8:
        raise ValueError("senha_curta")
    export = export_security_jsonl(alias_secret=alias_secret, db_engine=db_engine)
    salt = os.urandom(16)
    token = _fernet_from_password(str(password), salt).encrypt(str(export["conteudo"]).encode("utf-8"))
    return {
        "formato": "fernet-pbkdf2-sha256",
        "linhas": export["linhas"],
        "sha256_plaintext": export["sha256"],
        "salt_b64": base64.urlsafe_b64encode(salt).decode("ascii"),
        "conteudo_b64": token.decode("ascii"),
        "created_at": _now_iso(),
    }


def security_dashboard_public(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_security_tables(db_engine)
    audit = list_security_audit(limit=20, db_engine=db_engine)
    export_preview = export_security_jsonl(alias_secret=alias_secret, db_engine=db_engine)
    return {
        "modo": get_security_mode(db_engine),
        "auditoria": audit,
        "resumo": {"eventos_recentes": len(audit), "linhas_exportaveis": export_preview["linhas"], "sha256": export_preview["sha256"]},
        "diagnostico": {"tabelas": sorted(_collect_rows(db_engine, limit_per_table=1).keys())},
    }
