#!/usr/bin/env bash
set -euo pipefail

python -m py_compile \
  app/bot/music_broadcast_core.py \
  app/bot/music_broadcast.py \
  app/bot/owner_daily_summary.py \
  app/bot/show_owner.py \
  app/fsm_tigrao/context.py \
  app/fsm_tigrao/keyboards.py \
  app/fsm_tigrao/router.py \
  app/main.py \
  app/equalizador/router.py \
  app/equalizador/governante_scope.py \
  app/equalizador/governante_webapp.py \
  scripts/validate_equalizador_embedded_html.py

python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py

python -m pytest -q \
  tests/test_phase11a_embedded_html_js_guard.py \
  tests/test_phase11b_panel_hardening.py \
  tests/test_phase11_etapa2_show_owner.py \
  tests/test_phase11_etapa3_webapp_governante.py \
  tests/test_phase11_etapa4_ddx_owner_only.py \
  tests/test_phase11_etapa5_music_broadcast.py \
  tests/test_phase11_etapa6_governante_scope.py \
  tests/test_phase11_etapa7_governante_limits.py \
  tests/test_phase11_etapa8_saneamento_acumulado.py \
  tests/test_phase11_etapa9_personalizado_scope_ui.py \
  tests/test_phase11_etapa10_show_owner_painel.py \
  tests/test_phase11_etapa11_broadcast_auto_summary.py \
  tests/test_phase11_etapa12_broadcast_quality.py \
  tests/test_phase11_etapa13_technical_closure.py \
  tests/test_phase11_etapa15_auditoria_corretiva.py \
  tests/test_phase11_etapa16_auditoria_final.py \
  tests/test_phase11_etapa17_alinhamento_final.py \
  tests/test_phase11_etapa18_bot_api_compat.py \
  tests/test_phase11_etapa19_security_hardening.py \
  tests/test_phase11_etapa21_context_auto.py \
  tests/test_phase11_etapa22_show_fsm_redesign.py \
  tests/test_phase11_etapa23_moderator_panel_clean.py \
  tests/test_fsm_tr3_to_tr4_architecture.py \
  tests/test_fsm_private_x9_architecture.py \
  tests/test_fsm_private_x9_hardening.py \
  tests/test_music_only_build.py

python scripts/equalizador_release_check.py

echo "FASE 11 FINAL: VALIDACAO LOCAL OK"
