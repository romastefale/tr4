from pathlib import Path

SCRIPT = Path("scripts/tr3_import_status.py").read_text(encoding="utf-8")
FINALIZE = Path("scripts/tr3_import_finalize_check.py").read_text(encoding="utf-8")
LEGACY = Path("scripts/import_tr3_legacy_tables.py").read_text(encoding="utf-8")


def test_status_script_is_read_only_and_uses_finalize_compare():
    assert "from scripts.tr3_import_finalize_check import compare" in SCRIPT
    assert "compare(source, target)" in SCRIPT
    assert "INSERT" not in SCRIPT.upper()
    assert "UPDATE" not in SCRIPT.upper()


def test_status_script_has_default_recovered_source_and_persistent_target_resolution():
    assert 'Path.home() / "tr4" / "app.db"' in SCRIPT
    assert "resolve_sqlite_path" in SCRIPT
    assert "/data/app.db" in LEGACY or "DATABASE_URL" in LEGACY


def test_finalize_check_reports_missing_or_lower_tables():
    assert "missing_or_lower" in FINALIZE
    assert "Rode import_tr3_legacy_tables.py com --apply" in FINALIZE
