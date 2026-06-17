from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

try:
    os.makedirs("/data", exist_ok=True)
    logger.info("Database directory /data ready.")
except Exception as exc:
    logger.warning("Could not prepare /data: %s", exc)

connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def _table_columns(conn, dialect_name: str, table_name: str) -> set[str]:
    """Return existing column names for a hardcoded table.

    Used only by boot migrations. Table names are controlled by code, not user
    input. Supports SQLite in Railway and PostgreSQL compatibility.
    """
    try:
        if dialect_name == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
            return {str(row.get("name") or "") for row in rows if row.get("name")}
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).mappings().all()
        return {str(row.get("column_name") or "") for row in rows if row.get("column_name")}
    except Exception:
        logger.debug("DB column introspection skipped | table=%s", table_name, exc_info=True)
        return set()


def _reactivate_legacy_music_login_rows(conn, dialect_name: str) -> None:
    """Mark every persisted music-login row as active.

    This is a compatibility backfill for databases carried from older TR4/TR3
    builds. Some historical schemas may contain an active/enabled flag; the
    current music-only code treats the presence of Last fm or Spotify rows as
    the connection, so this migration must not require users to run /login or
    /lastfm again.
    """
    tables = ("lastfm_profiles", "spotify_tokens")
    flag_columns = ("active", "is_active", "enabled", "habilitado")
    total_changed = 0
    for table_name in tables:
        columns = _table_columns(conn, dialect_name, table_name)
        if not columns:
            continue
        if "active" not in columns:
            try:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN active INTEGER DEFAULT 1"))
                columns.add("active")
            except Exception:
                logger.debug("DB active column add skipped | table=%s", table_name, exc_info=True)
        for column in flag_columns:
            if column not in columns:
                continue
            try:
                result = conn.execute(
                    text(f"UPDATE {table_name} SET {column}=1 WHERE {column} IS NULL OR {column} != 1")
                )
                changed = getattr(result, "rowcount", 0) or 0
                total_changed += int(changed)
            except Exception:
                logger.debug("DB login activation backfill skipped | table=%s column=%s", table_name, column, exc_info=True)
    logger.info("DB music login activation backfill complete | changed=%s", total_changed)


