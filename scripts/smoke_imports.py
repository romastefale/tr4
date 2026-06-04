from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep the smoke test isolated from Railway volume/local production DB.
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
os.environ.setdefault("TR3_DATABASE_URL", f"sqlite:///{tmp.name}")
os.environ.setdefault("TR3_DATA_DIR", tempfile.gettempdir())
os.environ.setdefault("TR3_TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TR3_ROOT_USER_ID", "1")
os.environ.setdefault("TR3_SECOND_MODERATOR_ID", "2")
os.environ.setdefault("TR3_THIRD_MODERATOR_ID", "3")
os.environ.setdefault("TR3_MANAGED_GROUP_IDS", "-1001")

from app.bot.intent import detect_intent
from app.bot.music_extras import register_music_extra_handlers
from app.bot.telegram import _CARD_EMOJI_DEFAULT, bot_dispatcher
from app.bot.setup_commands import command_scope_summary, private_command_names_for_access, sync_active_grant_command_scopes
from app.btb import btb_router
from app.db.database import engine, init_db, run_migrations
from app.main import app, dispatcher
from app.moderation_tigrao import router as tigrao_router
from app.moderation_tigrao.parsers import (
    parse_chat_id,
    parse_duration,
    parse_message_link,
    parse_user_id,
)
from app.moderation_tigrao.permissions import MODERATOR_IDS, is_moderator_user
from app.moderation_tigrao.state import (
    cleanup_expired_sessions as tigrao_cleanup_expired_sessions,
    current_user_id as tigrao_current_user_id,
    reset_current_user as tigrao_reset_current_user,
    session_diagnostics as tigrao_session_diagnostics,
    set_current_user as tigrao_set_current_user,
)
from app.moderation_tigrao.keyboards import radio_keyboard, user_actions_keyboard
from app.services.lastfm import _stable_track_id, lastfm_service
from app.services.music import music_service
from app.services.spotify import spotify_service
from app.security.managed_groups import (
    bootstrap_from_env as bootstrap_managed_groups_from_env,
    is_managed_group,
)
from app.security.permissions import (
    delegable_full_permissions,
    ensure_tables as ensure_permission_tables,
    grant_permission,
    grant_permissions,
    has_any_radio_permission,
    has_permission,
    moderation_full_permissions,
    radio_full_permissions,
    list_active_grant_user_ids,
    require_current_actor_permission,
    set_current_actor,
    reset_current_actor,
    get_current_actor,
)
from app.security.private_panels import (
    ensure_tables as ensure_private_panel_tables,
    get_panel,
    remember_ephemeral,
    upsert_panel,
)
from app.security.audit import (
    cleanup_audit_events_older_than,
    ensure_tables as ensure_audit_tables,
    export_audit_events_jsonl,
    list_recent_events,
    log_audit_event,
)
from app.security.radio_drafts import (
    create_text_draft,
    ensure_tables as ensure_radio_draft_tables,
    get_draft,
    mark_cancelled,
)
from app.security.radio_templates import (
    create_template,
    ensure_tables as ensure_radio_template_tables,
    find_recent_duplicate,
    list_post_history,
    list_templates,
    message_hash,
    record_post_history,
)
from app.security.radio_schedules import (
    create_schedule,
    ensure_tables as ensure_radio_schedule_tables,
    get_group_policy,
    is_quiet_now,
    list_schedules,
    parse_utc_offset_minutes,
    set_group_policy,
)
from app.security.panic import (
    get_security_mode,
    record_security_signal,
    reset_security_signals,
    security_status,
    set_security_mode,
)
from app.security.task_registry import task_count
from app.security.rate_limit import check_command_rate_limit, rate_limit_status, reset_rate_limits
from app.security.alerts import send_security_alert
from app.security.error_handling import normalize_exception
from app.security.callbacks import CallbackParseError, page_number, trailing_int
from app.security.critical_operations import begin_critical_operation, cleanup_critical_operations_older_than, export_critical_operations_jsonl, finish_critical_operation, list_critical_operations, replay_packet
from app.security.signed_exports import create_signed_jsonl_export, sha256_hex, count_jsonl_records
from app.security.encrypted_exports import build_decryption_keyring, create_encrypted_signed_export, decrypt_encrypted_export, derive_export_key, keyring_public_summary, parse_decryption_keyring
from app.security.bot_rights import BotRights, bot_rights_capabilities, format_bot_rights, format_rights_refresh_report, refresh_managed_group_rights
from app.security.session_store import (
    acquire_operational_lock,
    cleanup_expired_operational_locks,
    delete_private_session,
    ensure_tables as ensure_session_store_tables,
    list_operational_locks,
    list_private_sessions,
    load_private_session,
    release_operational_lock,
    save_private_session,
)


