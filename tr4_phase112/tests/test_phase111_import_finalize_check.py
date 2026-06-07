import sqlite3
from pathlib import Path

from scripts.tr3_import_finalize_check import compare


def _db(path: Path, n: int):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE lastfm_profiles (user_id INTEGER PRIMARY KEY, username TEXT)")
        for i in range(n):
            conn.execute("INSERT INTO lastfm_profiles (user_id, username) VALUES (?, ?)", (i + 1, f"u{i}"))


def test_phase111_compare_detects_missing_rows(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _db(source, 2)
    _db(target, 1)
    report = compare(source, target)
    assert report["ok"] is False
    assert "lastfm_profiles" in report["missing_or_lower"]


def test_phase111_compare_same_file_is_safe(tmp_path):
    source = tmp_path / "same.db"
    _db(source, 1)
    report = compare(source, source)
    assert report["ok"] is True
    assert "não importe sobre ele mesmo" in report["next_step"]
