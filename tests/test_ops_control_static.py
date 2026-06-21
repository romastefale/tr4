from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
OPS_BOT = (ROOT / "app" / "bot" / "ops_control.py").read_text(encoding="utf-8")
OPS_SERVICE = (ROOT / "app" / "services" / "ops_control.py").read_text(encoding="utf-8")
DB = (ROOT / "app" / "db" / "database.py").read_text(encoding="utf-8")
SETUP = (ROOT / "app" / "bot" / "setup_commands.py").read_text(encoding="utf-8")
LASTFM = (ROOT / "app" / "services" / "lastfm.py").read_text(encoding="utf-8")
SPOTIFY = (ROOT / "app" / "services" / "spotify.py").read_text(encoding="utf-8")
WEB = (ROOT / "app" / "web_music" / "router.py").read_text(encoding="utf-8")


def test_operational_router_registered_before_common_handlers():
    assert "from app.bot.ops_control import install_operational_control_middleware, router as ops_control_router" in MAIN
    assert "dispatcher.include_router(ops_control_router)" in MAIN
    assert MAIN.index("install_operational_control_middleware(dispatcher)") < MAIN.index("dispatcher.include_router(ops_control_router)") < MAIN.index("_register_handlers(dispatcher)")


def test_webhook_global_gate_covers_updates_before_dispatch():
    assert "should_drop_update_for_operational_controls" in MAIN
    assert MAIN.index("should_drop_update_for_operational_controls") < MAIN.index("await dispatcher.feed_update")
    assert "return {\"ok\": True}" in MAIN.split("should_drop_update_for_operational_controls", 1)[1]


def test_owner_commands_exist_and_are_owner_only():
    for command in ("onoff", "legacy", "listening"):
        assert f'Command("{command}")' in OPS_BOT
        assert f'CommandDef("{command}"' in SETUP
    assert "is_code_owner" in OPS_BOT
    assert "if not _owner_only(message):\n        return" in OPS_BOT


def test_silent_and_legacy_allowlists_are_narrow():
    assert '_ALLOWED_DURING_SILENT = {"start", "help"}' in OPS_SERVICE
    assert '_ALLOWED_FOR_LEGACY_RELOGIN = {"start", "help", "login", "lastfm"}' in OPS_SERVICE
    assert "callback_query" in OPS_SERVICE
    assert "inline_query" in OPS_SERVICE
    assert "message_reaction" in OPS_SERVICE


def test_legacy_tables_and_login_release_are_present():
    assert "CREATE TABLE IF NOT EXISTS operational_state" in DB
    assert "CREATE TABLE IF NOT EXISTS legacy_restricted_users" in DB
    assert "created_at" in DB and "updated_at" in DB and "spotify_tokens" in DB
    assert 'release_legacy_after_login(user_id, source="lastfm")' in LASTFM
    assert 'release_legacy_after_login(user_id, source="spotify")' in SPOTIFY


def test_listening_exports_txt_and_pdf_by_dm():
    assert "build_listening_export" in OPS_BOT
    assert "send_document" in OPS_BOT
    assert "txt_bytes" in OPS_SERVICE
    assert "pdf_bytes" in OPS_SERVICE
    assert "lastfm_profiles" in OPS_SERVICE
    assert "spotify_tokens" in OPS_SERVICE


def test_web_app_authenticated_routes_are_guarded():
    assert "_require_operational_access" in WEB
    assert "silent_mode_enabled" in WEB
    assert "is_legacy_restricted" in WEB


def test_operational_middleware_and_large_export_guard_are_present():
    assert "class OperationalControlMiddleware(BaseMiddleware)" in OPS_BOT
    assert "dispatcher.update.outer_middleware(OperationalControlMiddleware())" in OPS_BOT
    assert "build_listening_export_parts" in OPS_SERVICE
    assert "MAX_TELEGRAM_DOCUMENT_BYTES" in OPS_SERVICE

def test_listening_export_covers_interactions_and_identification():
    assert "_INTERACTION_TABLES" in OPS_SERVICE
    for table in (
        "tnow_recent_tracks",
        "track_plays",
        "track_reactions",
        "track_likes",
        "card_messages",
        "tnow_private_visibility",
    ):
        assert table in OPS_SERVICE
    assert "resumo por usuario identificado" in OPS_SERVICE
    assert "dados integrais por tabela" in OPS_SERVICE
    assert "_USER_ID_COLUMNS" in OPS_SERVICE
    assert "telegram_user_id" in OPS_SERVICE
    assert "owner_user_id" in OPS_SERVICE
    assert "interaction_row_count" in OPS_SERVICE
    assert "Usuários identificados" in OPS_BOT



def test_listening_records_raw_updates_and_api_debug():
    assert "CREATE TABLE IF NOT EXISTS bot_seen_updates" in DB
    assert "payload_json TEXT NOT NULL" in DB
    assert "record_seen_update_payload" in MAIN
    assert MAIN.index("record_seen_update_payload") < MAIN.index("await dispatcher.feed_update")
    assert "listening_known_user_ids" in OPS_SERVICE
    assert "listening_known_chat_ids" in OPS_SERVICE
    assert "get_chat" in OPS_BOT
    assert "get_chat_member" in OPS_BOT
    assert "depuracao ao vivo via Telegram Bot API" in OPS_SERVICE
