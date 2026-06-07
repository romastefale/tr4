from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path('scripts/import_tr3_lastfm_profiles.py')


def _make_source(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            '''
            CREATE TABLE lastfm_profiles (
                user_id INTEGER NOT NULL,
                username VARCHAR NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (user_id)
            )
            '''
        )
        conn.executemany(
            'INSERT INTO lastfm_profiles (user_id, username, created_at, updated_at) VALUES (?, ?, ?, ?)',
            [
                (1, 'romastefale', '2026-05-25 15:45:52', '2026-05-25 15:45:52'),
                (2, '@dracco0', '2026-05-14 22:54:09', '2026-05-14 22:54:09'),
                (3, 'bad username with space', '2026-05-14 22:54:09', '2026-05-14 22:54:09'),
            ],
        )


def _run(*args: str) -> dict:
    result = subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_phase86_dry_run_does_not_create_target_rows(tmp_path: Path):
    source = tmp_path / 'tr3.db'
    target = tmp_path / 'tr4.db'
    _make_source(source)
    report = _run('--source', str(source), '--target', str(target))
    assert report['dry_run'] is True
    assert report['source_rows'] == 3
    assert report['inserted'] == 2
    assert report['skipped_invalid'] == 1
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT COUNT(*) FROM lastfm_profiles').fetchone()[0] == 0


def test_phase86_apply_imports_idempotently_and_records_report(tmp_path: Path):
    source = tmp_path / 'tr3.db'
    target = tmp_path / 'tr4.db'
    _make_source(source)
    report = _run('--source', str(source), '--target', str(target), '--apply')
    assert report['dry_run'] is False
    assert report['inserted'] == 2
    assert report['backup_path']
    with sqlite3.connect(target) as conn:
        rows = conn.execute('SELECT user_id, username FROM lastfm_profiles ORDER BY user_id').fetchall()
        assert rows == [(1, 'romastefale'), (2, 'dracco0')]
        assert conn.execute('SELECT COUNT(*) FROM tr3_import_runs').fetchone()[0] == 1
    second = _run('--source', str(source), '--target', str(target), '--apply')
    assert second['inserted'] == 0
    assert second['skipped_existing'] == 2


def test_phase86_refuses_same_source_and_target(tmp_path: Path):
    source = tmp_path / 'same.db'
    _make_source(source)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--source', str(source), '--target', str(source), '--apply'],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert 'source e target são o mesmo arquivo' in result.stderr
