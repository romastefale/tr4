from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
CACHE = (ROOT / "app" / "services" / "tnow_activity_cache.py").read_text(encoding="utf-8")
COVER = (ROOT / "app" / "services" / "cover_cache.py").read_text(encoding="utf-8")
DB = (ROOT / "app" / "db" / "database.py").read_text(encoding="utf-8")
MODEL = (ROOT / "app" / "models" / "tnow_private_visibility.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "tnow_privacy.py").read_text(encoding="utf-8")
COMMANDS = (ROOT / "app" / "bot" / "setup_commands.py").read_text(encoding="utf-8")


def test_tpv_owner_command_and_table_exist():
    assert 'class TnowPrivateVisibility' in MODEL
    assert 'tnow_private_visibility' in DB
    assert 'from app.models.tnow_private_visibility import TnowPrivateVisibility' in DB
    assert 'Command("tpv")' in TNOW
    assert 'message.chat.type != ChatType.PRIVATE or not is_code_owner' in TNOW
    assert 'CommandDef("tpv", "Privacidade visual no mosaico")' in COMMANDS


def test_tpv_masks_only_display_name_not_music_flow():
    assert 'tnow_privacy_service.label_for' in TNOW
    assert 'return private_label' in TNOW
    assert 'return TPV_DEFAULT_LABEL' in TNOW
    assert 'TPV_DEFAULT_LABEL = "User"' in SERVICE
    assert 'normalize_tpv_mode' in SERVICE
    assert 'set_rule' in SERVICE
    assert 'disable_rule' in SERVICE
    assert 'TPV_RULE_SET' in SERVICE
    assert 'TPV_RULE_OFF' in SERVICE


def test_tnow_cover_file_id_is_not_reused_after_track_or_cover_change():
    assert 'previous_track_id = row.track_id' in CACHE
    assert 'previous_cover_url = row.cover_url' in CACHE
    assert 'same_cover_identity' in CACHE
    assert 'elif not same_cover_identity' in CACHE
    assert 'row.cover_file_id = None' in CACHE


def test_cover_bytes_validate_current_cache_key_before_download():
    first_get = COVER.index('hit = await self.get(track_id=track_id, cover_url=cover_url)')
    direct_download = COVER.index('if file_id and not (track_id or cover_url):')
    assert first_get < direct_download
    assert 'file_id mismatch ignored for current cover key' in COVER