def run_migrations(engine) -> None:
    dialect_name = engine.dialect.name
    with engine.begin() as conn:
        statements = [
            "ALTER TABLE track_plays ADD COLUMN track_name TEXT",
            "ALTER TABLE track_plays ADD COLUMN artist_name TEXT",
            "ALTER TABLE track_likes ADD COLUMN track_name TEXT",
            "ALTER TABLE track_likes ADD COLUMN artist_name TEXT",
            "ALTER TABLE track_likes ADD COLUMN liked INTEGER DEFAULT 1",
            "ALTER TABLE track_likes ADD COLUMN owner_user_id INTEGER",
        ]
        # Postgres: relaxa refresh_token pra nullable (Spotify nem sempre
        # devolve refresh em /api/token). SQLite ignora — schema legado já
        # convive bem porque o código grava `refresh_token or ""`.
        if dialect_name == "postgresql":
            statements.append(
                "ALTER TABLE spotify_tokens ALTER COLUMN refresh_token DROP NOT NULL"
            )
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                # Sprint 4 (S4.2): falhas esperadas em SQLite (ALTER COLUMN
                # não suportado) ou quando a coluna/constraint já está no
                # estado desejado. DEBUG basta pra investigar quando algo
                # novo aparecer.
                logger.debug("DB migration stmt skipped | stmt=%s", stmt, exc_info=True)

        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS lastfm_profiles (
                        user_id INTEGER PRIMARY KEY,
                        username VARCHAR NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
        except Exception:
            # Sprint 4 (S4.2): CREATE TABLE IF NOT EXISTS deveria ser
            # idempotente — falha aqui sinaliza problema sério (conexão
            # morta, schema corrompido). WARNING com traceback pra Railway
            # logs mostrarem rápido sem mascarar.
            logger.warning("DB lastfm_profiles ensure failed", exc_info=True)

        try:
            _reactivate_legacy_music_login_rows(conn, dialect_name)
        except Exception:
            logger.warning("DB music login activation backfill failed", exc_info=True)

        try:
            index_rows = conn.execute(text("PRAGMA index_list(track_likes)")).all()
            has_new_unique = any(str(row[1]) == "uq_user_owner_track_like" for row in index_rows)
            if not has_new_unique:
                conn.execute(text("DROP TABLE IF EXISTS track_likes_migrated"))
                conn.execute(
                    text(
                        """
                        CREATE TABLE track_likes_migrated (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            owner_user_id INTEGER,
                            track_id VARCHAR NOT NULL,
                            track_name VARCHAR,
                            artist_name VARCHAR,
                            liked INTEGER DEFAULT 1,
                            created_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO track_likes_migrated (
                            id, user_id, owner_user_id, track_id, track_name, artist_name, liked, created_at
                        )
                        SELECT id, user_id, owner_user_id, track_id, track_name, artist_name, liked, created_at
                        FROM track_likes
                        """
                    )
                )
                conn.execute(text("DROP TABLE track_likes"))
                conn.execute(text("ALTER TABLE track_likes_migrated RENAME TO track_likes"))
                conn.execute(text("CREATE INDEX ix_track_likes_user_id ON track_likes(user_id)"))
                conn.execute(text("CREATE INDEX ix_track_likes_owner_user_id ON track_likes(owner_user_id)"))
                conn.execute(text("CREATE INDEX ix_track_likes_track_id ON track_likes(track_id)"))
                conn.execute(
                    text("CREATE UNIQUE INDEX uq_user_owner_track_like ON track_likes(user_id, owner_user_id, track_id)")
                )
        except Exception:
            # Sprint 4 (S4.2): migração de track_likes pra UNIQUE composto.
            # Falha aqui PODE deixar schema inconsistente (tabela temp
            # `track_likes_migrated` pendurada). WARNING + traceback no
            # log do Railway pra investigar antes que vire bug em
            # produção (likes duplicados, etc).
            logger.warning("DB track_likes migration failed", exc_info=True)

        # Sprint 12: migra track_likes legado (botão ♥ removido na Sprint 8)
        # pra track_reactions, fonte única de verdade dos likes.
        # - chat_id = -1 + message_id = track_likes.id → IDs sintéticos
        #   únicos por construção, sem colisão com IDs reais do Telegram.
        # - emoji '♥' marca origem legacy (distinto de 🔥/❤/🏆 do bot).
        # - WHERE liked=1 ignora unlikes (toggle off).
        # - ON CONFLICT/INSERT OR IGNORE garante idempotência: rodar 2x
        #   no boot não duplica nada (chat=-1 + msg=id + user + '♥' é UK).
        # - track_reactions precisa existir; init_db() roda DEPOIS de
        #   run_migrations(), então usamos CREATE TABLE IF NOT EXISTS
        #   defensivo antes do INSERT.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS track_reactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        emoji VARCHAR NOT NULL,
                        track_id VARCHAR,
                        owner_user_id INTEGER,
                        created_at DATETIME NOT NULL,
                        CONSTRAINT uq_card_user_emoji UNIQUE (chat_id, message_id, user_id, emoji)
                    )
                    """
                ) if dialect_name == "sqlite" else text(
                    """
                    CREATE TABLE IF NOT EXISTS track_reactions (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        emoji VARCHAR NOT NULL,
                        track_id VARCHAR,
                        owner_user_id BIGINT,
                        created_at TIMESTAMP NOT NULL,
                        CONSTRAINT uq_card_user_emoji UNIQUE (chat_id, message_id, user_id, emoji)
                    )
                    """
                )
            )
            if dialect_name == "postgresql":
                migrate_sql = """
                    INSERT INTO track_reactions
                        (chat_id, message_id, user_id, emoji, track_id, owner_user_id, created_at)
                    SELECT -1, tl.id, tl.user_id, '♥', tl.track_id, tl.owner_user_id, tl.created_at
                    FROM track_likes tl
                    WHERE COALESCE(tl.liked, 1) = 1
                    ON CONFLICT (chat_id, message_id, user_id, emoji) DO NOTHING
                """
            else:
                migrate_sql = """
                    INSERT OR IGNORE INTO track_reactions
                        (chat_id, message_id, user_id, emoji, track_id, owner_user_id, created_at)
                    SELECT -1, tl.id, tl.user_id, '♥', tl.track_id, tl.owner_user_id, tl.created_at
                    FROM track_likes tl
                    WHERE COALESCE(tl.liked, 1) = 1
                """
            result = conn.execute(text(migrate_sql))
            migrated = getattr(result, "rowcount", -1)
            if migrated > 0:
                logger.info("Sprint 12: migrated %d track_likes → track_reactions", migrated)
        except Exception:
            logger.warning("Sprint 12 likes→reactions migration failed", exc_info=True)


        # Cache persistente de trechos de letra usados pelo /tly. Colunas são
        # texto/datetime simples, então CREATE TABLE IF NOT EXISTS serve igual
        # pros dois dialetos.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS lyrics_snippet_cache (
                        cache_key VARCHAR PRIMARY KEY,
                        artist_norm VARCHAR NOT NULL,
                        title_norm VARCHAR NOT NULL,
                        artist VARCHAR NOT NULL,
                        title VARCHAR NOT NULL,
                        snippet TEXT,
                        source VARCHAR,
                        channel_chat_id BIGINT,
                        channel_message_id INTEGER,
                        archived_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """,
                        expires_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            existing_columns = _table_columns(conn, dialect_name, "lyrics_snippet_cache")
            lyric_archive_columns = {
                "channel_chat_id": "BIGINT",
                "channel_message_id": "INTEGER",
                "archived_at": "TIMESTAMP" if dialect_name == "postgresql" else "DATETIME",
            }
            for column_name, column_type in lyric_archive_columns.items():
                if column_name in existing_columns:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE lyrics_snippet_cache ADD COLUMN {column_name} {column_type}"))
                    existing_columns.add(column_name)
                except Exception:
                    logger.debug(
                        "DB lyrics archive column add skipped | column=%s",
                        column_name,
                        exc_info=True,
                    )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lyrics_snippet_cache_artist_norm ON lyrics_snippet_cache(artist_norm)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lyrics_snippet_cache_title_norm ON lyrics_snippet_cache(title_norm)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lyrics_snippet_cache_expires_at ON lyrics_snippet_cache(expires_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lyrics_snippet_cache_channel_chat_id ON lyrics_snippet_cache(channel_chat_id)"))
        except Exception:
            logger.warning("DB lyrics_snippet_cache table creation failed", exc_info=True)


        # Perfil Telegram persistente usado como identidade visual.
        # Os provedores musicais permanecem dados técnicos; o card/mosaico usa
        # este cadastro primeiro e cai para User quando não houver dado seguro.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS telegram_user_profiles (
                        user_id """ + ("BIGINT" if dialect_name == "postgresql" else "INTEGER") + """ PRIMARY KEY,
                        first_name VARCHAR,
                        last_name VARCHAR,
                        username VARCHAR,
                        full_name VARCHAR,
                        photo_url TEXT,
                        language_code VARCHAR,
                        source VARCHAR,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_user_profiles_username ON telegram_user_profiles(username)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_user_profiles_source ON telegram_user_profiles(source)"))
        except Exception:
            logger.warning("DB telegram_user_profiles table creation failed", exc_info=True)

        # Cache persistente do mosaico /tnow. Fonte de verdade por usuário:
        # Last fm username + faixa ouvida + quando foi ouvida/observada.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tnow_recent_tracks (
                        user_id """ + ("BIGINT" if dialect_name == "postgresql" else "INTEGER") + """ PRIMARY KEY,
                        lastfm_username VARCHAR,
                        source VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        track_id VARCHAR,
                        track_name VARCHAR NOT NULL,
                        artist VARCHAR NOT NULL,
                        album_name VARCHAR,
                        track_url TEXT,
                        cover_url TEXT,
                        cover_file_id VARCHAR,
                        is_live BOOLEAN NOT NULL DEFAULT """ + ("false" if dialect_name == "postgresql" else "0") + """,
                        played_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """,
                        observed_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        fetched_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        expires_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        raw_age_seconds FLOAT,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_lastfm_username ON tnow_recent_tracks(lastfm_username)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_status ON tnow_recent_tracks(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_track_id ON tnow_recent_tracks(track_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_played_at ON tnow_recent_tracks(played_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_observed_at ON tnow_recent_tracks(observed_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_fetched_at ON tnow_recent_tracks(fetched_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_recent_tracks_expires_at ON tnow_recent_tracks(expires_at)"))
        except Exception:
            logger.warning("DB tnow_recent_tracks table creation failed", exc_info=True)

        # Máscara visual owner-only para nomes no /tnow/mosaico. Não altera
        # Last fm/Spotify nem a música; apenas o rótulo renderizado.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tnow_private_visibility (
                        telegram_user_id """ + ("BIGINT" if dialect_name == "postgresql" else "INTEGER") + """ PRIMARY KEY,
                        mode VARCHAR NOT NULL DEFAULT 'all',
                        display_label VARCHAR NOT NULL DEFAULT 'User',
                        enabled BOOLEAN NOT NULL DEFAULT """ + ("true" if dialect_name == "postgresql" else "1") + """,
                        created_by_owner_id """ + ("BIGINT" if dialect_name == "postgresql" else "INTEGER") + """,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_private_visibility_mode ON tnow_private_visibility(mode)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tnow_private_visibility_enabled ON tnow_private_visibility(enabled)"))
        except Exception:
            logger.warning("DB tnow_private_visibility table creation failed", exc_info=True)

        # Cache persistente de capas musicais por file_id. Fase 3: o canal
        # técnico arquiva a mídia; o banco indexa por faixa/URL/hash.
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS cover_files (
                        cache_key VARCHAR PRIMARY KEY,
                        spotify_track_id VARCHAR,
                        cover_url TEXT,
                        cover_hash VARCHAR,
                        file_id VARCHAR NOT NULL,
                        file_unique_id VARCHAR,
                        width INTEGER,
                        height INTEGER,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cover_files_spotify_track_id ON cover_files(spotify_track_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cover_files_cover_hash ON cover_files(cover_hash)"))
        except Exception:
            logger.warning("DB cover_files table creation failed", exc_info=True)

        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS canvas_files (
                        track_id VARCHAR PRIMARY KEY,
                        file_id VARCHAR NOT NULL,
                        file_unique_id VARCHAR,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
        except Exception:
            logger.warning("DB canvas_files table creation failed", exc_info=True)

        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS canvas_processed_files (
                        cache_key VARCHAR PRIMARY KEY,
                        spotify_track_id VARCHAR NOT NULL,
                        canvas_fingerprint VARCHAR NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        process_kind VARCHAR NOT NULL,
                        process_version VARCHAR NOT NULL,
                        file_id VARCHAR NOT NULL,
                        file_unique_id VARCHAR,
                        created_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL,
                        updated_at """ + ("TIMESTAMP" if dialect_name == "postgresql" else "DATETIME") + """ NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_canvas_processed_files_spotify_track_id ON canvas_processed_files(spotify_track_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_canvas_processed_files_fingerprint ON canvas_processed_files(canvas_fingerprint)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_canvas_processed_files_kind ON canvas_processed_files(process_kind)"))
        except Exception:
            logger.warning("DB canvas_processed_files table creation failed", exc_info=True)


def init_db() -> None:
    try:
        from app.models.card_message import CardMessage  # noqa: F401  # Sprint 8
        from app.models.canvas_file import CanvasFile  # noqa: F401  # cache file_id
        from app.models.canvas_processed_file import CanvasProcessedFile  # noqa: F401  # Canvas derivado com áudio
        from app.models.cover_file import CoverFile  # noqa: F401  # cache de capas
        from app.models.lyrics_snippet_cache import LyricsSnippetCache  # noqa: F401  # cache de trechos /tly
        from app.models.lastfm_profile import LastfmProfile  # noqa: F401
        from app.models.spotify_token import SpotifyToken  # noqa: F401
        from app.models.track_like import TrackLike  # noqa: F401
        from app.models.track_play import TrackPlay  # noqa: F401
        from app.models.track_reaction import TrackReaction  # noqa: F401  # Sprint 8
        from app.models.tnow_recent_track import TnowRecentTrack  # noqa: F401  # cache /tnow
        from app.models.tnow_private_visibility import TnowPrivateVisibility  # noqa: F401  # máscara /tpv
        from app.models.telegram_user_profile import TelegramUserProfile  # noqa: F401  # identidade visual Telegram

        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized.")
    except Exception as exc:
        logger.exception("Database initialization failed: %s", exc)
