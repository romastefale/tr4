import sqlite3
from pathlib import Path

import pytest

from scripts.import_tr3_legacy_phase138 import (
    LEGACY_TABLES,
    MARKER_KEY,
    MARKER_TABLE,
    run_phase138_import,
)
from scripts.diagnose_phase138_tr3_persistence import diagnose


def _create_legacy_db(path: Path, seed: int = 1) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE lastfm_profiles (user_id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("CREATE TABLE spotify_tokens (user_id INTEGER PRIMARY KEY, access_token TEXT, refresh_token TEXT)")
        conn.execute("CREATE TABLE track_plays (id INTEGER PRIMARY KEY, user_id INTEGER, track_name TEXT, artist_name TEXT)")
        conn.execute("CREATE TABLE track_likes (id INTEGER PRIMARY KEY, user_id INTEGER, track_name TEXT, artist_name TEXT, liked INTEGER)")
        conn.execute("CREATE TABLE track_reactions (id INTEGER PRIMARY KEY, user_id INTEGER, reaction TEXT)")
        conn.execute("CREATE TABLE reaction_audit (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT)")
        conn.execute("CREATE TABLE canvas_files (id INTEGER PRIMARY KEY, track_name TEXT, file_path TEXT)")
        conn.execute("CREATE TABLE card_messages (id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER)")
        conn.execute("CREATE TABLE new_member_watch (id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER)")
        for i in range(seed, seed + 2):
            conn.execute("INSERT INTO lastfm_profiles VALUES (?, ?)", (i, f"lastfm_{i}"))
            conn.execute("INSERT INTO spotify_tokens VALUES (?, ?, ?)", (i, f"access_{i}", f"refresh_{i}"))
            conn.execute("INSERT INTO track_plays VALUES (?, ?, ?, ?)", (i, i, f"track_{i}", f"artist_{i}"))
            conn.execute("INSERT INTO track_likes VALUES (?, ?, ?, ?, ?)", (i, i, f"track_{i}", f"artist_{i}", 1))
            conn.execute("INSERT INTO track_reactions VALUES (?, ?, ?)", (i, i, "🔥"))
            conn.execute("INSERT INTO reaction_audit VALUES (?, ?, ?)", (i, i, "created"))
            conn.execute("INSERT INTO canvas_files VALUES (?, ?, ?)", (i, f"track_{i}", f"/tmp/{i}.mp4"))
            conn.execute("INSERT INTO card_messages VALUES (?, ?, ?)", (i, -100, i))
            conn.execute("INSERT INTO new_member_watch VALUES (?, ?, ?)", (i, -100, i))


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def test_phase138_requires_existing_source(tmp_path):
    target = tmp_path / "target.db"
    with pytest.raises(FileNotFoundError):
        run_phase138_import(tmp_path / "missing.db", target, apply=True)


def test_phase138_refuses_source_equal_target(tmp_path):
    source = tmp_path / "same.db"
    _create_legacy_db(source)
    with pytest.raises(RuntimeError, match="source e target"):
        run_phase138_import(source, source, apply=True)


def test_phase138_imports_expected_tables_creates_backup_and_marker(tmp_path):
    source = tmp_path / "tr3_antigo.db"
    target = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"
    _create_legacy_db(source)
    sqlite3.connect(target).close()

    report = run_phase138_import(source, target, apply=True, backup_dir=backup_dir)

    assert report.ok is True
    assert report.marker_created is True
    assert Path(report.source_backup).exists()
    assert Path(report.target_backup).exists()
    assert set(p.name.split(".source_before_import.")[0] for p in backup_dir.glob("*.source_before_import.*.bak")) == {"tr3_antigo.db"}
    assert set(p.name.split(".target_before_import.")[0] for p in backup_dir.glob("*.target_before_import.*.bak")) == {"app.db"}
    for table in LEGACY_TABLES:
        assert _count(target, table) == 2
    with sqlite3.connect(target) as conn:
        row = conn.execute(f"SELECT marker_key FROM {MARKER_TABLE} WHERE marker_key=?", (MARKER_KEY,)).fetchone()
        assert row == (MARKER_KEY,)


def test_phase138_second_run_is_idempotent_and_does_not_duplicate(tmp_path):
    source = tmp_path / "tr3_antigo.db"
    target = tmp_path / "app.db"
    _create_legacy_db(source)
    sqlite3.connect(target).close()

    first = run_phase138_import(source, target, apply=True)
    second = run_phase138_import(source, target, apply=True)

    assert first.marker_created is True
    assert second.marker_existing is True
    assert second.marker_noop is True
    assert second.marker_created is False
    for table in LEGACY_TABLES:
        assert _count(target, table) == 2


def test_phase138_aborts_when_marker_fingerprint_differs(tmp_path):
    source = tmp_path / "tr3_antigo.db"
    other = tmp_path / "tr3_outro.db"
    target = tmp_path / "app.db"
    _create_legacy_db(source, seed=1)
    _create_legacy_db(other, seed=100)
    sqlite3.connect(target).close()

    run_phase138_import(source, target, apply=True)

    with pytest.raises(RuntimeError, match="fingerprint diferente"):
        run_phase138_import(other, target, apply=True)


def test_phase138_diagnose_reports_marker_counts_and_volume_status(tmp_path):
    source = tmp_path / "tr3_antigo.db"
    target = tmp_path / "app.db"
    _create_legacy_db(source)
    sqlite3.connect(target).close()
    run_phase138_import(source, target, apply=True)

    report = diagnose(target, source)

    assert report["target_exists"] is True
    assert report["source_exists"] is True
    assert report["source_sha256"]
    assert report["marker"]["marker_key"] == MARKER_KEY
    for table in LEGACY_TABLES:
        assert report["tables"][table] == 2
