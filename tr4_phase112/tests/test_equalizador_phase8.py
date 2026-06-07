from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_document_exists_and_mentions_rollback():
    doc = ROOT / "docs" / "EQUALIZADOR_RELEASE_OPERACIONAL.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "TR4_EQUALIZADOR_ENABLED=false" in text
    assert "Rollback" in text
    assert "/healthz" in text
    assert "/readyz" in text


def test_release_check_script_imports_without_project_dependencies():
    script = ROOT / "scripts" / "equalizador_release_check.py"
    spec = importlib.util.spec_from_file_location("equalizador_release_check", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROOT == ROOT


def test_release_check_script_runs_without_strict_env():
    script = ROOT / "scripts" / "equalizador_release_check.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_railway_healthcheck_path_is_healthz():
    railway = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert 'healthcheckPath = "/healthz"' in railway
    assert 'startCommand = "python -m app.bootstrap"' in railway