def _assert_parsers() -> None:
    assert parse_chat_id("1001234567890") == -1001234567890
    assert parse_chat_id("-1001234567890") == -1001234567890
    assert parse_user_id("6059326627") == 6059326627
    assert parse_duration("10m").total_seconds() == 600
    assert parse_duration("2h").total_seconds() == 7200
    assert parse_duration("3d").days == 3
    assert parse_duration("i") == "indefinido"
    assert parse_duration("x") == "desmutar"

    chat_id, message_id = parse_message_link("https://t.me/c/1234567890/55")
    assert chat_id == -1001234567890
    assert message_id == 55

    chat_id, message_id = parse_message_link("https://t.me/somegroup/77")
    assert chat_id == "@somegroup"
    assert message_id == 77


def main() -> None:
    init_db()
    run_migrations(engine)
    bootstrap_managed_groups_from_env()
    ensure_permission_tables()
    ensure_private_panel_tables()
    ensure_audit_tables()
    ensure_radio_draft_tables()
    ensure_radio_template_tables()
    ensure_radio_schedule_tables()
    ensure_session_store_tables()

    assert detect_intent("tocando") == "play"
    assert detect_intent("texto qualquer") is None

    lastfm_track_id = _stable_track_id("A Very Long Artist Name", "A Very Long Track Name")
    assert lastfm_track_id.startswith("lfm:")
    assert len(f"like:123456789:{lastfm_track_id}".encode("utf-8")) <= 64

    _assert_parsers()

    assert is_moderator_user(1) is True
    assert {1, 2, 3}.issubset(MODERATOR_IDS)
    assert is_managed_group(-1001) is True
    grant_permission(user_id=42, chat_id=-1001, permission="moderation.delete", granted_by_user_id=1)
    grant_permissions(user_id=43, chat_id=-1001, permissions=("moderation.view",), granted_by_user_id=1)
    grant_permission(user_id=44, chat_id=-1001, permission="radio.post_text", granted_by_user_id=1)
    grant_permissions(user_id=45, chat_id=-1001, permissions=("radio.templates.use", "radio.history.read"), granted_by_user_id=1)
    assert "moderation.delete" in moderation_full_permissions()
    assert "radio.post_text" in radio_full_permissions()
    assert "radio.broadcast" in delegable_full_permissions()
    assert has_permission(42, -1001, "moderation.delete") is True
    assert has_permission(42, -1002, "moderation.delete") is False
    assert has_permission(44, -1001, "radio.post_text") is True
    assert has_any_radio_permission(45) is True
    assert 44 in list_active_grant_user_ids()
    assert callable(sync_active_grant_command_scopes)
    limited_radio = radio_keyboard(
        allowed_permissions={"radio.post_text", "radio.pin"},
        is_root=False,
        has_selected_chat=True,
        bot_capabilities=set(),
    )
    assert "tigrao:rights:missing:pin" in str(limited_radio)
    limited_actions = user_actions_keyboard(bot_capabilities=set())
    assert "tigrao:rights:missing:restrict" in str(limited_actions)
    sample_rights = BotRights(
        chat_id=-1001,
        status="administrator",
        is_admin=True,
        can_delete_messages=True,
        can_restrict_members=False,
        can_pin_messages=True,
    )
    assert bot_rights_capabilities(sample_rights) == {"admin", "delete", "pin"}
    assert "fixar=sim" in format_bot_rights(sample_rights)
    report = format_rights_refresh_report({"total": 1, "admin": 1, "musical_only": 0, "error": 0, "rows": [{"chat_id": -1001, "is_admin": True, "capabilities": ["admin", "pin"]}]})
    assert "Total: 1" in report
    assert callable(refresh_managed_group_rights)
    assert isinstance(export_audit_events_jsonl(limit=10), bytes)
    assert isinstance(export_critical_operations_jsonl(limit=10), bytes)
    signed = create_signed_jsonl_export(source="smoke", base_filename="smoke.jsonl", data=b"{\"a\":1}\n")
    assert signed.compressed_filename == "smoke.jsonl.gz"
    assert signed.record_count == 1
    assert signed.gzip_sha256 == sha256_hex(signed.gzip_bytes)
    assert count_jsonl_records(signed.raw_bytes) == 1
    encrypted = create_encrypted_signed_export(signed_export=signed, secret="smoke-passphrase")
    assert encrypted.encrypted_filename.endswith(".enc")
    assert decrypt_encrypted_export(ciphertext=encrypted.ciphertext_bytes, manifest_bytes=encrypted.manifest_bytes, secret="smoke-passphrase") == signed.gzip_bytes
    assert parse_decryption_keyring("old=secret") == {"old": "secret"}
    keyring = build_decryption_keyring(current_key_id="current", current_secret="smoke-passphrase", extra_keyring_raw="old=secret")
    assert decrypt_encrypted_export(ciphertext=encrypted.ciphertext_bytes, manifest_bytes=encrypted.manifest_bytes, keyring=keyring) == signed.gzip_bytes
    summary = keyring_public_summary(current_key_id="current", extra_keyring_raw="old=secret")
    assert summary["current_key_id"] == "current" and summary["legacy_key_ids"] == ["old"]
    assert len(derive_export_key("smoke-passphrase")[0]) == 32
    assert callable(cleanup_audit_events_older_than)
    assert callable(cleanup_critical_operations_older_than)
    op_id = begin_critical_operation(
        category="smoke",
        action="critical",
        operation_key="smoke:critical",
        actor_user_id=1,
        chat_id=-1001,
        intent={"hello": "world"},
    )
    assert finish_critical_operation(op_id, status="success", result={"ok": True}) is True
    assert any(row["operation_id"] == op_id for row in list_critical_operations(limit=5))
    assert op_id in replay_packet(op_id)
    critical_lock = acquire_operational_lock("smoke_critical_action", ttl_seconds=5, metadata={"kind": "smoke"})
    assert critical_lock.acquired is True
    duplicate_lock = acquire_operational_lock("smoke_critical_action", ttl_seconds=5)
    assert duplicate_lock.acquired is False
    assert release_operational_lock("smoke_critical_action", owner=critical_lock.owner) is True
    save_private_session(namespace="smoke", user_id=99, payload={"k": "v"})
    assert load_private_session(namespace="smoke", user_id=99)["k"] == "v"
    assert list_private_sessions(namespace="smoke")
    assert delete_private_session(namespace="smoke", user_id=99) is True
    lock = acquire_operational_lock("smoke.lock", ttl_seconds=30)
    assert lock.acquired is True
    assert any(row["lock_name"] == "smoke.lock" for row in list_operational_locks())
    assert release_operational_lock("smoke.lock", owner=lock.owner) is True
    assert cleanup_expired_operational_locks() >= 0
    tigrao_context_token = tigrao_set_current_user(44)
    assert tigrao_current_user_id() == 44
    tigrao_reset_current_user(tigrao_context_token)
    assert tigrao_current_user_id() is None
    actor_token = set_current_actor(44)
    assert get_current_actor() == 44
    reset_current_actor(actor_token)
    assert get_current_actor() is None
    assert isinstance(tigrao_session_diagnostics(), dict)
    assert tigrao_cleanup_expired_sessions() >= 0
    set_current_actor(42)
    require_current_actor_permission(-1001, "moderation.delete")
    upsert_panel(actor_user_id=42, chat_id=42, message_id=100, panel_type="tigrao")
    assert get_panel(42)["message_id"] == 100
    remember_ephemeral(actor_user_id=42, chat_id=42, message_id=101, reason="smoke")
    event_id = log_audit_event(category="smoke", action="phase5", status="success", actor_user_id=1)
    assert event_id
    assert list_recent_events(category="smoke")
    draft_id = create_text_draft(actor_user_id=1, target_chat_id=-1001, text_value="smoke", pin=False)
    assert get_draft(draft_id)["kind"] == "text"
    mark_cancelled(draft_id)
    assert get_draft(draft_id)["status"] == "cancelled"
    template_id = create_template(name="smoke", body="template body", created_by_user_id=1)
    assert any(int(t["id"]) == template_id for t in list_templates())
    h = message_hash("template body")
    record_post_history(actor_user_id=1, chat_id=-1001, kind="text", message_hash_value=h, status="success")
    assert find_recent_duplicate(chat_id=-1001, message_hash_value=h)
    assert list_post_history(chat_id=-1001)
    assert trailing_int("radio:template:use:12", prefix="radio:template:use:") == 12
    assert page_number("radio:history:page:2", prefix="radio:history:page:") == 2
    set_group_policy(chat_id=-1001, quiet_from="23:00", quiet_to="08:00", utc_offset_minutes=parse_utc_offset_minutes("-03:00"), updated_by_user_id=1)
    assert get_group_policy(-1001)["quiet_from"] == "23:00"
    assert is_quiet_now(-1001) in {True, False}
    schedule_id = create_schedule(template_id=template_id, chat_id=-1001, interval_seconds=3600, created_by_user_id=1, pin=False)
    assert any(int(row["id"]) == schedule_id for row in list_schedules(chat_id=-1001))
    assert normalize_exception(RuntimeError("smoke")).category == "unexpected"
    reset_security_signals()
    assert get_security_mode() in {"normal", "alert", "restricted", "panic_stop"}
    record_security_signal("smoke.signal", threshold=0, reason="smoke")
    set_security_mode("normal", reason="smoke reset")
    assert "signals" in security_status()
    reset_rate_limits()
    assert check_command_rate_limit("monthfm", 1, -1001).allowed is True
    assert rate_limit_status()["enabled"] in {True, False}
    assert send_security_alert is not None
    assert task_count() >= 0
    assert _CARD_EMOJI_DEFAULT
    assert register_music_extra_handlers is not None
    assert tigrao_router is not None
    assert btb_router is not None
    assert bot_dispatcher is dispatcher
    assert app is not None
    assert music_service is not None
    assert spotify_service is not None
    assert lastfm_service is not None

    print("TR3 smoke imports ok")


if __name__ == "__main__":
    main()
