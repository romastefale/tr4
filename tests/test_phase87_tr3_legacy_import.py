from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path('scripts/import_tr3_legacy_tables.py')


def _make_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE track_plays (id INTEGER PRIMARY KEY, user_id INTEGER, track_id TEXT, played_at TEXT)')
        conn.execute('CREATE TABLE track_likes (id INTEGER PRIMARY KEY, user_id INTEGER, track_id TEXT)')
        conn.executemany('INSERT INTO track_plays (id, user_id, track_id, played_at) VALUES (?, ?, ?, ?)', [(1, 10, 'a', '2026-01-01'), (2, 11, 'b', '2026-01-02')])
        conn.execute('INSERT INTO track_likes (id, user_id, track_id) VALUES (1, 10, "a")')


def _run(*args: str) -> dict:
    result = subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_phase87_dry_run_reports_insertions_without_mutating(tmp_path: Path):
    source = tmp_path / 'tr3.db'
    target = tmp_path / 'tr4.db'
    _make_db(source)
    with sqlite3.connect(target) as conn:
        conn.execute('CREATE TABLE track_plays (id INTEGER PRIMARY KEY, user_id INTEGER, track_id TEXT, played_at TEXT)')
    report = _run('--source', str(source), '--target', str(target), '--tables', 'track_plays')
    table = report['tables'][0]
    assert report['dry_run'] is True
    assert table['table'] == 'track_plays'
    assert table['inserted'] == 2
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT COUNT(*) FROM track_plays').fetchone()[0] == 0


def test_phase87_apply_is_idempotent_and_records_report(tmp_path: Path):
    source = tmp_path / 'tr3.db'
    target = tmp_path / 'tr4.db'
    _make_db(source)
    with sqlite3.connect(target) as conn:
        conn.execute('CREATE TABLE track_plays (id INTEGER PRIMARY KEY, user_id INTEGER, track_id TEXT, played_at TEXT)')
    first = _run('--source', str(source), '--target', str(target), '--tables', 'track_plays', '--apply')
    assert first['backup_path']
    assert first['tables'][0]['inserted'] == 2
    second = _run('--source', str(source), '--target', str(target), '--tables', 'track_plays', '--apply')
    assert second['tables'][0]['inserted'] == 0
    assert second['tables'][0]['skipped_existing'] == 2
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT COUNT(*) FROM track_plays').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM tr3_legacy_import_runs').fetchone()[0] == 2


def test_phase87_skips_target_tables_that_do_not_exist(tmp_path: Path):
    source = tmp_path / 'tr3.db'
    target = tmp_path / 'tr4.db'
    _make_db(source)
    sqlite3.connect(target).close()
    report = _run('--source', str(source), '--target', str(target), '--tables', 'track_likes')
    assert report['tables'][0]['skipped_missing_target'] is True
