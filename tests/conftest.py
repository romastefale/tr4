"""Configuração compartilhada da suíte de testes.

Em Replit `/data` é read-only — qualquer import de `app.config.settings`
chama `DATA_DIR.mkdir()` no nível de módulo e quebraria a coleta dos testes.
Forçamos `DATA_DIR=/tmp/data` ANTES de qualquer import de `app.*`, que é o
único requisito de ambiente da suíte (ver task-32).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", "/tmp/data")
Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TR3_ROOT_USER_ID", "1")
os.environ.setdefault("TR3_SECOND_MODERATOR_ID", "2")
os.environ.setdefault("TR3_THIRD_MODERATOR_ID", "3")

# Use an isolated SQLite file for each pytest process. A fixed /tmp/data/test.db
# leaks rows between smoke/pytest runs and makes duplicate-detection tests flaky.
_test_db = Path(tempfile.gettempdir()) / f"tr3-test-{os.getpid()}.db"
os.environ["TR3_DATABASE_URL"] = f"sqlite:///{_test_db}"
