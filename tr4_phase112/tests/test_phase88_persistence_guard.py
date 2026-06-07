from pathlib import Path

SETTINGS = Path('app/config/settings.py').read_text(encoding='utf-8')
SCRIPT = Path('scripts/persistence_guard.py').read_text(encoding='utf-8')


def test_phase88_prefers_writable_data_volume_before_app_data():
    assert 'RAILWAY_VOLUME_MOUNT_PATH' in SETTINGS
    assert 'data_path = Path("/data")' in SETTINGS
    assert 'if _path_is_writable_dir(data_path):' in SETTINGS
    assert 'return data_path' in SETTINGS
    assert 'return Path("/app/data")' in SETTINGS


def test_phase88_persistence_guard_audits_moderation_and_import_tables():
    assert 'eq_runtime_grants' in SCRIPT
    assert 'eq_security_mode' in SCRIPT
    assert 'lastfm_profiles' in SCRIPT
    assert 'track_plays' in SCRIPT
    assert 'database_not_under_data_volume' in SCRIPT


def test_phase88_guard_has_strict_mode():
    assert '--strict' in SCRIPT
    assert 'return 1 if args.strict' in SCRIPT
