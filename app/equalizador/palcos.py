from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.config import settings
from app.equalizador.identity import display_name_from_telegram_user, make_ui_ref, public_tme_url, safe_public_username


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_label(value: object, *, fallback: str) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        text_value = fallback
    # Keep labels short and UI-safe. Telegram identifiers stay server-side.
    return text_value.replace("@", "").strip()[:120] or fallback


def _public_person_payload(*, ui_ref: str, nome: object, username: object = "", perfil: object = "") -> dict[str, object]:
    safe_username = safe_public_username(username)
    name = str(nome or "").strip()[:80] or (f"@{safe_username}" if safe_username else "Operador")
    payload: dict[str, object] = {"usr_ref": str(ui_ref), "nome": name, "username": safe_username, "contato_url": public_tme_url(safe_username)}
    if perfil:
        payload["perfil"] = str(perfil)
    return payload


def ensure_equalizador_tables(db_engine: Engine = default_engine) -> None:
    """Create the Equalizador base tables used from Phase 2 onward."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS music_groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_operadores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    nome TEXT NOT NULL,
                    ui_ref TEXT NOT NULL UNIQUE,
                    perfil TEXT NOT NULL,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_palcos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    titulo TEXT,
                    ui_label TEXT NOT NULL,
                    ui_ref TEXT NOT NULL UNIQUE,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    bot_rights_json TEXT,
                    last_synced_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_operadores_ui_ref ON eq_operadores(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_palcos_ui_ref ON eq_palcos(ui_ref)"))


def upsert_operador(
    *,
    user_id: int,
    user: dict[str, object],
    perfil: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    """Persist the authorized operator without exposing Telegram IDs to the UI."""
    ensure_equalizador_tables(db_engine)
    ui_ref = make_ui_ref("usr", user_id, alias_secret)
    nome = display_name_from_telegram_user(user)
    username = str(user.get("username") or "").strip() or None
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_operadores (
                    telegram_user_id, username, nome, ui_ref, perfil, habilitado, last_seen_at, updated_at
                ) VALUES (
                    :telegram_user_id, :username, :nome, :ui_ref, :perfil, 1, :last_seen_at, :updated_at
                )
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    username=excluded.username,
                    nome=excluded.nome,
                    ui_ref=excluded.ui_ref,
                    perfil=excluded.perfil,
                    habilitado=1,
                    last_seen_at=excluded.last_seen_at,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "telegram_user_id": int(user_id),
                "username": username,
                "nome": nome,
                "ui_ref": ui_ref,
                "perfil": perfil,
                "last_seen_at": now,
                "updated_at": now,
            },
        )
    return {"ui_ref": ui_ref, "usr_ref": ui_ref, "nome": nome, "username": safe_public_username(username), "contato_url": public_tme_url(username), "perfil": perfil}


def get_operador_public_by_user_id(
    *,
    user_id: int,
    alias_secret: str,
    perfil: str = "Operador",
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    """Return the best public operator profile known locally, without raw IDs."""
    ensure_equalizador_tables(db_engine)
    ui_ref = make_ui_ref("usr", int(user_id), alias_secret)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT ui_ref, nome, username, perfil
                FROM eq_operadores
                WHERE telegram_user_id=:telegram_user_id
                LIMIT 1
                """
            ),
            {"telegram_user_id": int(user_id)},
        ).mappings().first()
    if row:
        return _public_person_payload(
            ui_ref=str(row["ui_ref"] or ui_ref),
            nome=row["nome"],
            username=row["username"],
            perfil=row["perfil"] or perfil,
        )
    return _public_person_payload(ui_ref=ui_ref, nome=perfil, username="", perfil=perfil)


def get_operador_public_by_ref(*, usr_ref: str, db_engine: Engine = default_engine) -> dict[str, object] | None:
    """Resolve a public operator alias to public profile data when locally known."""
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT ui_ref, nome, username, perfil
                FROM eq_operadores
                WHERE ui_ref=:ui_ref
                LIMIT 1
                """
            ),
            {"ui_ref": str(usr_ref)},
        ).mappings().first()
    if not row:
        return None
    return _public_person_payload(ui_ref=str(row["ui_ref"]), nome=row["nome"], username=row["username"], perfil=row["perfil"])


def sync_allowed_palcos(
    *,
    palco_ids: Iterable[int],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Mirror allowed palco IDs into eq_palcos and return sanitized UI rows."""
    ensure_equalizador_tables(db_engine)
    allowed_ids = sorted({int(value) for value in palco_ids if int(value) != 0})
    if not allowed_ids:
        return []

    rows_for_ui: list[dict[str, object]] = []
    now = _now_iso()
    with db_engine.begin() as conn:
        for chat_id in allowed_ids:
            music_group = conn.execute(
                text("SELECT title, username FROM music_groups WHERE chat_id=:chat_id"),
                {"chat_id": chat_id},
            ).mappings().first()
            fallback_alias = settings.group_alias_for_chat(chat_id) or "Grupo sem título"
            title = _clean_label(music_group["title"] if music_group else "", fallback=fallback_alias)
            username = str(music_group["username"] or "").strip() if music_group else ""
            username = username or None
            ui_ref = make_ui_ref("grp", chat_id, alias_secret)
            conn.execute(
                text(
                    """
                    INSERT INTO eq_palcos (
                        telegram_chat_id, username, titulo, ui_label, ui_ref, habilitado, updated_at
                    ) VALUES (
                        :telegram_chat_id, :username, :titulo, :ui_label, :ui_ref, 1, :updated_at
                    )
                    ON CONFLICT(telegram_chat_id) DO UPDATE SET
                        username=excluded.username,
                        titulo=excluded.titulo,
                        ui_label=excluded.ui_label,
                        ui_ref=excluded.ui_ref,
                        habilitado=1,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "telegram_chat_id": chat_id,
                    "username": username,
                    "titulo": title,
                    "ui_label": title,
                    "ui_ref": ui_ref,
                    "updated_at": now,
                },
            )
            rows_for_ui.append(
                {
                    "grp_ref": ui_ref,
                    "titulo": title,
                    "username": safe_public_username(username),
                    "contato_url": public_tme_url(username),
                    "estado": "habilitado",
                    "afinacao": "pendente",
                }
            )
    return sorted(rows_for_ui, key=lambda item: str(item["titulo"]).casefold())


def list_equalizador_palcos(
    *,
    palco_ids: Iterable[int],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Return only public palco data for the Equalizador UI."""
    return sync_allowed_palcos(palco_ids=palco_ids, alias_secret=alias_secret, db_engine=db_engine)
