from pathlib import Path

IMPORTER = Path("scripts/import_tr3_legacy_tables.py").read_text(encoding="utf-8")
REPORT = Path("scripts/tr3_legacy_import_report.py").read_text(encoding="utf-8")


def test_phase92_importer_defaults_to_railway_volume_or_data():
    assert 'RAILWAY_VOLUME_MOUNT_PATH' in IMPORTER
    assert 'return data_dir.resolve() / "app.db"' in IMPORTER
    assert 'return Path("data/app.db")' in IMPORTER


def test_phase92_importer_has_same_file_audit_mode_not_blind_write():
    assert '--allow-same-file' in IMPORTER
    assert 'same_file_noop' in IMPORTER
    assert 'Use --allow-same-file apenas para auditar' in IMPORTER


def test_phase92_import_report_compares_source_and_target_counts():
    assert 'source_counts' in REPORT
    assert 'target_counts' in REPORT
    assert 'same_file' in REPORT
    assert 'SAFE_TABLES' in REPORT
