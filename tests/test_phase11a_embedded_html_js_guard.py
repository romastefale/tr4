from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_equalizador_embedded_html.py"
ROUTER = ROOT / "app" / "equalizador" / "router.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_equalizador_embedded_html", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedded_equalizador_html_js_ids_are_consistent() -> None:
    validator = _load_validator()
    assert validator.main(["--router", str(ROUTER), "--skip-node"]) == 0
