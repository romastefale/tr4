#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== FASE 11 PRE-DEPLOY: ambiente =="
python --version

python - <<'PY'
import importlib
import sys
required = [
    ("sqlalchemy", "SQLAlchemy"),
    ("aiogram", "aiogram"),
    ("fastapi", "FastAPI"),
    ("httpx", "httpx"),
    ("PIL", "Pillow"),
    ("cryptography", "cryptography"),
]
missing = []
for module, label in required:
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", "versao_nao_exposta")
        print(f"OK {label}: {version}")
    except Exception as exc:
        print(f"ERRO {label}: {type(exc).__name__}: {exc}")
        missing.append(label)
if missing:
    print("DEPENDENCIAS_AUSENTES=" + ",".join(missing))
    sys.exit(2)
PY

echo "== pip check =="
python -m pip check

echo "== imports principais =="
python - <<'PY'
import app.bootstrap  # noqa: F401
import app.main  # noqa: F401
from app.config import settings
print("DATABASE_URL", settings.DATABASE_URL)
print("DATA_DIR", settings.DATA_DIR)
print("TR4_EQUALIZADOR_ENABLED", settings.TR4_EQUALIZADOR_ENABLED)
print("RADIO_SCHEDULER_ENABLED", settings.RADIO_SCHEDULER_ENABLED)
print("MAESTROS", len(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET))
print("OPERADORES", len(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET))
print("PALCOS", len(settings.TR4_EQUALIZADOR_PALCO_IDS_SET))
print("CONFIG_ERRORS", list(settings.equalizador_config_errors()))
PY

echo "== validações locais =="
python -m py_compile \
  app/bootstrap.py \
  app/main.py \
  app/config/settings.py \
  app/db/database.py \
  app/equalizador/router.py \
  app/bot/show_owner.py \
  app/bot/music_broadcast.py \
  app/bot/music_broadcast_core.py \
  app/bot/owner_daily_summary.py \
  scripts/validate_equalizador_embedded_html.py

python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py
python scripts/equalizador_release_check.py

TMPDIR_PREDEPLOY="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_PREDEPLOY"' EXIT
TMPDB="$TMPDIR_PREDEPLOY/app.db"

echo "== banco temporário/migrações/tabelas novas =="
TR3_DATABASE_URL="sqlite:///$TMPDB" \
TR3_TELEGRAM_BOT_TOKEN="123456:predeploy_dummy_token" \
TR3_BASE_URL="https://example.invalid" \
TR4_EQUALIZADOR_ENABLED="1" \
TR4_EQUALIZADOR_MAESTRO_IDS="1" \
TR4_EQUALIZADOR_OPERADOR_IDS="2" \
TR4_EQUALIZADOR_PALCO_IDS="-1001234567890" \
python - <<'PY'
from sqlalchemy import text
from app.db.database import engine, init_db, run_migrations
from app.equalizador.persistencia import ensure_persistence_state
from app.equalizador.governante_scope import ensure_governante_scope_tables
from app.bot.music_broadcast_core import ensure_music_broadcast_tables
from app.equalizador.ddx import ensure_ddx_tables
from app.equalizador.mesa import ensure_phase5_tables
from app.equalizador.entradas import ensure_phase43_tables
from app.equalizador.novos_membros import ensure_novos_membros_tables

init_db()
run_migrations(engine)
ensure_persistence_state(engine)
ensure_phase5_tables(engine)
ensure_phase43_tables(engine)
ensure_novos_membros_tables(engine)
ensure_governante_scope_tables(engine)
ensure_music_broadcast_tables(engine)
ensure_ddx_tables(engine)
expected = {
    "eq_governante_assignments",
    "eq_governante_daily_limits",
    "eq_governante_daily_usage",
    "eq_governante_limit_exceptions",
    "eq_governante_daily_summary_dispatch",
    "eq_music_broadcast_blocks",
    "eq_music_broadcast_runs",
    "eq_music_broadcast_results",
    "eq_music_broadcast_schedules",
    "eq_music_broadcast_catalog",
    "eq_ddx_filters",
    "eq_ddx_events",
    "eq_ddx_soft_pending",
}
with engine.begin() as conn:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    present = {str(row[0]) for row in rows}
missing = sorted(expected - present)
if missing:
    raise SystemExit("TABELAS_AUSENTES=" + ",".join(missing))
print("TABELAS_OK", len(present))
PY

echo "== suite fase11 =="
./scripts/phase11_final_check.sh

echo "FASE 11 PRE-DEPLOY: OK"
