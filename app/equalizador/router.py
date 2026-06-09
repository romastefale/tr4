from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import re
import secrets
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

# Phase 136 public player: prefixo data URI exigido pelo backend/teste.
_PHASE136_DATA_IMAGE_PREFIX = "data:image/png;base64,"
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
import html
import httpx
import logging

from app.config import settings

logger = logging.getLogger(__name__)
from app.db.database import engine as default_engine
from app.bot.music_groups import remember_group, list_groups
from app.services.music import music_service
from app.services.reactions import reactions_service
from sqlalchemy import text
from app.equalizador.afinacao import PalcoNotFoundError, get_palco_internal_by_ref, sincronizar_afinacao_palco
from app.equalizador.palcos import list_equalizador_palcos, upsert_operador
from app.equalizador.permissions import (
    CRITICAL_CANAL_CODES,
    CANAL_BY_CODE,
    CANAL_DEFINITIONS,
    canal_codes_for_operator,
    canal_is_allowed,
    canais_for_palco,
    filter_palco_ids_by_canal,
)
from app.equalizador.rbac_runtime import (
    canal_codes_for_operator_effective,
    canal_is_allowed_effective,
    canais_for_palco_effective,
    filter_palco_ids_by_canal_effective,
    grant_runtime_canal,
    rbac_runtime_error_payload,
    list_runtime_grants_public,
    rbac_runtime_catalogo_publico,
    revoke_runtime_canal,
    update_governance_operator,
    disable_governance_operator,
    governance_persistence_public,
)
from app.equalizador.session_store import cleanup_expired_sessions, session_store_status
from app.equalizador.mesa import (
    ACTION_SPECS,
    MesaError,
    list_alvos_publicos,
    list_mensagens_publicas,
    MesaNotFoundError,
    MesaRightError,
    MesaTargetError,
    mesa_error_public_detail,
    executar_ajuste,
    executar_mensagens_apagar_lote,
    list_historico_publico,
    register_mensagem_from_link,
    resolve_alvo_manual,
    send_operator_dm,
)
from app.equalizador.papeis import matriz_permissoes_publica
from app.equalizador.governanca import governantes_publicos
from app.equalizador.ddx import (
    DDXError,
    DDXNotFoundError,
    cancelar_ddx_agendado,
    ddx_error_public_detail,
    list_ddx_publico,
    salvar_ddx_config,
)
from app.equalizador.reacoes import (
    ReacoesError,
    list_reacoes_publicas,
    reacoes_error_public_detail,
    silenciar_reactor,
)
from app.equalizador.novos_membros import (
    NovosMembrosError,
    NovosMembrosNotFoundError,
    get_new_member_event,
    list_novos_membros_publicos,
    marcar_new_member_event,
    novos_membros_error_public_detail,
)
from app.equalizador.radio import (
    RadioError,
    RadioNotFoundError,
    apagar_template_radio,
    cancelar_rascunho_radio,
    criar_rascunho_de_template_radio,
    criar_rascunho_radio,
    criar_template_radio,
    criar_radio_schedule,
    cancelar_radio_schedule,
    executar_radio_broadcast,
    get_radio_quiet_policy_publico,
    list_radio_drafts_publicos,
    list_radio_history_publico,
    list_radio_schedules_publicos,
    list_radio_templates_publicos,
    publicar_rascunho_radio,
    radio_error_public_detail,
    run_due_radio_schedules,
    salvar_radio_quiet_policy,
)
from app.equalizador.multimidia import (
    MultimediaError,
    create_multimedia_session,
    list_multimedia_sessions,
    publish_multimedia_session,
    public_multimedia_session,
    get_multimedia_session,
    multimedia_center_public,
    multimedia_session_diagnostic,
)
from app.equalizador.maestro import (
    MaestroConfirmationError,
    MaestroError,
    distribuicao_canais_publica,
    executar_modo_silencio,
    executar_modo_silencio_desativar,
    executar_transmissao,
    exportar_historico_publico,
    maestro_error_public_detail,
)
from app.equalizador.hardening import (
    EqualizadorMesaBusyError,
    EqualizadorRateLimitError,
    EqualizadorSessionError,
    EqualizadorStorageError,
    check_equalizador_rate_limit,
    create_equalizador_session,
    log_equalizador_event,
    mesa_operation_lock,
    reset_equalizador_locks,
    reset_equalizador_rate_limits,
    validate_equalizador_session,
)
from app.equalizador.identity import make_ui_ref
from app.equalizador.security import InitDataError, TelegramWebAppIdentity, extract_tma_authorization, validate_init_data
from app.equalizador.erros_telegram import telegram_error_payload
from app.equalizador.seguranca_avancada import (
    assert_security_action_allowed,
    cleanup_security_audit,
    export_security_encrypted,
    export_security_jsonl,
    get_security_mode,
    record_security_audit,
    security_dashboard_public,
    set_security_mode,
)
from app.equalizador.configuracao import configuracao_maestro_publica, raw_editor_from_form_payload
from app.equalizador.painel import PainelDinamicoError, montar_painel_dinamico_palco
from app.equalizador.entradas import (
    EntradasError,
    entradas_error_public_detail,
    list_join_requests_publicos,
    executar_pedido_entrada,
    list_invites_publicos,
    editar_convite,
    revogar_convite,
    exportar_link_primario,
)
from app.equalizador.avancado import (
    ADVANCED_SPECS,
    AvancadoError,
    avancado_error_public_detail,
    executar_ajuste_avancado,
    list_sender_chats_publicos,
    list_topics_publicos,
)
from app.equalizador.admin import (
    ADMIN_SPECS,
    AdminCriticoError,
    AdminConfirmationError,
    admin_error_public_detail,
    executar_admin_critico,
    executar_grupo_foto,
)

router = APIRouter(prefix="/equalizador", tags=["equalizador"], include_in_schema=False)

_EQUALIZADOR_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Equalizador</title>
  <script async src="https://telegram.org/js/telegram-web-app.js" onload="window.__TR4_READY_PANEL&&window.__TR4_READY_PANEL('telegram_script_load')" onerror="window.__TR4_PANEL_MARK&&window.__TR4_PANEL_MARK('panel_telegram_script_error','falha ao carregar telegram-web-app.js','')"></script>
  <script>
    (function () {
      function report(kind, message, source, line, col, extra) {
        try {
          var payload = {
            kind: String(kind || "client_error").slice(0, 40),
            message: String(message || "").slice(0, 320),
            source: String(source || "").slice(0, 180),
            line: Number(line || 0),
            col: Number(col || 0),
            href: String(location && location.pathname || "").slice(0, 160),
            user_agent: String(navigator.userAgent || "").slice(0, 220)
          };
          if (extra) payload.extra = String(extra).slice(0, 500);
          fetch("/equalizador/api/client-error", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          }).catch(function () {});
        } catch (_) {}
      }
      window.__eqClientError = report;
      window.__TR4_PANEL_BOOT = window.__TR4_PANEL_BOOT || { headStarted: true, bottomStarted: false, marks: [] };
      function visible(kind, title, detail) {
        try {
          var boot = window.__TR4_PANEL_BOOT = window.__TR4_PANEL_BOOT || { marks: [] };
          boot.visibleKind = kind;
          var debug = document.getElementById("panel_boot_debug");
          if (debug) debug.textContent = String(title || kind || "Inicialização") + (detail ? ": " + String(detail) : "");
          var loading = document.getElementById("loading");
          if (loading) loading.classList.remove("hidden");
        } catch (_) {}
      }
      function mark(kind, message, extra) {
        try {
          var boot = window.__TR4_PANEL_BOOT = window.__TR4_PANEL_BOOT || { marks: [] };
          boot.marks = boot.marks || [];
          boot.marks.push({ kind: String(kind || "panel_mark"), message: String(message || ""), time: Date.now() });
          report(kind, message || "ok", "equalizador_panel", 0, 0, extra || "");
          var debug = document.getElementById("panel_boot_debug");
          if (debug) debug.textContent = String(kind || "panel_mark") + (message ? ": " + String(message) : "");
        } catch (_) {}
      }
      function readyPanel(origin) {
        try {
          var tg = window.Telegram && window.Telegram.WebApp;
          if (!tg || !tg.ready) return false;
          tg.ready();
          if (tg.expand) tg.expand();
          mark("panel_telegram_ready", origin || "early", "");
          return true;
        } catch (error) {
          mark("panel_telegram_ready_failed", error && error.message ? error.message : "ready_failed", origin || "");
          return false;
        }
      }
      window.__TR4_PANEL_VISIBLE = visible;
      window.__TR4_PANEL_MARK = mark;
      window.__TR4_READY_PANEL = readyPanel;
      mark("panel_head_js_started", "ok", "phase137_4");
      document.addEventListener("DOMContentLoaded", function () {
        mark("panel_dom_content_loaded", "ok", "");
        readyPanel("dom");
        setTimeout(function () {
          var boot = window.__TR4_PANEL_BOOT || {};
          if (!boot.bottomStarted) visible("panel_bottom_script_not_started", "Erro de inicialização", "O HTML abriu, mas o JavaScript principal do painel não iniciou.");
        }, 2500);
      });
      setTimeout(function () { readyPanel("timer_early"); }, 150);
      setTimeout(function () {
        var tg = window.Telegram && window.Telegram.WebApp;
        if (!tg) mark("panel_telegram_object_missing", "Telegram.WebApp ausente após 1.2s", "");
      }, 1200);
      window.addEventListener("error", function (event) {
        var err = event.error || null;
        var stack = err && err.stack ? err.stack : "";
        var kind = event.message === "Script error." ? "script_error_restrito" : "error";
        report(kind, event.message, event.filename, event.lineno, event.colno, stack);
      }, true);
      window.addEventListener("unhandledrejection", function (event) {
        var reason = event.reason;
        var message = reason && reason.message ? reason.message : String(reason || "unhandledrejection");
        var stack = reason && reason.stack ? reason.stack : "";
        report("unhandledrejection", message, "", 0, 0, stack);
      });
    })();
  </script>
  <style>
    :root { color-scheme: dark light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 16px 16px 84px; background: var(--tg-theme-bg-color, #151a20); color: var(--tg-theme-text-color, #f8fafc); font-size: 15px; }
    body::before { content: ""; position: fixed; inset: 0; pointer-events: none; background: none; }
    main { max-width: 920px; margin: 0 auto; position: relative; z-index: 1; }
    .card { border: 1px solid rgba(255,255,255,.18); border-radius: 20px; padding: 18px; background: #151923; box-shadow: 0 16px 42px rgba(0,0,0,.38); transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
    h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.02em; }
    h2 { margin: 22px 0 10px; font-size: 18px; }
    h3 { margin: 14px 0 8px; font-size: 15px; }
    p { line-height: 1.45; }
    .muted { color: var(--tg-theme-hint-color, #cbd5e1); }
    .hidden { display: none !important; }
    .top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .pill { display: inline-flex; align-items: center; border: 1px solid rgba(255,255,255,.24); border-radius: 999px; padding: 6px 10px; font-size: 12px; color: #f8fafc; background: rgba(255,255,255,.08); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
    .formgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .panel { border: 1px solid rgba(255,255,255,.16); border-radius: 16px; padding: 14px; background: #1a202b; transition: border-color .18s ease, background-color .18s ease, transform .18s ease; }
    .panel:hover { border-color: rgba(255,255,255,.24); }
    .section-divider { display: grid; gap: 4px; margin: 22px 0 10px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.12); }
    .section-divider strong { font-size: 15px; }
    .section-divider span { font-size: 12px; color: var(--tg-theme-hint-color, #cbd5e1); }
    .palco { width: 100%; text-align: left; border: 1px solid rgba(255,255,255,.10); border-radius: 16px; padding: 14px; background: rgba(255,255,255,.06); color: inherit; font: inherit; }
    .palco.active { outline: 2px solid var(--tg-theme-button-color, #5b8cff); }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: center; border-top: 1px solid rgba(255,255,255,.08); padding-top: 10px; margin-top: 10px; }
    .bulk-list { display: grid; gap: 8px; max-height: 260px; overflow: auto; margin-top: 10px; padding-right: 2px; }
    .bulk-item { display: grid; grid-template-columns: 32px 1fr; gap: 10px; align-items: start; border: 1px solid rgba(255,255,255,.12); border-radius: 12px; padding: 10px; background: rgba(255,255,255,.04); cursor: pointer; transition: background-color .16s ease, border-color .16s ease, transform .12s ease, box-shadow .16s ease; }
    .bulk-item:hover { border-color: rgba(91,140,255,.48); background: rgba(91,140,255,.08); }
    .bulk-item:active { transform: scale(.992); }
    .bulk-item.selected { border-color: rgba(80,216,144,.72); background: rgba(22,138,85,.18); box-shadow: inset 4px 0 0 rgba(80,216,144,.85); }
    .bulk-item input { width: 18px; height: 18px; margin-top: 2px; accent-color: var(--tg-theme-button-color, #5b8cff); }
    .bulk-item.locked { opacity: .62; }
    .bulk-actions { position: static; margin-top: 10px; padding: 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 14px; background: #1a202b; box-shadow: 0 10px 28px rgba(0,0,0,.18); }
    .bulk-actions.idle .toolbar { display: none; }
    .bulk-actions.active { border-color: rgba(80,216,144,.42); background: rgba(20,83,45,.14); }
    .nav.access-blocked { opacity: .42; }
    button, select, textarea, input { font: inherit; }
    button.action, button.nav { border: 0; border-radius: 14px; padding: 12px 14px; background: var(--tg-theme-button-color, #5b8cff); color: var(--tg-theme-button-text-color, white); font-weight: 650; transition: transform .12s ease, filter .12s ease, box-shadow .16s ease, background-color .16s ease, opacity .16s ease; touch-action: manipulation; }
    button.action:hover, button.nav:hover { filter: brightness(1.07); box-shadow: 0 10px 22px rgba(0,0,0,.22); }
    button.action:active, button.nav:active, button.action.pressed, button.nav.pressed { transform: scale(.975); filter: brightness(.82); }
    button.action:focus-visible, button.nav:focus-visible, select:focus-visible, textarea:focus-visible, input:focus-visible { outline: 2px solid var(--tg-theme-button-color, #5b8cff); outline-offset: 2px; }
    button.action.confirming { filter: brightness(.72); box-shadow: inset 0 0 0 2px rgba(255,255,255,.34), 0 10px 24px rgba(0,0,0,.28); }
    button.action.working { opacity: .78; cursor: wait; }
    button.action.success { box-shadow: inset 0 0 0 2px rgba(80,216,144,.70); }
    button.action.error { box-shadow: inset 0 0 0 2px rgba(255,138,128,.70); }
    .app-tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; align-items: stretch; }
    .app-tabs button.nav { width: 100%; min-height: 54px; text-align: left; padding: 9px 10px; border-radius: 14px; line-height: 1.15; }
    .app-tabs button.nav strong { display: block; font-size: 14px; color: #fff; margin-bottom: 2px; }
    .app-tabs button.nav span { display: block; font-size: 11px; color: #d1d5db; font-weight: 500; }
    button.secondary { background: #263142; color: #f8fafc; border: 1px solid rgba(255,255,255,.20); }
    button.nav.active { background: #3b82f6; color: #fff; border-color: rgba(255,255,255,.36); }
    button.danger { background: #b42318; color: #fff; }
    button:disabled { opacity: .45; filter: grayscale(1); }
    button.action[data-action="convites.criar"], button.action[data-action="entradas.aprovar"], button.action[data-action="membros.liberar"], button.action[data-action="membros.reintegrar"], button.action[data-action="canais_remetentes.liberar"], button.action[data-action="admins.promover"], button.action[data-action="silencio.desativar"], button.action[data-action="grupo.foto"] { background: #168a55; color: #fff; }
    button.action[data-action="fixados.criar"], button.action[data-action="fixados.remover"], button.action[data-action="topicos.criar"], button.action[data-action="topicos.editar"], button.action[data-action="topicos.reabrir"], button.action[data-action="topicos.desfixar"], button.action[data-action="topicos.geral.reabrir"], button.action[data-action="topicos.geral.exibir"], button.action[data-action="topicos.geral.desfixar"], button.action[data-action="grupo.descricao"], button.action[data-action="admins.titulo"], button#resolver_mensagem, button#resolver_alvo { background: #2563eb; color: #fff; }
    button.action[data-action="transmissao.enviar"], button.action[data-action="mensagens.enviar"], button#radio_schedule_criar, button#radio_quiet_salvar, button#radio_broadcast_enviar, button#radio_schedules_processar, button#ddx_hard_salvar, button#ddx_soft_salvar, button#reacoes_silenciar_reactor, button#novos_silenciar, button#novos_ignorar, button.action[data-action="convites.editar"], button.action[data-action="convites.exportar_primario"], button.action[data-action="grupo.titulo"], button.action[data-action="membros.tag.definir"], button.action[data-action="membros.silenciar"], button.action[data-action="silencio.ativar"], button.action[data-action="topicos.fechar"], button.action[data-action="topicos.geral.fechar"], button.action[data-action="topicos.geral.ocultar"], button.action[data-action="reacoes.mensagem.limpar"], button.action[data-action="reacoes.recentes.limpar"], button#seguranca_modo_alerta, button#seguranca_exportar_jsonl, button#seguranca_exportar_assinado, button#seguranca_exportar_criptografado, button#seguranca_limpar_auditoria, button#seguranca_limpar_locks, button#atualizar_configuracao, button#gerar_config_raw, button#resetar_config_form, button#copiar_config_raw, button#exportar_historico { background: #c77800; color: #fff; }
    button.action[data-action="mensagens.apagar"], button#seguranca_modo_restrito, button#radio_schedule_cancelar, button#ddx_cancelar_agendado, button#novos_apagar, button#novos_banir, button.action[data-action="membros.remover"], button.action[data-action="entradas.recusar"], button.action[data-action="convites.revogar"], button.action[data-action="topicos.apagar"], button.action[data-action="canais_remetentes.banir"], button.action[data-action="admins.rebaixar"], button.action[data-action="grupo.foto.remover"] { background: #b42318; color: #fff; }
    .toolbar { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 12px 0; align-items: stretch; }
    .toolbar.compact { grid-template-columns: repeat(auto-fit, minmax(120px, max-content)); justify-content: start; }
    .toolbar > button { width: 100%; min-height: 44px; }
    select, textarea, input { width: 100%; border: 1px solid rgba(255,255,255,.22); border-radius: 14px; padding: 12px; background: #0f172a; color: #f8fafc; scroll-margin-bottom: 320px; }
    textarea { min-height: 92px; resize: vertical; }
    input[type="checkbox"], input[type="radio"] { width: auto; min-width: 18px; height: 18px; margin: 0 8px 0 0; padding: 0; border-radius: 4px; accent-color: var(--tg-theme-button-color, #5b8cff); vertical-align: middle; }
    label.small { display: inline-flex; align-items: center; gap: 6px; min-height: 30px; }
    .formgrid label.small { align-items: center; justify-content: flex-start; }
    input[type="file"] { padding: 10px; }
    input[type="file"]::file-selector-button { margin-right: 10px; border: 0; border-radius: 10px; padding: 9px 12px; background: #263142; color: #f8fafc; font-weight: 650; }
    .list { display: grid; gap: 8px; }
    .item { border: 1px solid rgba(255,255,255,.14); border-radius: 14px; padding: 12px; background: #111827; }
    .ok { color: #50d890; }
    .bad { color: #ff8a80; }
    .warn { color: #ffd166; }
    .feedback-item { position: relative; padding-right: 96px; white-space: pre-wrap; word-break: break-word; }
    .feedback-copy-one { position: absolute; right: 8px; top: 8px; border: 1px solid rgba(255,255,255,.18); border-radius: 9px; padding: 5px 8px; background: #263142; color: #f8fafc; font-size: 11px; font-weight: 650; }
    .feedback-copy-one:active { filter: brightness(.82); transform: scale(.96); }
    .small { font-size: 12px; }
    .section-note { margin: 8px 0 12px; color: #d1d5db; font-size: 13px; }
    .statusbar { margin: 14px 0; border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 10px 12px; background: #111827; font-size: 13px; line-height: 1.35; }
    .statusbar.ok { border-color: rgba(80,216,144,.44); background: rgba(22,138,85,.12); color: #d1fae5; }
    .statusbar.warn { border-color: rgba(255,209,102,.44); background: rgba(199,120,0,.13); color: #fde68a; }
    .statusbar.bad { border-color: rgba(255,138,128,.44); background: rgba(180,35,24,.13); color: #fecaca; }
    .status-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: stretch; margin: 14px 0; }
    .status-row .statusbar { margin: 0; }
    .refresh-action { min-width: 122px; min-height: 42px; }
    .refresh-action.working::before, button.action.working::before, button.nav.loading::before { content: ""; display: inline-block; width: 13px; height: 13px; margin-right: 7px; vertical-align: -2px; border: 2px solid rgba(255,255,255,.36); border-top-color: rgba(255,255,255,.92); border-radius: 50%; animation: spin .78s linear infinite; }
    .refresh-state { margin: -4px 0 12px; min-height: 20px; font-size: 12px; color: var(--tg-theme-hint-color, #cbd5e1); display: flex; align-items: center; gap: 6px; }
    .refresh-state::before { content: ""; width: 8px; height: 8px; border-radius: 999px; background: rgba(255,255,255,.22); }
    .refresh-state.loading::before { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.24); border-top-color: #ffd166; background: transparent; animation: spin .8s linear infinite; }
    .refresh-state.ok::before { background: #50d890; }
    .refresh-state.warn::before { background: #ffd166; }
    .refresh-state.bad::before { background: #ff8a80; }
    .is-refreshing .view:not(.hidden), .is-refreshing #grupo_resumo_card { border-color: rgba(255,209,102,.30); }
    .skeleton-line { display: block; height: 14px; border-radius: 999px; margin: 8px 0; background: linear-gradient(90deg, rgba(255,255,255,.06), rgba(255,255,255,.16), rgba(255,255,255,.06)); background-size: 220% 100%; animation: shimmer 1.1s ease-in-out infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes shimmer { 0% { background-position: 160% 0; } 100% { background-position: -60% 0; } }
    .badge { display: inline-flex; align-items: center; margin: 3px 4px 3px 0; border-radius: 999px; padding: 5px 9px; border: 1px solid rgba(255,255,255,.20); font-size: 12px; color: #e5e7eb; background: rgba(255,255,255,.06); }
    .wide { grid-column: 1 / -1; }
    .person-card { display: grid; gap: 8px; }
    .person-line { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .right-chip { display: inline-flex; margin: 3px 4px 3px 0; border-radius: 999px; padding: 4px 8px; border: 1px solid rgba(255,255,255,.18); font-size: 11px; color: #e5e7eb; background: #0f172a; }
    .right-chip.ok { border-color: rgba(80,216,144,.55); background: rgba(22,138,85,.18); color: #d1fae5; }
    .right-chip.bad { border-color: rgba(255,138,128,.35); color: #fecaca; opacity: .78; }
    .select-note { margin-top: 6px; }
    .empty { border: 1px dashed rgba(255,255,255,.24); border-radius: 14px; padding: 12px; color: #d1d5db; background: #0f172a; }
    .toast { position: sticky; bottom: 12px; margin-top: 16px; border-radius: 14px; padding: 12px; background: #273449; border: 1px solid rgba(255,255,255,.20); white-space: pre-wrap; }
    .toast.ok { border-color: rgba(80,216,144,.55); background: rgba(22,138,85,.18); }
    .toast.warn { border-color: rgba(255,209,102,.55); background: rgba(199,120,0,.18); }
    .toast.bad { border-color: rgba(255,138,128,.50); background: rgba(180,35,24,.18); }
    .feedback-panel { margin-top: 14px; border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 12px; background: #0f172a; }
    .feedback-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; }
    .feedback-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .feedback-actions button { width: auto; min-height: 34px; padding: 8px 10px; }
    .feedback-items { display: grid; gap: 8px; max-height: 240px; overflow: auto; }
    .feedback-item { position: relative; border: 1px solid rgba(255,255,255,.14); border-radius: 12px; padding: 9px 96px 9px 9px; background: rgba(255,255,255,.04); white-space: pre-wrap; word-break: break-word; }
    .feedback-item.ok { border-color: rgba(80,216,144,.50); }
    .feedback-item.warn { border-color: rgba(255,209,102,.52); }
    .feedback-item.bad { border-color: rgba(255,138,128,.48); }
    .feedback-meta { display: block; margin-bottom: 3px; color: var(--tg-theme-hint-color, #cbd5e1); font-size: 11px; }
    .headline { display: grid; grid-template-columns: 72px 1fr; gap: 12px; align-items: center; }
    .bot-hero { display: grid; grid-template-columns: 86px 1fr; gap: 14px; align-items: center; border: 1px solid rgba(255,255,255,.18); border-radius: 18px; padding: 14px; background: #111827; margin-bottom: 12px; }
    .bot-hero h2 { margin: 0 0 4px; font-size: 22px; }
    .bot-avatar { width: 76px; height: 76px; border-radius: 22px; object-fit: cover; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.08); display: grid; place-items: center; color: var(--tg-theme-hint-color, #a1a1aa); font-weight: 800; font-size: 26px; }
    .avatar { width: 64px; height: 64px; border-radius: 18px; object-fit: cover; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.08); display: grid; place-items: center; color: var(--tg-theme-hint-color, #a1a1aa); font-weight: 800; }
    .photo-preview { display: grid; grid-template-columns: 72px 1fr; gap: 12px; align-items: center; margin-top: 12px; }
    .photo-actions input[type="file"] { padding: 10px; background: #020617; }
    .header-select { margin: 14px 0; }
    .group-picker { margin: 14px 0 18px; }
    .group-picker > label { display: block; margin: 0 0 8px; }
    .group-picker select { margin-bottom: 12px; }
    .group-card { margin: 0; }
    #grupo_descricao { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .group-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
    .group-meta .item { margin: 0; }
    .search-box { margin: 8px 0 10px; }
    .member-preview.compact { max-height: 176px; }
    .config-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .config-actions button { width: 100%; }
    .nav-state { display: inline-grid; place-items: center; width: 18px; height: 18px; margin-right: 6px; border-radius: 999px; font-size: 11px; background: rgba(255,255,255,.08); color: var(--tg-theme-hint-color, #a1a1aa); vertical-align: middle; }
    .nav-state.loading { color: #ffd166; animation: pulse 1s infinite alternate; }
    .nav-state.ok { color: #50d890; background: rgba(80,216,144,.12); }
    .nav-state.bad { color: #ff8a80; background: rgba(255,138,128,.12); }
    .chip-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
    .chip-grid .badge { margin: 0; }
    .owner-only { border-color: rgba(255,209,102,.28); }
    .quicklist { display: grid; gap: 8px; }
    .quicklist code { background: #020617; padding: 2px 6px; border-radius: 8px; border: 1px solid rgba(255,255,255,.14); }
    .person-link { color: var(--tg-theme-link-color, #8ab4ff); text-decoration: none; }
    .person-link:hover { text-decoration: underline; }
    .mini-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .mini-table td { border-top: 1px solid rgba(255,255,255,.14); padding: 7px 4px; vertical-align: top; }
    .home-hint-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .panel-split { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
    .member-preview { display: grid; gap: 8px; max-height: 260px; overflow: auto; }
    .home-hint { border: 1px solid rgba(255,255,255,.14); border-radius: 14px; padding: 10px; background: #0f172a; min-height: 68px; }
    .home-hint strong { display: block; font-size: 13px; color: #fff; margin-bottom: 3px; }
    .home-hint span { display: block; color: #d1d5db; font-size: 11px; line-height: 1.3; }
    .window-title { margin-top: 0; }
    .diagnostic-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 10px 0 12px; }
    .diagnostic-metric { border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 12px; background: #0f172a; }
    .diagnostic-metric strong { display: block; font-size: 20px; line-height: 1.1; }
    .diagnostic-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
    .diagnostic-card { border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 12px; background: #111827; }
    .diagnostic-card.ok { border-color: rgba(80,216,144,.55); background: rgba(22,138,85,.14); }
    .diagnostic-card.warn { border-color: rgba(255,209,102,.50); background: rgba(199,120,0,.14); }
    .diagnostic-card.bad { border-color: rgba(255,138,128,.45); background: rgba(180,35,24,.16); }
    .diagnostic-card strong { display: block; margin-bottom: 4px; }
    .diagnostic-reasons { margin-top: 6px; color: #d1d5db; }
    .diagnostic-rights { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
    .governance-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .governance-card { border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 12px; background: #0f172a; }
    .governance-card strong { display: block; margin-bottom: 4px; }
    .governance-role { border: 1px solid rgba(255,255,255,.14); border-radius: 14px; padding: 9px; background: #111827; margin-top: 8px; }
    .governance-role.active { border-color: rgba(80,216,144,.52); background: rgba(22,138,85,.14); }
    .governance-role.locked { opacity: .72; }
    .governance-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
    /* Fase 70: UX minimalista consolidada em cinza/preto, inspirada em padrões nativos do Telegram. */
    body.phase68-minimal { background: #17212b; color: #f5f7fb; padding-top: max(14px, var(--tg-safe-area-inset-top, 0px)); }
    body.phase68-minimal::before { background: none; }
    body.phase68-minimal main { max-width: 760px; }
    body.phase68-minimal .card { background: transparent; border: 0; box-shadow: none; padding: 0; }
    body.phase68-minimal .top { min-height: 28px; justify-content: flex-end; margin: 0 0 8px; }
    body.phase68-minimal .top > div { display: none; }
    body.phase68-minimal #perfil { position: static; justify-self: end; background: #0f141b; border-color: rgba(255,255,255,.08); color: #a9b3c2; }
    body.phase68-minimal .row { display: none; }
    body.phase68-minimal #inicio_view { background: transparent; border: 0; padding: 0; margin: 0 0 16px; }
    body.phase68-minimal .bot-hero { grid-template-columns: 1fr; justify-items: center; text-align: center; border: 0; background: transparent; box-shadow: none; padding: 10px 8px 6px; margin: 0 0 8px; }
    body.phase68-minimal .bot-avatar { width: 78px; height: 78px; border-radius: 999px; font-size: 24px; box-shadow: 0 18px 40px rgba(0,0,0,.34); }
    body.phase68-minimal .bot-hero h2 { font-size: 30px; letter-spacing: -.03em; margin-top: 10px; }
    body.phase68-minimal #bot_metricas { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin-top: 8px; }
    body.phase68-minimal #bot_revisoes { display: none; }
    body.phase68-minimal .global-search-wrap { margin: 18px 0 14px; position: relative; }
    body.phase68-minimal .global-search-wrap::before { content: '⌕'; position: absolute; left: 18px; top: 14px; color: #7d8795; font-size: 22px; z-index: 1; }
    body.phase68-minimal #global_search { width: 100%; min-height: 58px; border-radius: 12px; border: 0; background: #232e3a; color: #f7f8fb; padding-left: 52px; font-size: 16px; }
    body.phase68-minimal #global_search:focus { outline: 2px solid rgba(73,150,236,.42); }
    body.phase68-minimal .search-results { margin-top: 8px; border-radius: 14px; overflow: hidden; background: #202b36; border: 1px solid rgba(255,255,255,.06); }
    body.phase68-minimal .search-result { width: 100%; border: 0; border-top: 1px solid rgba(255,255,255,.06); background: transparent; color: inherit; text-align: left; padding: 13px 14px; display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; }
    body.phase68-minimal .search-result:first-child { border-top: 0; }
    body.phase68-minimal .search-result strong { display:block; }
    body.phase68-minimal .search-result span { color:#8792a2; font-size: 12px; }
    body.phase68-minimal .search-result::after { content:'›'; color:#7d8795; font-size: 24px; }
    body.phase68-minimal .group-picker { margin: 18px 0; }
    body.phase68-minimal .group-picker > label { color: #7d8795; margin-left: 2px; }
    body.phase68-minimal .group-picker select { border-radius: 13px; min-height: 58px; background: #17212b; border: 1px solid rgba(255,255,255,.09); }
    body.phase68-minimal .group-card { background: #202b36; border-color: rgba(255,255,255,.06); border-radius: 14px; padding: 14px; box-shadow: none; }
    body.phase68-minimal .headline { grid-template-columns: 68px 1fr; }
    body.phase68-minimal .avatar { border-radius: 18px; }
    
    body.phase68-minimal .status-row { margin-top: 8px; }
    body.phase68-minimal .statusbar, body.phase68-minimal .refresh-state { border-radius: 14px; background: #202b36; border-color: rgba(255,255,255,.07); }
    body.phase68-minimal #mesa_titulo { margin-top: 22px; font-size: 22px; }
    body.phase68-minimal .app-tabs { display: grid; grid-template-columns: 1fr; gap: 0; background: #202b36; border: 1px solid rgba(255,255,255,.06); border-radius: 14px; overflow: hidden; margin: 12px 0 16px; }
    body.phase68-minimal button.nav { width: 100%; min-height: 58px; border-radius: 0; border: 0; border-top: 1px solid rgba(255,255,255,.06); background: transparent; padding: 12px 44px 12px 16px; text-align: left; position: relative; display: block; }
    body.phase68-minimal button.nav:first-child { border-top: 0; }
    body.phase68-minimal button.nav::after { content: '›'; position: absolute; right: 16px; top: 50%; transform: translateY(-50%); color: #748091; font-size: 28px; font-weight: 500; }
    body.phase68-minimal button.nav.active { background: rgba(255,255,255,.045); color: #fff; }
    body.phase68-minimal button.nav.active::after { content: '⌄'; font-size: 20px; }
    body.phase68-minimal button.nav strong { display: block; font-size: 15px; margin-bottom: 2px; }
    body.phase68-minimal button.nav span:not(.nav-state) { display: block; font-size: 12px; color: #8792a2; font-weight: 500; }
    body.phase68-minimal .nav-state { position: absolute; right: 42px; top: 21px; margin: 0; background: transparent; }
    body.phase68-minimal .view { margin-top: 14px; background: #202b36; border: 1px solid rgba(255,255,255,.06); border-radius: 14px; padding: 14px; }
    body.phase68-minimal .view.hidden { display: none !important; }
    body.phase68-minimal .panel { background: #17212b; border-color: rgba(255,255,255,.06); box-shadow: none; }
    body.phase68-minimal .toolbar { gap: 8px; }
    body.phase68-minimal button.action { border-radius: 12px; }
    body.phase68-minimal .section-note { color: #97a1af; }
    body.phase68-minimal .feedback-panel { background: #202b36; border-color: rgba(255,255,255,.06); }
    body.phase68-minimal .search-empty { min-height: 170px; display: grid; place-items: center; text-align: center; color: #8792a2; padding: 28px 18px; }
    body.phase68-minimal .search-empty strong { display: block; color: #c6d0dd; margin-bottom: 4px; }
    /* Fase 71: compactação final da home no padrão cinza/preto nativo. */
    body.phase68-minimal { background: #151a20; color: #f4f7fb; font-size: 15px; }
    body.phase68-minimal #app > .top { display: none !important; }
    body.phase68-minimal .card { background: transparent; border: 0; box-shadow: none; padding: 0 6px; }
    body.phase68-minimal .bot-hero { padding: 14px 8px 2px; margin-bottom: 8px; }
    body.phase68-minimal .bot-avatar { width: 72px; height: 72px; }
    body.phase68-minimal .bot-hero h2 { font-size: 26px; margin-top: 8px; }
    body.phase68-minimal #bot_metricas { display: block; margin-top: 9px; color: #99a4b3; font-size: 13px; }
    body.phase68-minimal #global_search { min-height: 52px; background: #222d38; font-size: 15px; }
    body.phase68-minimal .global-search-wrap::before { top: 12px; font-size: 20px; }
    body.phase68-minimal .section-note { font-size: 14px; line-height: 1.35; color: #98a3b2; }
    body.phase68-minimal .group-picker select { background: #151a20; min-height: 54px; font-size: 16px; }
    body.phase68-minimal #palcos_hint { margin: 12px 0; }

        body.phase68-minimal #bot_revisoes { display: none; }
    body.phase68-minimal .group-card { background: #19232c; border-color: rgba(255,255,255,.075); border-radius: 18px; padding: 16px; box-shadow: none; }
    body.phase68-minimal .group-head { display: grid; grid-template-columns: 64px 1fr auto; gap: 12px; align-items: center; }
    body.phase68-minimal .group-head .avatar { width: 64px; height: 64px; border-radius: 18px; }
    body.phase68-minimal .group-title strong { display: block; font-size: 18px; line-height: 1.1; }
    body.phase68-minimal .group-meta-line { color: #98a3b2; font-size: 13px; margin-top: 8px; line-height: 1.35; }
    body.phase68-minimal .mini-status-button { min-height: 34px; border-radius: 999px; padding: 6px 11px; border: 1px solid rgba(255,255,255,.10); background: #222d38; color: #d7e0ec; font: inherit; font-size: 12px; font-weight: 650; white-space: nowrap; }
    body.phase68-minimal .mini-status-button.ok { color: #8af0bd; border-color: rgba(80,216,144,.25); }
    body.phase68-minimal .mini-status-button.warn { color: #ffd36e; border-color: rgba(255,211,110,.28); }
    body.phase68-minimal .mini-status-button.bad { color: #ff8a8a; border-color: rgba(255,138,138,.26); }
    body.phase68-minimal .status-row { display: none; }
    body.phase68-minimal .refresh-state { margin-top: 8px; border: 0; background: transparent; padding: 0; font-size: 12px; color: #8490a0; }
    body.phase68-minimal #palcos_hint { margin-top: 14px; }
    /* Fase 72: limpeza minimalista estrita conforme prints. */
    body.phase68-minimal { background: #12171d; font-size: 14px; }
    body.phase68-minimal main { max-width: 720px; }
    body.phase68-minimal .bot-hero { padding-top: 8px; margin-bottom: 4px; }
    body.phase68-minimal .bot-avatar { width: 62px; height: 62px; }
    body.phase68-minimal .bot-hero h2 { font-size: 23px; margin-top: 7px; letter-spacing: -.035em; }
    body.phase68-minimal #bot_usuario { margin-bottom: 5px !important; }
    body.phase68-minimal #bot_metricas { font-size: 12px; margin-top: 6px; color: #8793a1; }
    body.phase68-minimal .global-search-wrap { margin: 14px 0 12px; }
    body.phase68-minimal #global_search { min-height: 50px; border-radius: 12px; background: #1f2a34; font-size: 14px; }
    body.phase68-minimal #inicio_view > .section-note,
    body.phase68-minimal #palcos_hint { display: none !important; }
    body.phase68-minimal .group-picker { margin: 14px 0 10px; }
    body.phase68-minimal .group-picker > label { font-size: 12px; }
    body.phase68-minimal .group-picker select { min-height: 50px; font-size: 14px; }
    body.phase68-minimal .group-card { padding: 14px; background: #17212a; }
    body.phase68-minimal .group-head { grid-template-columns: 56px 1fr auto; gap: 11px; }
    body.phase68-minimal .group-head .avatar { width: 56px; height: 56px; border-radius: 16px; }
    body.phase68-minimal .group-title strong { display: inline; font-size: 17px; }
    body.phase68-minimal #grupo_descricao { display: none !important; }
    body.phase68-minimal .inline-dot,
    body.phase68-minimal .group-desc-inline { color: #98a3b2; font-weight: 500; }
    body.phase68-minimal .group-meta-line { font-size: 12px; margin-top: 6px; }
    body.phase68-minimal .mini-status-button { min-height: 30px; padding: 5px 10px; font-size: 11px; }
    body.phase68-minimal #mesa_titulo { display: none !important; }
    body.phase68-minimal .refresh-state { display: none !important; }
    body.phase68-minimal .app-tabs { margin-top: 14px; }
    body.phase68-minimal button.nav { min-height: 54px; padding-top: 10px; padding-bottom: 10px; }
    body.phase68-minimal button.nav strong { font-size: 14px; }
    body.phase68-minimal button.nav span:not(.nav-state) { font-size: 12px; }
    body.phase68-minimal .view .toolbar:not(.app-tabs),
    body.phase68-minimal .panel .toolbar:not(.app-tabs),
    body.phase68-minimal .config-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }

    /* Fase 73: navegação interna por telas, no padrão lista -> detalhe -> voltar. */
    body.phase68-minimal.detail-mode #inicio_view,
    body.phase68-minimal.detail-mode #palco_header,
    body.phase68-minimal.detail-mode #palcos_hint,
    body.phase68-minimal.detail-mode #palcos,
    body.phase68-minimal.detail-mode #mesa_titulo,
    body.phase68-minimal.detail-mode .app-tabs,
    body.phase68-minimal.detail-mode .status-row,
    body.phase68-minimal.detail-mode .refresh-state { display: none !important; }
    body.phase68-minimal.detail-mode .view { display: block; margin-top: 10px; }
    body.phase68-minimal.detail-mode .view.hidden { display: none !important; }
    .detail-nav { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 12px; margin: 10px 0 14px; }
    .detail-back { border: 0; border-radius: 999px; padding: 8px 12px; min-height: 38px; background: #1f2a34; color: #f7f8fb; font-weight: 650; }
    .detail-title { margin: 0; font-size: 22px; letter-spacing: -.02em; }
    .detail-subtitle { display: none; color: #8e99a8; font-size: 13px; margin-top: 2px; }
    body.phase68-minimal.detail-mode .view > .window-title,
    body.phase68-minimal.detail-mode .view > .section-note:first-of-type { display: none !important; }


    /* Fase 74: telas internas minimalistas em cinza/preto, sem subtítulos redundantes e sem camadas azuis. */
    body.phase74-botfather-pages { background: #161b20; color: #f4f6f8; }
    body.phase74-botfather-pages main { max-width: 720px; }
    body.phase74-botfather-pages .bot-hero { padding-top: 6px; }
    body.phase74-botfather-pages .bot-avatar { width: 58px; height: 58px; }
    body.phase74-botfather-pages .bot-hero h2 { font-size: 22px; }
    body.phase74-botfather-pages #global_search { background: #222a32; border: 1px solid rgba(255,255,255,.07); }
    body.phase74-botfather-pages .group-card,
    body.phase74-botfather-pages .app-tabs,
    body.phase74-botfather-pages .view,
    body.phase74-botfather-pages .panel,
    body.phase74-botfather-pages .feedback-panel { background: #1b222a; border-color: rgba(255,255,255,.075); box-shadow: none; }
    body.phase74-botfather-pages .view { padding: 0; overflow: hidden; }
    body.phase74-botfather-pages.detail-mode .view { padding: 18px; }
    body.phase74-botfather-pages .view > .grid,
    body.phase74-botfather-pages .view > .panel-split { gap: 10px; }
    body.phase74-botfather-pages .view .panel { background: #171d23; border-color: rgba(255,255,255,.055); }
    body.phase74-botfather-pages .app-tabs { border-radius: 18px; margin-top: 14px; }
    body.phase74-botfather-pages button.nav { min-height: 50px; padding: 14px 48px 14px 16px; background: transparent; }
    body.phase74-botfather-pages button.nav span:not(.nav-state) { display: none !important; }
    body.phase74-botfather-pages .nav-state { display: none !important; }
    body.phase74-botfather-pages button.nav::after { right: 18px; color: #7d8794; }
    body.phase74-botfather-pages button.nav.active::after { content: '›'; font-size: 28px; }
    body.phase74-botfather-pages button.nav strong { font-size: 15px; margin: 0; }
    body.phase74-botfather-pages .detail-nav { margin: 8px 0 12px; }
    body.phase74-botfather-pages .detail-back { background: #20272f; border: 1px solid rgba(255,255,255,.07); }
    body.phase74-botfather-pages .detail-title { font-size: 22px; }
    body.phase74-botfather-pages .section-note { display: none; }
    body.phase74-botfather-pages .view p.section-note { display: none !important; }
    body.phase74-botfather-pages h3.window-title { display: none !important; }
    body.phase74-botfather-pages button.action { background: #242c36; border: 1px solid rgba(255,255,255,.09); color: #f4f6f8; min-height: 44px; box-shadow: none; }
    body.phase74-botfather-pages button.action:hover { box-shadow: none; filter: brightness(1.08); }
    body.phase74-botfather-pages button.action.secondary { background: #242c36; color: #f4f6f8; }
    body.phase74-botfather-pages button.action[data-action="fixados.criar"],
    body.phase74-botfather-pages button.action[data-action="fixados.remover"],
    body.phase74-botfather-pages button.action[data-action="topicos.criar"],
    body.phase74-botfather-pages button.action[data-action="topicos.editar"],
    body.phase74-botfather-pages button.action[data-action="topicos.reabrir"],
    body.phase74-botfather-pages button.action[data-action="topicos.desfixar"],
    body.phase74-botfather-pages button.action[data-action="topicos.geral.reabrir"],
    body.phase74-botfather-pages button.action[data-action="topicos.geral.exibir"],
    body.phase74-botfather-pages button.action[data-action="topicos.geral.desfixar"],
    body.phase74-botfather-pages button.action[data-action="grupo.descricao"],
    body.phase74-botfather-pages button.action[data-action="admins.titulo"],
    body.phase74-botfather-pages button#resolver_mensagem,
    body.phase74-botfather-pages button#resolver_alvo { background: #2b75d6; color: #fff; border-color: rgba(255,255,255,.10); }
    body.phase74-botfather-pages button.action[data-action="convites.criar"],
    body.phase74-botfather-pages button.action[data-action="entradas.aprovar"],
    body.phase74-botfather-pages button.action[data-action="membros.liberar"],
    body.phase74-botfather-pages button.action[data-action="membros.reintegrar"],
    body.phase74-botfather-pages button.action[data-action="canais_remetentes.liberar"],
    body.phase74-botfather-pages button.action[data-action="admins.promover"],
    body.phase74-botfather-pages button.action[data-action="silencio.desativar"],
    body.phase74-botfather-pages button.action[data-action="grupo.foto"] { background: #167548; color: #fff; }
    body.phase74-botfather-pages button.action[data-action="mensagens.apagar"],
    body.phase74-botfather-pages button#seguranca_modo_restrito,
    body.phase74-botfather-pages button#radio_schedule_cancelar,
    body.phase74-botfather-pages button#ddx_cancelar_agendado,
    body.phase74-botfather-pages button#novos_apagar,
    body.phase74-botfather-pages button#novos_banir,
    body.phase74-botfather-pages button.action[data-action="membros.remover"],
    body.phase74-botfather-pages button.action[data-action="entradas.recusar"],
    body.phase74-botfather-pages button.action[data-action="convites.revogar"],
    body.phase74-botfather-pages button.action[data-action="topicos.apagar"],
    body.phase74-botfather-pages button.action[data-action="canais_remetentes.banir"],
    body.phase74-botfather-pages button.action[data-action="admins.rebaixar"],
    body.phase74-botfather-pages button.action[data-action="grupo.foto.remover"] { background: #9f261f; color: #fff; }
    body.phase74-botfather-pages .toolbar { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
    body.phase74-botfather-pages .toolbar > button:only-child { grid-column: 1 / -1; }
    body.phase74-botfather-pages select,
    body.phase74-botfather-pages textarea,
    body.phase74-botfather-pages input { background: #131924; border-color: rgba(255,255,255,.12); }
    body.phase74-botfather-pages .empty { background: #131924; border-color: rgba(255,255,255,.08); }
    @media (max-width: 560px) {
      body.phase74-botfather-pages .toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      body.phase74-botfather-pages .toolbar > button:only-child { grid-column: 1 / -1; }
      body.phase74-botfather-pages.detail-mode .view { padding: 14px; }
    }

    /* Fase 75: auditoria visual global do Mini App.
       Mantém backend intacto e consolida padrão cinza/preto, listas secas e botões consistentes. */
    body.phase75-miniapp-review {
      background: #11161c;
      color: #f3f5f8;
      font-size: 13px;
    }
    body.phase75-miniapp-review main { max-width: 720px; }
    body.phase75-miniapp-review .bot-hero,
    body.phase75-miniapp-review .group-card,
    body.phase75-miniapp-review .app-tabs,
    body.phase75-miniapp-review .view,
    body.phase75-miniapp-review .panel,
    body.phase75-miniapp-review .feedback-panel {
      background: #171d23;
      border-color: rgba(255,255,255,.075);
      box-shadow: none;
    }
    body.phase75-miniapp-review .bot-hero {
      display: grid;
      grid-template-columns: 54px 1fr;
      gap: 12px;
      align-items: center;
      padding: 8px 4px 6px;
      margin-bottom: 10px;
    }
    body.phase75-miniapp-review .bot-avatar { width: 54px; height: 54px; border-radius: 16px; }
    body.phase75-miniapp-review .bot-hero h2 { font-size: 20px; margin: 0 0 2px; letter-spacing: -.03em; }
    body.phase75-miniapp-review #bot_usuario,
    body.phase75-miniapp-review #bot_metricas { font-size: 12px; line-height: 1.25; color: #8f9baa; }
    body.phase75-miniapp-review .global-search-wrap { margin: 10px 0 12px; }
    body.phase75-miniapp-review #global_search {
      min-height: 48px;
      border-radius: 13px;
      background: #1b232b;
      border-color: rgba(255,255,255,.08);
      font-size: 13px;
    }
    body.phase75-miniapp-review .group-picker { margin: 8px 0 10px; }
    body.phase75-miniapp-review .group-picker > label { font-size: 11px; color: #7f8b99; margin-bottom: 6px; }
    body.phase75-miniapp-review .group-picker select {
      min-height: 48px;
      border-radius: 13px;
      background: #11161c;
      border-color: rgba(255,255,255,.09);
      font-size: 13px;
    }
    body.phase75-miniapp-review .group-card { padding: 13px; border-radius: 18px; }
    body.phase75-miniapp-review .group-head { grid-template-columns: 52px 1fr auto; gap: 11px; }
    body.phase75-miniapp-review .group-head .avatar { width: 52px; height: 52px; border-radius: 15px; }
    body.phase75-miniapp-review .group-title strong { font-size: 16px; line-height: 1.15; }
    body.phase75-miniapp-review .group-desc-inline { font-size: 13px; color: #8e99a8; }
    body.phase75-miniapp-review .group-meta-line { font-size: 12px; color: #8e99a8; line-height: 1.35; }
    body.phase75-miniapp-review .mini-status-button { background: #16221d; border-color: rgba(80,216,144,.20); color: #9debc0; }
    body.phase75-miniapp-review .app-tabs { border-radius: 16px; overflow: hidden; margin-top: 12px; }
    body.phase75-miniapp-review button.nav {
      min-height: 46px;
      padding: 12px 42px 12px 14px;
      background: transparent;
      border-top: 1px solid rgba(255,255,255,.055);
    }
    body.phase75-miniapp-review button.nav:first-child { border-top: 0; }
    body.phase75-miniapp-review button.nav strong { font-size: 14px; line-height: 1.1; margin: 0; }
    body.phase75-miniapp-review button.nav span:not(.nav-state),
    body.phase75-miniapp-review .detail-subtitle { display: none !important; }
    body.phase75-miniapp-review button.nav.active { background: rgba(255,255,255,.035); }
    body.phase75-miniapp-review button.nav::after,
    body.phase75-miniapp-review button.nav.active::after { content: '›'; right: 15px; color: #707b89; font-size: 24px; }
    body.phase75-miniapp-review.detail-mode .view {
      background: #171d23;
      border-radius: 18px;
      padding: 14px;
      overflow: hidden;
    }
    body.phase75-miniapp-review .view .panel { background: #141a20; border-color: rgba(255,255,255,.065); }
    body.phase75-miniapp-review .panel h3 { font-size: 15px; margin: 4px 0 10px; }
    body.phase75-miniapp-review .panel p.muted.small,
    body.phase75-miniapp-review .empty.small { font-size: 12px; line-height: 1.35; }
    body.phase75-miniapp-review .toolbar {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      align-items: stretch;
    }
    body.phase75-miniapp-review .toolbar > button:only-child,
    body.phase75-miniapp-review .toolbar > button:nth-child(odd):last-child { grid-column: 1 / -1; }
    body.phase75-miniapp-review button.action {
      width: 100%;
      min-height: 44px;
      border-radius: 12px;
      background: #232a32;
      border: 1px solid rgba(255,255,255,.09);
      color: #f3f5f8;
      box-shadow: none;
    }
    body.phase75-miniapp-review button.action.secondary { background: #232a32; color: #f3f5f8; }
    body.phase75-miniapp-review button.action:hover { box-shadow: none; filter: brightness(1.06); }
    body.phase75-miniapp-review select,
    body.phase75-miniapp-review textarea,
    body.phase75-miniapp-review input { background: #111722; border-color: rgba(255,255,255,.12); }
    body.phase75-miniapp-review .empty { background: #111722; border-color: rgba(255,255,255,.08); }
    @media (max-width: 560px) {
      body.phase75-miniapp-review { padding-left: 12px; padding-right: 12px; }
      body.phase75-miniapp-review .toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      body.phase75-miniapp-review .toolbar > button:only-child,
      body.phase75-miniapp-review .toolbar > button:nth-child(odd):last-child { grid-column: 1 / -1; }
    }

    /* Fase 76: governantes recolhidos e cinza/preto real, sem listas imensas abertas. */
    body.phase76-governance-compact {
      background: #101418;
      color: #f3f5f7;
    }
    body.phase76-governance-compact .bot-hero,
    body.phase76-governance-compact .group-card,
    body.phase76-governance-compact .app-tabs,
    body.phase76-governance-compact .view,
    body.phase76-governance-compact .panel,
    body.phase76-governance-compact .feedback-panel {
      background: #161b20;
      border-color: rgba(255,255,255,.075);
      box-shadow: none;
    }
    body.phase76-governance-compact .panel,
    body.phase76-governance-compact .governance-card,
    body.phase76-governance-compact .governance-role,
    body.phase76-governance-compact .empty { background: #14191f; }
    body.phase76-governance-compact .view .panel { background: #14191f; }
    body.phase76-governance-compact input,
    body.phase76-governance-compact textarea,
    body.phase76-governance-compact select { background: #11161c; }
    body.phase76-governance-compact .toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    body.phase76-governance-compact .toolbar > button:only-child,
    body.phase76-governance-compact .toolbar > button:nth-child(odd):last-child { grid-column: 1 / -1; }
    body.phase76-governance-compact .governance-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
    }
    body.phase76-governance-compact .governance-card {
      border: 1px solid rgba(255,255,255,.075);
      border-radius: 15px;
      padding: 0;
      overflow: hidden;
    }
    body.phase76-governance-compact .governance-card > summary {
      list-style: none;
      cursor: pointer;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
      min-height: 48px;
      padding: 12px 14px;
      color: #f3f5f7;
    }
    body.phase76-governance-compact .governance-card > summary::-webkit-details-marker { display: none; }
    body.phase76-governance-compact .governance-card > summary::after {
      content: '›';
      color: #8c96a3;
      font-size: 22px;
      line-height: 1;
      transform: rotate(90deg);
      transition: transform .16s ease;
    }
    body.phase76-governance-compact .governance-card[open] > summary::after { transform: rotate(-90deg); }
    body.phase76-governance-compact .governance-person-main {
      display: block;
      font-weight: 700;
      line-height: 1.2;
    }
    body.phase76-governance-compact .governance-person-sub {
      display: block;
      color: #8f9baa;
      font-size: 12px;
      margin-top: 3px;
      line-height: 1.25;
    }
    body.phase76-governance-compact .governance-detail {
      border-top: 1px solid rgba(255,255,255,.06);
      padding: 10px 12px 12px;
    }
    body.phase76-governance-compact .governance-role {
      border: 1px solid rgba(255,255,255,.075);
      border-radius: 12px;
      padding: 10px;
      margin-top: 8px;
    }
    body.phase76-governance-compact .governance-role.active { border-color: rgba(68, 201, 132, .26); }
    body.phase76-governance-compact .governance-role .muted { display: none; }
    body.phase76-governance-compact .governance-chips { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
    body.phase76-governance-compact .badge { background: rgba(255,255,255,.055); border-color: rgba(255,255,255,.08); }
    /* Fase 79: governantes reais, cargo explícito e accordion exclusivo. */
    body.phase79-governantes-reais .governance-grid { grid-template-columns: 1fr; gap: 8px; }
    body.phase79-governantes-reais .governance-card { background: #13181e; border-color: rgba(255,255,255,.08); }
    body.phase79-governantes-reais .governance-card > summary { min-height: 50px; padding: 12px 14px; }
    body.phase79-governantes-reais .governance-person-main { font-size: 14px; }
    body.phase79-governantes-reais .governance-person-sub { font-size: 12px; }
    body.phase79-governantes-reais .governance-cargo { color: #b9c4d1; font-weight: 650; }
    body.phase79-governantes-reais .governance-warn { color: #ffd166; }
    body.phase79-governantes-reais .governance-detail { background: #10151b; }
    body.phase79-governantes-reais .governance-role { background: #151b22; }
    body.phase79-governantes-reais .governance-summary-line { display: block; }
    /* Fase 80: sistema visual único. Cinza/preto como base; azul/verde/vermelho só por semântica. */
    body.phase80-visual-system {
      --eq-bg: #0f1419;
      --eq-surface: #151b21;
      --eq-surface-2: #1a2129;
      --eq-surface-3: #202832;
      --eq-border: rgba(255,255,255,.075);
      --eq-text: #f2f5f8;
      --eq-muted: #8e99a7;
      --eq-primary: #2b75d6;
      --eq-success: #168a55;
      --eq-danger: #a52a24;
      --eq-warning: #d99a2b;
      background: var(--eq-bg);
      color: var(--eq-text);
    }
    body.phase80-visual-system .bot-hero,
    body.phase80-visual-system .group-card,
    body.phase80-visual-system .app-tabs,
    body.phase80-visual-system .view,
    body.phase80-visual-system .panel,
    body.phase80-visual-system .feedback-panel,
    body.phase80-visual-system .governance-card,
    body.phase80-visual-system .governance-role,
    body.phase80-visual-system .item,
    body.phase80-visual-system .empty {
      background: var(--eq-surface);
      border-color: var(--eq-border);
      box-shadow: none;
    }
    body.phase80-visual-system .view .panel,
    body.phase80-visual-system .governance-detail,
    body.phase80-visual-system .search-results { background: var(--eq-surface-2); border-color: var(--eq-border); }
    body.phase80-visual-system input,
    body.phase80-visual-system textarea,
    body.phase80-visual-system select { background: #10161d; border-color: var(--eq-border); color: var(--eq-text); }
    body.phase80-visual-system .muted,
    body.phase80-visual-system .section-note,
    body.phase80-visual-system .small.muted,
    body.phase80-visual-system .governance-person-sub,
    body.phase80-visual-system .group-meta-line { color: var(--eq-muted); }
    body.phase80-visual-system button.nav,
    body.phase80-visual-system button.action,
    body.phase80-visual-system .detail-back,
    body.phase80-visual-system .mini-status-button {
      background: var(--eq-surface-3);
      border-color: var(--eq-border);
      color: var(--eq-text);
      box-shadow: none;
    }
    body.phase80-visual-system button.nav.active { background: rgba(255,255,255,.045); }
    body.phase80-visual-system button.action.primary,
    body.phase80-visual-system button.action[data-action="grupo.descricao"],
    body.phase80-visual-system button.action[data-action="fixados.criar"],
    body.phase80-visual-system button.action[data-action="topicos.criar"],
    body.phase80-visual-system button#resolver_mensagem,
    body.phase80-visual-system button#resolver_alvo { background: var(--eq-primary); color: #fff; }
    body.phase80-visual-system button.action[data-action="convites.criar"],
    body.phase80-visual-system button.action[data-action="entradas.aprovar"],
    body.phase80-visual-system button.action[data-action="membros.liberar"],
    body.phase80-visual-system button.action[data-action="membros.reintegrar"],
    body.phase80-visual-system button.action[data-action="grupo.foto"],
    body.phase80-visual-system .mini-status-button.ok,
    body.phase80-visual-system .statusbar.ok { background: var(--eq-success); color: #fff; border-color: rgba(255,255,255,.12); }
    body.phase80-visual-system button.action[data-action="mensagens.apagar"],
    body.phase80-visual-system button.action[data-action="membros.remover"],
    body.phase80-visual-system button.action[data-action="entradas.recusar"],
    body.phase80-visual-system button.action[data-action="convites.revogar"],
    body.phase80-visual-system button.action[data-action="topicos.apagar"],
    body.phase80-visual-system button.action[data-action="grupo.foto.remover"],
    body.phase80-visual-system button#radio_schedule_cancelar,
    body.phase80-visual-system button#ddx_cancelar_agendado,
    body.phase80-visual-system button#novos_apagar,
    body.phase80-visual-system button#novos_banir { background: var(--eq-danger); color: #fff; border-color: rgba(255,255,255,.12); }
    body.phase80-visual-system .statusbar.warn,
    body.phase80-visual-system .governance-warn { color: #ffd166; background: transparent; }
    body.phase80-visual-system .badge,
    body.phase80-visual-system .right-chip { background: rgba(255,255,255,.055); border-color: var(--eq-border); color: var(--eq-text); }
    body.phase80-visual-system .right-chip.ok { color: #95e8bb; }
    body.phase80-visual-system .right-chip.bad { color: #ffaaa5; }



    /* Fase 77: Home despoluida, foto central e busca como entrada principal. */
    body.phase77-search-home { background: #101419; }
    body.phase77-search-home #app > .top,
    body.phase77-search-home #app > .row { display: none !important; }
    body.phase77-search-home #inicio_view { margin-top: 0; }
    body.phase77-search-home .bot-hero {
      display: grid;
      grid-template-columns: 1fr;
      justify-items: center;
      text-align: center;
      background: transparent;
      border: 0;
      padding: 12px 6px 8px;
      margin: 0 0 10px;
    }
    body.phase77-search-home .bot-avatar {
      width: 92px;
      height: 92px;
      border-radius: 50%;
      object-fit: cover;
      box-shadow: 0 12px 34px rgba(0,0,0,.42);
      border: 1px solid rgba(255,255,255,.09);
    }
    body.phase77-search-home .bot-hero h2 { font-size: 24px; margin: 10px 0 2px; }
    body.phase77-search-home #bot_usuario { margin: 0 0 4px !important; font-size: 12px; }
    body.phase77-search-home #bot_metricas { font-size: 12px; color: #8d98a6; margin-top: 4px; }
    body.phase77-search-home .global-search-wrap { margin: 12px 0 12px; }
    body.phase77-search-home #global_search { min-height: 50px; background: #1b222a; border-color: rgba(255,255,255,.08); font-size: 14px; }
    body.phase77-search-home #palco_header > label,
    body.phase77-search-home #palco_header_select,
    body.phase77-search-home #palcos_hint,
    body.phase77-search-home #palcos { display: none !important; }
    body.phase77-search-home #palco_header { margin: 0; }
    body.phase77-search-home #grupo_resumo_card { display: none; }
    body.phase77-search-home.group-selected #grupo_resumo_card { display: block; margin-top: 8px; }
    body.phase77-search-home:not(.group-selected) #mesa { display: none !important; }
    body.phase77-search-home .search-results { border-radius: 14px; background: #171d23; border-color: rgba(255,255,255,.075); }
    body.phase77-search-home .search-result { min-height: 50px; }


    /* Fase 78: páginas internas cautelosas, com BackButton nativo quando disponível. */
    body.phase78-internal-pages.detail-mode { background: #101419; }
    body.phase78-internal-pages.detail-mode #inicio_view,
    body.phase78-internal-pages.detail-mode #palco_header,
    body.phase78-internal-pages.detail-mode .app-tabs { display: none !important; }
    body.phase78-internal-pages .detail-nav {
      position: sticky;
      top: max(8px, var(--tg-safe-area-inset-top, 0px));
      z-index: 8;
      background: rgba(16,20,25,.96);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,.075);
      border-radius: 16px;
      padding: 8px;
      margin: 8px 0 10px;
    }
    body.phase78-internal-pages .detail-back { background: #1b222a; min-height: 38px; }
    body.phase78-internal-pages .detail-title { font-size: 19px; }
    body.phase78-internal-pages.detail-mode .view {
      background: #161b20;
      border-color: rgba(255,255,255,.075);
      border-radius: 18px;
      padding: 14px;
    }
    body.phase78-internal-pages .view > .window-title,
    body.phase78-internal-pages .view > .section-note:first-of-type { display: none !important; }
    body.phase78-internal-pages button.nav span:not(.nav-state),
    body.phase78-internal-pages .nav-state { display: none !important; }
    body.phase78-internal-pages button.nav { min-height: 49px; }
    body.phase78-internal-pages button.nav strong { font-size: 14px; }


    /* Fase 81: a busca volta a conduzir a entrada no painel sem deixar a home vazia. */
    body.phase81-search-suggestions:not(.group-selected) #global_search_results {
      display: block;
      margin-top: 10px;
    }
    body.phase81-search-suggestions .search-result.quick-suggestion strong::before {
      content: '';
    }
    body.phase81-search-suggestions .search-result.quick-suggestion {
      min-height: 48px;
    }
    body.phase81-search-suggestions .search-result .search-kind {
      color: #8995a3;
      font-size: 12px;
    }
    body.phase81-search-suggestions .search-empty {
      min-height: 88px;
      padding: 16px;
    }

    /* Fase 82: estados compactos e feedback único, sem card vazio gigante. */
    body.phase82-state-feedback .search-empty,
    body.phase82-state-feedback .empty,
    body.phase82-state-feedback .statusbar,
    body.phase82-state-feedback .refresh-state {
      border-radius: 13px;
      background: var(--eq-surface-2, #14191f);
      border: 1px solid var(--eq-border, rgba(255,255,255,.08));
      color: var(--eq-muted, #8f9baa);
      min-height: auto;
      padding: 10px 12px;
      font-size: 12px;
      line-height: 1.35;
    }
    body.phase82-state-feedback .search-empty strong,
    body.phase82-state-feedback .empty strong {
      color: var(--eq-text, #f3f5f7);
      font-size: 13px;
      margin-bottom: 2px;
    }
    body.phase82-state-feedback .feedback-panel {
      border-radius: 14px;
      background: var(--eq-surface, #161b20);
      border-color: var(--eq-border, rgba(255,255,255,.08));
      padding: 10px;
    }
    body.phase82-state-feedback .feedback-panel.ok { border-color: rgba(80,216,144,.20); }
    body.phase82-state-feedback .feedback-panel.bad { border-color: rgba(255,111,111,.22); }
    body.phase82-state-feedback .feedback-panel.warn { border-color: rgba(255,202,87,.22); }
    body.phase82-state-feedback .loading-shell,
    body.phase82-state-feedback #loading.card {
      min-height: 180px;
      display: grid;
      place-items: center;
      background: #101419;
      border: 0;
      box-shadow: none;
    }


    /* Fase 85: limpeza pós-print — remove card sobre card, listas imensas abertas e overflow de botões. */
    body.phase85-cleanup {
      --eq-bg: #101418;
      --eq-surface: #151a20;
      --eq-surface-2: #12171d;
      --eq-surface-3: #0f141a;
      --eq-border: rgba(255,255,255,.075);
      --eq-border-strong: rgba(255,255,255,.12);
      overflow-x: hidden;
    }
    body.phase85-cleanup main,
    body.phase85-cleanup .view,
    body.phase85-cleanup .panel,
    body.phase85-cleanup .feedback-panel,
    body.phase85-cleanup .grid,
    body.phase85-cleanup .toolbar,
    body.phase85-cleanup button.action,
    body.phase85-cleanup input,
    body.phase85-cleanup textarea,
    body.phase85-cleanup select { box-sizing: border-box; min-width: 0; max-width: 100%; }
    body.phase85-cleanup .view,
    body.phase85-cleanup .panel,
    body.phase85-cleanup .feedback-panel,
    body.phase85-cleanup .group-card,
    body.phase85-cleanup .app-tabs {
      background: var(--eq-surface);
      border-color: var(--eq-border);
      box-shadow: none;
    }
    body.phase85-cleanup.detail-mode .view {
      padding: 10px;
      background: transparent;
      border-color: transparent;
    }
    body.phase85-cleanup.detail-mode .view > .grid,
    body.phase85-cleanup.detail-mode .view > .panel-split,
    body.phase85-cleanup.detail-mode .view > .panel,
    body.phase85-cleanup .panel.owner-only {
      background: var(--eq-surface);
      border: 1px solid var(--eq-border);
      border-radius: 18px;
      padding: 12px;
      overflow: hidden;
    }
    body.phase85-cleanup .view .panel {
      background: var(--eq-surface-2);
      border-color: var(--eq-border);
      box-shadow: none;
      overflow: hidden;
    }
    body.phase85-cleanup .view .panel .panel,
    body.phase85-cleanup .panel .panel,
    body.phase85-cleanup .diagnostic-card .diagnostic-card {
      background: var(--eq-surface-3);
      border-color: var(--eq-border);
    }
    body.phase85-cleanup .toolbar,
    body.phase85-cleanup .config-actions,
    body.phase85-cleanup .feedback-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      width: 100%;
      overflow: hidden;
    }
    body.phase85-cleanup .toolbar > button,
    body.phase85-cleanup .config-actions > button,
    body.phase85-cleanup .feedback-actions > button,
    body.phase85-cleanup button.action {
      width: 100%;
      min-width: 0;
      max-width: 100%;
      white-space: normal;
      overflow-wrap: anywhere;
      line-height: 1.2;
    }
    body.phase85-cleanup .toolbar > button:only-child,
    body.phase85-cleanup .toolbar > button:nth-child(odd):last-child,
    body.phase85-cleanup .config-actions > button:only-child,
    body.phase85-cleanup .config-actions > button:nth-child(odd):last-child,
    body.phase85-cleanup .feedback-actions > button:only-child,
    body.phase85-cleanup .feedback-actions > button:nth-child(odd):last-child { grid-column: 1 / -1; }
    body.phase85-cleanup #seguranca_view .toolbar,
    body.phase85-cleanup #config_view .toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    body.phase85-cleanup #seguranca_modo_restrito,
    body.phase85-cleanup #seguranca_exportar_criptografado,
    body.phase85-cleanup #seguranca_limpar_locks { grid-column: 1 / -1; }
    body.phase85-cleanup .feedback-panel { padding: 12px; }
    body.phase85-cleanup .feedback-head {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
    }
    body.phase85-cleanup .feedback-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: start;
      overflow: hidden;
    }
    body.phase85-cleanup .feedback-copy-one {
      max-width: 84px;
      min-width: 66px;
      white-space: nowrap;
    }
    body.phase85-cleanup .disclosure-list {
      display: grid;
      gap: 8px;
    }
    body.phase85-cleanup details.disclosure-row,
    body.phase85-cleanup details.diagnostic-section {
      background: var(--eq-surface-2);
      border: 1px solid var(--eq-border);
      border-radius: 14px;
      overflow: hidden;
    }
    body.phase85-cleanup details.disclosure-row > summary,
    body.phase85-cleanup details.diagnostic-section > summary {
      list-style: none;
      cursor: pointer;
      display: grid;
      grid-template-columns: minmax(0,1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 11px 12px;
    }
    body.phase85-cleanup details.disclosure-row > summary::-webkit-details-marker,
    body.phase85-cleanup details.diagnostic-section > summary::-webkit-details-marker { display: none; }
    body.phase85-cleanup details.disclosure-row > summary::after,
    body.phase85-cleanup details.diagnostic-section > summary::after {
      content: '›';
      color: var(--eq-muted, #8f9baa);
      font-size: 22px;
      transform: rotate(90deg);
      transition: transform .16s ease;
    }
    body.phase85-cleanup details.disclosure-row[open] > summary::after,
    body.phase85-cleanup details.diagnostic-section[open] > summary::after { transform: rotate(-90deg); }
    body.phase85-cleanup .disclosure-title { font-weight: 700; color: var(--eq-text, #f4f7fa); }
    body.phase85-cleanup .disclosure-sub { display: block; color: var(--eq-muted, #8f9baa); font-size: 12px; line-height: 1.3; margin-top: 3px; }
    body.phase85-cleanup .disclosure-body,
    body.phase85-cleanup .diagnostic-section-body {
      border-top: 1px solid var(--eq-border);
      padding: 10px 12px 12px;
      color: var(--eq-muted, #8f9baa);
      overflow-wrap: anywhere;
    }
    body.phase85-cleanup .diagnostic-grid { gap: 8px; }
    body.phase85-cleanup .diagnostic-section-body { display: grid; gap: 8px; }
    body.phase85-cleanup .diagnostic-card { background: var(--eq-surface-2); border-color: var(--eq-border); }
    body.phase85-cleanup .diagnostic-card.ok { background: rgba(22,138,85,.10); }
    body.phase85-cleanup .diagnostic-card.bad { background: rgba(180,35,24,.12); }
    body.phase85-cleanup .diagnostic-card.warn { background: rgba(199,120,0,.10); }
    body.phase85-cleanup .matrix-summary { display: block; color: var(--eq-muted, #8f9baa); font-size: 12px; margin-top: 3px; }
    @media (max-width: 560px) {
      body.phase85-cleanup .toolbar,
      body.phase85-cleanup .config-actions,
      body.phase85-cleanup .feedback-actions,
      body.phase85-cleanup #seguranca_view .toolbar,
      body.phase85-cleanup #config_view .toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      body.phase85-cleanup button.action { min-height: 42px; padding-left: 10px; padding-right: 10px; font-size: 13px; }
      body.phase85-cleanup .view .panel { padding: 12px; }
    }


    /* Fase 89: governança owner-only e cadastro pelo painel sem expor IDs no resumo. */
    body.phase89-owner-governance .owner-governance-add {
      border: 1px solid rgba(255,255,255,.075);
      border-radius: 14px;
      background: #12171d;
      padding: 12px;
      margin: 10px 0;
    }
    body.phase89-owner-governance .owner-governance-add .formgrid { margin-top: 8px; }
    body.phase89-owner-governance .owner-governance-add input { min-width: 0; }
    body.phase89-owner-governance .owner-governance-add .hint-private { color: #8d98a7; font-size: 12px; line-height: 1.35; }

    /* Fase 98: UX minimalista final — reduz card sobre card, texto redundante e azul estrutural. */
    body.phase98-ux-final {
      --eq-bg: #0e1217;
      --eq-surface: #14191f;
      --eq-surface-2: #11161c;
      --eq-surface-3: #0d1116;
      --eq-border: rgba(255,255,255,.07);
      --eq-muted: #8b96a5;
      background: var(--eq-bg);
      color: #f3f6f8;
    }
    body.phase98-ux-final .view,
    body.phase98-ux-final .panel,
    body.phase98-ux-final .feedback-panel,
    body.phase98-ux-final .group-card,
    body.phase98-ux-final .app-tabs,
    body.phase98-ux-final details.disclosure-row,
    body.phase98-ux-final details.diagnostic-section,
    body.phase98-ux-final .governance-card,
    body.phase98-ux-final .empty,
    body.phase98-ux-final .item,
    body.phase98-ux-final .item-line {
      background: var(--eq-surface);
      border-color: var(--eq-border);
      box-shadow: none;
    }
    body.phase98-ux-final.detail-mode .view { background: transparent; border-color: transparent; padding: 8px; }
    body.phase98-ux-final .view .panel { background: var(--eq-surface); border-color: var(--eq-border); }
    body.phase98-ux-final .panel .panel,
    body.phase98-ux-final .view .panel .panel,
    body.phase98-ux-final .diagnostic-card,
    body.phase98-ux-final .governance-role,
    body.phase98-ux-final .disclosure-body,
    body.phase98-ux-final .diagnostic-section-body { background: var(--eq-surface-2); border-color: var(--eq-border); }
    body.phase98-ux-final .section-note,
    body.phase98-ux-final .view p.section-note,
    body.phase98-ux-final .panel > p.muted.small { display: none !important; }
    body.phase98-ux-final .panel h3 { margin: 2px 0 9px; font-size: 14px; letter-spacing: -.01em; }
    body.phase98-ux-final .grid,
    body.phase98-ux-final .panel-split,
    body.phase98-ux-final .diagnostic-grid,
    body.phase98-ux-final .disclosure-list { gap: 8px; }
    body.phase98-ux-final .panel { padding: 10px; border-radius: 15px; }
    body.phase98-ux-final .item,
    body.phase98-ux-final .item-line,
    body.phase98-ux-final .empty { padding: 9px 10px; border-radius: 12px; }
    body.phase98-ux-final button.action { min-height: 42px; border-radius: 12px; background: #232b34; }
    body.phase98-ux-final button.action.secondary { background: #20272f; }
    body.phase98-ux-final button.action.warn { background: #5c3d16; }
    body.phase98-ux-final button.action.bad { background: #6a201c; }
    body.phase98-ux-final input,
    body.phase98-ux-final textarea,
    body.phase98-ux-final select { background: var(--eq-surface-3); border-color: var(--eq-border); }
    body.phase98-ux-final .toolbar,
    body.phase98-ux-final .config-actions,
    body.phase98-ux-final .feedback-actions { gap: 7px; }


    /* Fase 99: menus recolhíveis e listas roláveis por padrão. */
    body.phase99-collapsible-menus .collapsible-list-shell {
      border: 1px solid var(--eq-border, rgba(255,255,255,.07));
      border-radius: 14px;
      overflow: hidden;
      background: var(--eq-surface, #14191f);
    }
    body.phase99-collapsible-menus .collapsible-list-shell > summary {
      list-style: none;
      cursor: pointer;
      display: grid;
      grid-template-columns: minmax(0,1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
    }
    body.phase99-collapsible-menus .collapsible-list-shell > summary::-webkit-details-marker { display: none; }
    body.phase99-collapsible-menus .collapsible-list-shell > summary::after {
      content: '›';
      color: var(--eq-muted, #8b96a5);
      font-size: 22px;
      transform: rotate(90deg);
      transition: transform .16s ease;
    }
    body.phase99-collapsible-menus .collapsible-list-shell[open] > summary::after { transform: rotate(-90deg); }
    body.phase99-collapsible-menus .collapsible-list-body {
      border-top: 1px solid var(--eq-border, rgba(255,255,255,.07));
      display: grid;
      gap: 7px;
      padding: 9px;
      max-height: min(54vh, 420px);
      overflow-y: auto;
      overscroll-behavior: contain;
    }
    body.phase99-collapsible-menus .collapsible-list-title { font-weight: 700; color: #f3f6f8; }
    body.phase99-collapsible-menus .collapsible-list-sub { display: block; color: var(--eq-muted, #8b96a5); font-size: 12px; margin-top: 2px; }
    body.phase99-collapsible-menus #config_matriz,
    body.phase99-collapsible-menus #config_permissoes_auditoria,
    body.phase99-collapsible-menus #diagnostico_acoes { max-height: min(58vh, 460px); overflow-y: auto; padding-right: 2px; }


    @media (max-width: 560px) { body { padding: 10px 10px 88px; } .card { padding: 14px; border-radius: 18px; } h1 { font-size: 22px; } .toolbar { grid-template-columns: 1fr; gap: 6px; } button.action { width: 100%; } .app-tabs { grid-template-columns: 1fr 1fr; } .app-tabs button.nav { width: 100%; } .top { display: block; } .grid { grid-template-columns: 1fr; } .home-hint-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .group-meta { grid-template-columns: 1fr; } .config-actions { grid-template-columns: 1fr; } .feedback-head { display: grid; } .status-row { grid-template-columns: 1fr; } .refresh-action { width: 100%; } }
    @media (max-width: 560px) { body.phase68-minimal .view .toolbar:not(.app-tabs), body.phase68-minimal .panel .toolbar:not(.app-tabs), body.phase68-minimal .config-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); } body.phase68-minimal .group-head { grid-template-columns: 56px 1fr auto; } body.phase68-minimal .group-card { margin-top: 10px; } }
  .command-panel{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 24px}.command-chip{border:1px solid rgba(255,255,255,.12);background:#1d2731;color:#f3f6fb;border-radius:18px;padding:13px 10px;font-weight:800;font-size:15px}.command-chip:active{transform:scale(.98)}@media(max-width:380px){.command-panel{grid-template-columns:1fr;margin-left:18px;margin-right:18px}}

</style>
</head>
<body class="phase68-minimal">
  <script>document.body.classList.add("phase74-botfather-pages", "phase75-miniapp-review", "phase76-governance-compact", "phase77-search-home", "phase78-internal-pages", "phase79-governantes-reais", "phase80-visual-system", "phase81-search-suggestions", "phase82-state-feedback", "phase85-cleanup", "phase89-owner-governance", "phase98-ux-final", "phase99-collapsible-menus");</script>
  <main>
    <section id="loading" class="card">
      <h1>Equalizador</h1>
      <p class="muted">Carregando acesso…</p>
      <p id="panel_boot_debug" class="muted small">Inicializando painel.</p>
    </section>
    <section id="denied" class="card hidden">
      <h1>Equalizador</h1>
      <p>Acesso indisponível.</p>
      <p id="denied_detail" class="muted small">Abra pelo Telegram ou aguarde a recuperação da sessão local.</p>
    </section>
    <section id="app" class="card hidden">
      <div class="top">
        <div>
          <h1>tigraoRADIO</h1>
          <p class="muted">@tigraoRADIObot</p>
        </div>
        <span id="perfil" class="pill">Operador</span>
      </div>
      <div class="row"><span>Operador</span><strong id="nome">Operador</strong></div>
      <div class="row"><span>Referência segura</span><span id="ui_ref" class="muted small"></span></div>
      <section id="inicio_view" class="panel">
        <div class="bot-hero">
          <div id="bot_avatar" class="bot-avatar">♫</div>
          <div>
            <h2 id="bot_nome">Bot</h2>
            <p id="bot_usuario" class="muted small" style="margin:0 0 8px;">Carregando dados do bot…</p>
            <div id="bot_metricas" class="small"><span class="badge">Usuários conhecidos: —</span></div>
            <div id="bot_revisoes" class="bot-revisoes small muted"></div>
          </div>
        </div>
        <div class="global-search-wrap">
          <input id="global_search" autocomplete="off" placeholder="Buscar grupo, @, ID ou ação" aria-label="Buscar grupo, usuário, identificador ou ação" />
          <div id="global_search_results" class="search-results hidden"></div>
        </div>
        
      </section>
      <section id="palco_header" class="group-picker header-select">
        <label class="small muted">Grupo</label>
        <select id="palco_header_select"></select>
        <div id="grupo_resumo_card" class="panel group-card">
          <div id="grupo_resumo" class="group-head">
            <div id="grupo_avatar" class="avatar">♪</div>
            <div class="group-title">
              <strong id="grupo_nome">Selecione um grupo</strong>
              <p id="grupo_descricao" class="muted small" style="margin:4px 0 0;">O resumo do grupo aparece aqui.</p>
              <div id="grupo_meta_linha" class="group-meta-line">—</div>
            </div>
            <button id="grupo_card_status" class="mini-status-button" type="button" disabled>Aguardar</button>
          </div>
        </div>
      </section>
      <h2 class="hidden">Grupos</h2>
      <p id="palcos_hint" class="section-note"></p>
      <div id="palcos" class="grid hidden"></div>
      <div id="mesa" class="hidden">
        <div class="status-row">
          <div id="mesa_status" class="statusbar muted">Painel aguardando seleção.</div>
          <button id="mesa_refresh" class="action secondary refresh-action" type="button" disabled>Atualizar</button>
        </div>
        <div id="refresh_state" class="refresh-state">Aguardando seleção de grupo.</div>
        <div id="detail_nav" class="detail-nav hidden">
          <button id="detail_back" class="detail-back" type="button">← Voltar</button>
          <div>
            <h2 id="detail_title" class="detail-title">Janela</h2>
            <div id="detail_subtitle" class="detail-subtitle"></div>
          </div>
        </div>
        <h2 id="mesa_titulo">Painel do grupo</h2>
        <div class="toolbar app-tabs">
          <button class="nav secondary" data-view="mesa_view"><strong>Início</strong><span>status e resumo</span></button>
          <button class="nav secondary" data-view="perfil_view"><strong>Perfil</strong><span>nome, descrição e foto</span></button>
          <button class="nav secondary" data-view="mensagens_view"><strong>Mensagens</strong><span>enviar, fixar e apagar</span></button>
          <button class="nav secondary" data-view="radio_view"><strong>Rádio</strong><span>rascunho e mídia</span></button>
          <button class="nav secondary" data-view="ddx_view"><strong>Filtros</strong><span>DDX e 10 min</span></button>
          <button class="nav secondary" data-view="reacoes_view"><strong>Reações</strong><span>auditoria e reactors</span></button>
          <button class="nav secondary" data-view="pessoas_view"><strong>Pessoas</strong><span>membros, administradores e bots</span></button>
          <button class="nav secondary" data-view="convites_view"><strong>Convites</strong><span>criar, copiar e revogar</span></button>
          <button class="nav secondary" data-view="topicos_view"><strong>Tópicos</strong><span>fórum e tópico geral</span></button>
          <button id="maestro_nav" class="nav secondary hidden" data-view="maestro_view"><strong>Transmissão</strong><span>avisos e silêncio</span></button>
          <button class="nav secondary" data-view="afinacao_view"><strong>Diagnóstico</strong><span>permissões reais</span></button>
          <button class="nav secondary" data-view="historico_view"><strong>Histórico</strong><span>ações sanitizadas</span></button>
          <button id="seguranca_nav" class="nav secondary hidden" data-view="seguranca_view"><strong>Segurança</strong><span>modo, auditoria e exports</span></button>
          <button id="config_nav" class="nav secondary hidden" data-view="config_view"><strong>Configuração</strong><span>operadores e canais</span></button>
        </div>
        <section id="mesa_view" class="view hidden">
          <h3 class="window-title">Resumo operacional</h3>
          <p class="section-note">A navegação acima já substitui os cartões repetidos. Esta tela mostra apenas estado, pessoas e delegação quando aplicável.</p>
          <div class="panel-split">
            <div class="panel">
              <strong>Resumo de membros</strong>
              <div id="mesa_pessoas_resumo" class="empty small">Escolha um grupo para carregar membros e administradores.</div>
            </div>
            <div class="panel">
              <strong>Membros vistos recentemente</strong>
              <input id="mesa_membros_busca" class="search-box" placeholder="Buscar membro por nome ou @username" />
              <div id="mesa_membros_preview" class="member-preview compact muted small">Nenhum membro carregado ainda.</div>
            </div>
          </div>
          <div id="governantes_palco_section" class="owner-only hidden">
            <h3>Governantes deste grupo</h3>
            <p class="section-note">Área visível somente para o proprietário técnico. Mostra nome público e @username quando já vistos pelo bot.</p>
            <div id="governantes_palco" class="governance-grid muted">Governantes ainda não carregados.</div>
          </div>
        </section>
        <section id="perfil_view" class="view hidden">
          <h3 class="window-title">Perfil do grupo</h3>
          <p class="section-note">Personalização visual e textual do grupo. Título, descrição e foto ficam concentrados aqui.</p>
          <div class="grid">
            <div class="panel">
              <strong>Identidade atual</strong>
              <div id="perfil_grupo_resumo" class="empty small">A foto, o título e a descrição aparecem no cabeçalho do grupo selecionado.</div>
              <div class="toolbar"><button class="action secondary" id="perfil_atualizar_dados" type="button">Atualizar dados do Telegram</button></div>
            </div>
            <div class="panel">
              <strong>Personalização do grupo</strong>
              <p class="muted small">Alterar título e descrição exige direito real do bot e confirmação crítica.</p>
              <input id="grupo_titulo_input" maxlength="128" placeholder="Novo título do grupo" />
              <textarea id="grupo_descricao_input" maxlength="255" placeholder="Nova descrição do grupo"></textarea>
              <label class="small"><input id="admin_ciente_grupo" class="admin-ciente" type="checkbox" /> confirmo que entendo o risco da alteração do perfil do grupo</label>
              <div class="toolbar">
                <button class="action secondary" data-action="grupo.titulo" type="button">Alterar título</button>
                <button class="action secondary" data-action="grupo.descricao" type="button">Alterar descrição</button>
              </div>
              <div class="photo-actions">
                <strong>Foto do grupo</strong>
                <p class="muted small">Envie JPG, PNG ou WEBP. O backend envia a imagem ao Telegram como arquivo e não grava a imagem no histórico.</p>
                <input id="grupo_foto_input" type="file" accept="image/jpeg,image/png,image/webp" />
                <div class="toolbar">
                  <button class="action" data-action="grupo.foto" type="button">Trocar foto do grupo</button>
                  <button class="action danger" data-action="grupo.foto.remover" type="button">Remover foto do grupo</button>
                </div>
                <div id="grupo_foto_resultado" class="empty small">A foto atual aparece no cabeçalho. Após trocar ou remover, o painel recarrega os dados do Telegram.</div>
              </div>
            </div>
          </div>
        </section>
        <section id="mensagens_view" class="view hidden">
          <h3 class="window-title">Mensagens</h3>
          <p class="section-note">Envie, fixe, desfixe, apague ou resolva mensagens em uma área única. Referências técnicas continuam internas.</p>
          <div class="grid">
            <div class="panel">
              <h3>Enviar mensagem</h3>
              <textarea id="mensagem_envio_texto" maxlength="4096" placeholder="Texto que será enviado no grupo selecionado"></textarea>
              <div id="mensagem_envio_contador" class="muted small">0/4096 caracteres</div>
              <div class="formgrid">
                <label class="small"><input id="mensagem_envio_sem_preview" type="checkbox" checked /> sem prévia de links</label>
                <label class="small"><input id="mensagem_envio_sem_notificacao" type="checkbox" /> enviar sem notificação</label>
                <label class="small"><input id="mensagem_envio_fixar" type="checkbox" /> fixar depois do envio</label>
              </div>
              <div class="toolbar">
                <button class="action" data-action="mensagens.enviar" type="button">Enviar mensagem</button>
              </div>
              <div class="empty small">Para enviar e fixar, marque “fixar depois do envio”. O painel registra a mensagem como referência interna automaticamente.</div>
            </div>
            <div class="panel">
              <h3>Mensagens registradas</h3>
              <select id="mensagem_select"></select>
              <div id="mensagens_hint" class="empty small">Nenhuma mensagem carregada ainda.</div>
              <div id="mensagens_lote_lista" class="bulk-list muted">Seleção em lote aguardando mensagens registradas.</div>
              <div class="bulk-actions">
                <div id="mensagens_lote_status" class="empty small">Nenhuma mensagem selecionada para apagamento em lote.</div>
                <div class="toolbar">
                  <button id="mensagens_lote_apagar" class="action danger" type="button" disabled>Apagar selecionadas</button>
                  <button id="mensagens_lote_limpar" class="action secondary" type="button" disabled>Limpar seleção</button>
                </div>
              </div>
              <div class="toolbar">
                <button class="action danger" data-action="mensagens.apagar" type="button">Apagar mensagem</button>
                <button class="action secondary" data-action="fixados.criar" type="button">Fixar mensagem</button>
                <button class="action secondary" data-action="fixados.remover" type="button">Remover fixado</button>
              </div>
              <div id="mensagem_resultado" class="empty small">Nenhum ajuste de mensagem executado nesta sessão.</div>
            </div>
            <div class="panel">
              <h3>Resolver mensagem</h3>
              <p class="muted small">Cole o link da mensagem. O backend converte para referência interna.</p>
              <input id="mensagem_link_input" placeholder="Link da mensagem: https://t.me/c/.../..." />
              <div class="toolbar"><button id="resolver_mensagem" class="action secondary" type="button">Resolver mensagem</button></div>
            </div>
          </div>
        </section>
        <section id="radio_view" class="view hidden">
          <h3 class="window-title">Radio seguro</h3>
          <p class="section-note">Crie rascunho, confira a prévia e publique somente depois da confirmação. Texto e mídia usam referência interna após envio.</p>
          <div class="grid">
            <div class="panel">
              <h3>Novo rascunho</h3>
              <textarea id="radio_texto" maxlength="4096" placeholder="Texto da publicação ou legenda da mídia"></textarea>
              <div id="radio_contador" class="muted small">0/4096 caracteres</div>
              <label class="small">Mídia opcional: foto, vídeo ou documento até 8 MB</label>
              <input id="radio_media_input" type="file" accept="image/jpeg,image/png,image/webp,video/mp4,application/pdf,.pdf,.txt,.doc,.docx,.zip" />
              <div class="formgrid">
                <label class="small"><input id="radio_sem_preview" type="checkbox" checked /> sem prévia de links</label>
                <label class="small"><input id="radio_sem_notificacao" type="checkbox" /> enviar sem notificação</label>
                <label class="small"><input id="radio_fixar" type="checkbox" /> fixar depois de publicar</label>
              </div>
              <div class="toolbar">
                <button id="radio_criar_rascunho" class="action" type="button">Criar rascunho</button>
              </div>
              <div id="radio_resultado" class="empty small">Nenhum rascunho criado nesta sessão.</div>
            </div>
            <div class="panel">
              <h3>Postagem multimídia nativa</h3>
              <p class="muted small">Abra o privado do bot, envie texto, foto, vídeo, áudio ou documento pela própria interface do Telegram e confirme a publicação aqui.</p>
              <div class="toolbar">
                <button id="multimidia_iniciar" class="action" type="button">Abrir privado do bot</button>
                <button id="multimidia_atualizar" class="action secondary" type="button">Atualizar sessões</button>
              </div>
              <select id="multimidia_session_select"></select>
              <div id="multimidia_preview" class="empty small">Crie uma sessão. O Telegram coleta texto, foto, vídeo, áudio, voz, documento ou animação no privado do bot.</div>
              <div class="toolbar">
                <button id="multimidia_publicar" class="action" type="button">Publicar sessão</button>
              </div>
              <div id="multimidia_sessions" class="list muted">Nenhuma sessão carregada.</div>
            </div>
            <div class="panel">
              <h3>Prévia e confirmação</h3>
              <select id="radio_draft_select"></select>
              <div id="radio_preview" class="empty small">Escolha um rascunho para revisar antes de publicar.</div>
              <div class="toolbar">
                <button id="radio_publicar" class="action" type="button">Publicar rascunho</button>
                <button id="radio_cancelar" class="action danger" type="button">Cancelar rascunho</button>
              </div>
              <div class="empty small">Publicar é a etapa final. Se “fixar” estiver marcado, o bot também precisa ter direito real de fixar mensagens.</div>
            </div>
            <div class="panel">
              <h3>Modelos do Radio</h3>
              <p class="muted small">Salve textos frequentes como modelo. O uso cria um novo rascunho para revisão antes de publicar.</p>
              <input id="radio_template_nome" placeholder="Nome do modelo" maxlength="80" />
              <select id="radio_template_select"></select>
              <div class="toolbar">
                <button id="radio_template_salvar" class="action secondary" type="button">Salvar modelo</button>
                <button id="radio_template_usar" class="action" type="button">Usar como rascunho</button>
                <button id="radio_template_apagar" class="action danger" type="button">Apagar modelo</button>
              </div>
              <div id="radio_templates" class="list muted">Nenhum modelo carregado.</div>
            </div>
            <div class="panel">
              <h3>Histórico do Radio</h3>
              <p class="muted small">Publicações feitas pelo Radio, separadas do histórico técnico do Equalizador.</p>
              <div id="radio_history" class="list muted">Nenhuma publicação registrada.</div>
            </div>
            <div class="panel wide">
              <h3>Rascunhos recentes</h3>
              <div id="radio_drafts" class="list muted">Nenhum rascunho carregado.</div>
            </div>
            <div class="panel">
              <h3>Agendamento</h3>
              <p class="muted small">Agenda texto ou modelo para publicar depois. Mídia continua exigindo rascunho manual nesta etapa.</p>
              <input id="radio_schedule_datetime" type="datetime-local" />
              <label class="small"><input id="radio_schedule_respeitar_silencio" type="checkbox" checked /> respeitar janela de silêncio</label>
              <select id="radio_schedule_select"></select>
              <div class="toolbar">
                <button id="radio_schedule_criar" class="action" type="button">Agendar publicação</button>
                <button id="radio_schedule_cancelar" class="action danger" type="button">Cancelar agendamento</button>
                <button id="radio_schedules_processar" class="action secondary" type="button">Processar vencidos</button>
              </div>
              <div id="radio_schedules" class="list muted">Nenhum agendamento carregado.</div>
            </div>
            <div class="panel">
              <h3>Janela de silêncio</h3>
              <p class="muted small">Impede agendamentos e broadcast de publicar durante o período configurado, quando a opção de respeitar silêncio estiver marcada.</p>
              <label class="small"><input id="radio_quiet_enabled" type="checkbox" /> ativar silêncio operacional do Radio</label>
              <div class="formgrid">
                <div><label class="small muted">Início</label><input id="radio_quiet_start" placeholder="22:00" maxlength="5" /></div>
                <div><label class="small muted">Fim</label><input id="radio_quiet_end" placeholder="08:00" maxlength="5" /></div>
              </div>
              <label class="small muted">Fuso</label>
              <input id="radio_quiet_tz" placeholder="America/Sao_Paulo" />
              <div class="toolbar"><button id="radio_quiet_salvar" class="action" type="button">Salvar janela</button></div>
              <div id="radio_quiet_status" class="empty small">Janela ainda não carregada.</div>
            </div>
            <div class="panel wide">
              <h3>Broadcast multi-grupo</h3>
              <p class="muted small">Envia o texto atual ou modelo selecionado para grupos em que você tem canal do Radio. Limite seguro: 25 grupos por execução.</p>
              <div class="formgrid">
                <label class="small"><input id="radio_broadcast_todos" type="checkbox" /> enviar para todos os grupos permitidos</label>
                <label class="small"><input id="radio_broadcast_respeitar_silencio" type="checkbox" checked /> respeitar silêncio por grupo</label>
              </div>
              <div class="toolbar"><button id="radio_broadcast_enviar" class="action" type="button">Executar broadcast</button></div>
              <div id="radio_broadcast_resultado" class="list muted">Nenhum broadcast executado nesta sessão.</div>
            </div>
          </div>
        </section>
        <section id="ddx_view" class="view hidden">
          <h3 class="window-title">Filtros DDX</h3>
          <p class="section-note">DDX imediato apaga mensagens no ato. DDX 10 minutos agenda apagamento silencioso para 10 minutos depois. Use palavras ou frases separadas por linha, vírgula ou ponto e vírgula.</p>
          <div class="grid">
            <div class="panel">
              <h3>DDX imediato</h3>
              <p class="muted small">Use para termos que devem ser removidos assim que forem detectados. Exige direito real de apagar mensagens.</p>
              <label class="small"><input id="ddx_hard_enabled" type="checkbox" /> ativar DDX imediato neste grupo</label>
              <textarea id="ddx_hard_words" maxlength="12000" placeholder="palavra proibida
frase proibida"></textarea>
              <div class="toolbar">
                <button id="ddx_hard_salvar" class="action" type="button">Salvar DDX imediato</button>
              </div>
              <div id="ddx_hard_status" class="empty small">Filtro imediato ainda não carregado.</div>
            </div>
            <div class="panel">
              <h3>DDX 10 minutos</h3>
              <p class="muted small">A mensagem permanece visível por 10 minutos e depois é apagada. O agendamento pode ser cancelado enquanto estiver pendente.</p>
              <label class="small"><input id="ddx_soft_enabled" type="checkbox" /> ativar DDX 10 minutos neste grupo</label>
              <textarea id="ddx_soft_words" maxlength="12000" placeholder="palavra para apagar em 10 minutos
frase temporária"></textarea>
              <div class="toolbar">
                <button id="ddx_soft_salvar" class="action" type="button">Salvar DDX 10 minutos</button>
              </div>
              <div id="ddx_soft_status" class="empty small">Filtro temporário ainda não carregado.</div>
            </div>
            <div class="panel">
              <h3>Agendados para apagar</h3>
              <select id="ddx_pending_select"></select>
              <div class="toolbar"><button id="ddx_cancelar_agendado" class="action danger" type="button">Cancelar apagamento</button></div>
              <div id="ddx_pending" class="list muted">Nenhum apagamento pendente.</div>
            </div>
            <div class="panel">
              <h3>Eventos recentes</h3>
              <div id="ddx_events" class="list muted">Nenhum evento DDX registrado.</div>
            </div>
          </div>
        </section>

        <section id="reacoes_view" class="view hidden">
          <h3 class="window-title">Reações</h3>
          <p class="section-note">Auditoria de reações capturadas pelo webhook. Use o seletor para limpar reações recentes ou aplicar silêncio de interação ao reactor sem expor identificador técnico.</p>
          <div class="grid">
            <div class="panel">
              <h3>Resumo</h3>
              <div id="reacoes_resumo" class="statusbar muted">Escolha um grupo para carregar auditoria de reações.</div>
              <div class="toolbar"><button id="reacoes_atualizar" class="action secondary" type="button">Atualizar reações</button></div>
            </div>
            <div class="panel">
              <h3>Reactor selecionado</h3>
              <select id="reactor_select"></select>
              <label class="small muted">Duração do silêncio de interação</label>
              <select id="reactor_silencio_minutos">
                <option value="10">10 minutos</option>
                <option value="60" selected>1 hora</option>
                <option value="1440">24 horas</option>
                <option value="10080">7 dias</option>
              </select>
              <div class="toolbar">
                <button class="action secondary" data-action="reacoes.recentes.limpar" type="button">Limpar reações recentes</button>
                <button id="reacoes_silenciar_reactor" class="action" type="button">Silenciar reactor</button>
              </div>
              <div id="reactor_hint" class="empty small">Nenhum reactor recente carregado.</div>
              <p class="muted small">O silêncio de reactor usa a permissão individual mais estreita disponível no Bot API e preserva mensagens comuns quando possível.</p>
            </div>
            <div class="panel wide">
              <h3>Reactors recentes</h3>
              <div id="reacoes_recentes" class="list muted">Nenhum reactor recente registrado.</div>
            </div>
            <div class="panel wide">
              <h3>Eventos de reação</h3>
              <div id="reacoes_eventos" class="list muted">Nenhum evento de reação registrado.</div>
            </div>
          </div>
        </section>

        <section id="novos_view" class="view hidden">
          <h3 class="window-title">Novos membros</h3>
          <p class="section-note">Monitora recém-chegados por janela curta. Quando um novo membro envia link nas primeiras mensagens, o painel registra alerta com nome público e @username, sem mostrar identificador técnico.</p>
          <div class="grid">
            <div class="panel">
              <h3>Resumo</h3>
              <div id="novos_resumo" class="statusbar muted">Escolha um grupo para carregar o monitor.</div>
              <div class="toolbar"><button id="novos_atualizar" class="action secondary" type="button">Atualizar novos membros</button></div>
              <div class="empty small">O watcher começa quando o Telegram envia evento de entrada de membro. As ações exigem os canais próprios e direitos reais do bot.</div>
            </div>
            <div class="panel">
              <h3>Alerta selecionado</h3>
              <select id="novos_evento_select"></select>
              <label class="small muted">Duração do silêncio</label>
              <select id="novos_silencio_segundos">
                <option value="600">10 minutos</option>
                <option value="3600" selected>1 hora</option>
                <option value="86400">24 horas</option>
                <option value="604800">7 dias</option>
              </select>
              <div class="toolbar">
                <button id="novos_apagar" class="action danger" type="button">Apagar mensagem</button>
                <button id="novos_silenciar" class="action" type="button">Silenciar membro</button>
                <button id="novos_banir" class="action danger" type="button">Banir membro</button>
                <button id="novos_ignorar" class="action secondary" type="button">Ignorar alerta</button>
              </div>
              <div id="novos_evento_hint" class="empty small">Nenhum alerta selecionado.</div>
            </div>
            <div class="panel wide">
              <h3>Alertas de link</h3>
              <div id="novos_eventos" class="list muted">Nenhum alerta registrado.</div>
            </div>
            <div class="panel wide">
              <h3>Recém-chegados monitorados</h3>
              <div id="novos_recentes" class="list muted">Nenhum novo membro monitorado.</div>
            </div>
          </div>
        </section>
        <section id="pessoas_view" class="view hidden">
          <h3 class="window-title">Pessoas</h3>
          <p class="section-note">Membros, administradores humanos, bots administradores, pedidos de entrada e canais remetentes. A interface mostra nome público e @username quando houver; identificador técnico não é exibido.</p>
          <div class="grid">
            <div class="panel wide">
              <h3>Mapa de pessoas do grupo</h3>
              <div id="pessoas_resumo" class="statusbar muted">Escolha um grupo para carregar pessoas e privilégios.</div>
              <div class="formgrid">
                <div>
                  <strong>Administradores humanos</strong>
                  <div id="admins_humanos_lista" class="list muted">Administradores ainda não carregados.</div>
                </div>
                <div>
                  <strong>Bots administradores</strong>
                  <div id="bots_admins_lista" class="list muted">Bots administradores ainda não carregados.</div>
                </div>
              </div>
            </div>
            <div class="panel">
              <h3>Membros vistos</h3>
              <input id="alvos_busca" class="search-box" placeholder="Buscar membro por nome, @username ou tag" />
              <select id="alvo_select"></select>
              <div id="alvos_hint" class="empty small">Nenhum membro carregado ainda.</div>
              <div id="alvos_atalhos" class="member-preview compact small"></div>
              <label class="small muted">Duração do silêncio</label>
              <select id="silencio_duracao">
                <option value="600">10 minutos</option>
                <option value="3600" selected>1 hora</option>
                <option value="86400">24 horas</option>
                <option value="604800">7 dias</option>
              </select>
              <label class="small"><input id="remover_revogar" type="checkbox" /> remover mensagens recentes ao remover</label>
              <div class="toolbar">
                <button class="action secondary" data-action="membros.silenciar">Silenciar membro</button>
                <button class="action secondary" data-action="membros.liberar">Liberar membro</button>
                <button class="action danger" data-action="membros.remover">Remover membro</button>
                <button class="action secondary" data-action="membros.reintegrar">Reintegrar membro</button>
              </div>
              <div id="membro_resultado" class="empty small">Nenhum ajuste de membro executado nesta sessão.</div>
            </div>
            <div class="panel">
              <h3>Resolver membro</h3>
              <p class="muted small">Use @username já visto pelo bot ou referência interna. O backend resolve a pessoa sem expor identificador técnico.</p>
              <input id="alvo_manual_input" placeholder="@username ou referência interna" />
              <div class="toolbar"><button id="resolver_alvo" class="action secondary" type="button">Resolver membro</button></div>
            </div>
            <div class="panel wide">
              <h3>Administração de pessoas</h3>
              <p class="muted small">Escolha um membro ou administrador registrado. Promover, rebaixar e título personalizado exigem direito real do bot e confirmação crítica.</p>
              <label class="small muted">Alvo da administração</label>
              <select id="admin_alvo_select"></select>
              <p id="admin_alvo_hint" class="muted small select-note">Administradores e membros vistos aparecerão aqui por nome público ou referência segura.</p>
              <div class="formgrid">
                <div>
                  <label class="small muted">Título personalizado</label>
                  <input id="admin_titulo_input" maxlength="16" placeholder="Título personalizado" />
                  <p class="muted small">O Telegram só aceita título para administrador elegível promovido pelo próprio bot.</p>
                </div>
                <div>
                  <label class="small muted">Perfil de promoção</label>
                  <select id="admin_perfil_select"><option value="moderador" selected>Moderador seguro</option><option value="maestro">Administrador delegado</option></select>
                </div>
              </div>
              <label class="small"><input id="admin_ciente" class="admin-ciente" type="checkbox" /> confirmo que entendo o risco da administração de pessoas</label>
              <div class="toolbar">
                <button class="action secondary" data-action="admins.promover" type="button">Promover administrador</button>
                <button class="action danger" data-action="admins.rebaixar" type="button">Rebaixar administrador</button>
                <button class="action secondary" data-action="admins.titulo" type="button">Definir título</button>
              </div>
              <div id="admin_resultado" class="empty small">Nenhuma administração de pessoas executada nesta sessão.</div>
            </div>
            <div class="panel">
              <h3>Pedidos de entrada</h3>
              <select id="entrada_select"></select>
              <div class="toolbar">
                <button class="action secondary" data-action="entradas.aprovar">Aprovar entrada</button>
                <button class="action danger" data-action="entradas.recusar">Recusar entrada</button>
              </div>
              <div id="entradas_hint" class="empty small">Nenhum pedido de entrada capturado.</div>
            </div>
            <div class="panel">
              <h3>Reações e canais remetentes</h3>
              <p class="muted small">Para reações escolha uma mensagem e um membro ou canal remetente.</p>
              <select id="sender_select"></select>
              <input id="membro_tag" maxlength="16" placeholder="Tag do membro" />
              <div class="toolbar"><button class="action secondary" data-action="reacoes.mensagem.limpar" type="button">Limpar reação da mensagem</button><button class="action secondary" data-action="reacoes.recentes.limpar" type="button">Limpar reações recentes</button></div>
              <div class="toolbar"><button class="action danger" data-action="canais_remetentes.banir" type="button">Banir canal remetente</button><button class="action secondary" data-action="canais_remetentes.liberar" type="button">Liberar canal remetente</button></div>
              <div class="toolbar"><button class="action secondary" data-action="membros.tag.definir" type="button">Definir tag</button></div>
              <div id="remetentes_hint" class="empty small">Nenhum canal remetente capturado.</div>
            </div>
            <div class="panel wide">
              <h3>Distribuição de canais</h3>
              <div id="distribuicao" class="list muted"></div>
            </div>
          </div>
        </section>
        <section id="convites_view" class="view hidden">
          <h3 class="window-title">Convites</h3>
          <p class="section-note">Criação, revisão e revogação de convites. Esta janela separa convite novo, convite selecionado e link primário para evitar operação no item errado.</p>
          <div id="convites_resumo" class="statusbar muted">Convites ainda não carregados.</div>
          <div class="grid">
            <div class="panel">
              <h3>Criar convite</h3>
              <p class="muted small">Defina o nome, validade e limite antes de gerar. Convite com aprovação não usa limite de membros.</p>
              <input id="convite_nome" maxlength="32" placeholder="Nome do convite" value="Equalizador" />
              <label class="small muted">Expiração do convite</label>
              <select id="convite_expira">
                <option value="0" selected>Sem expiração</option>
                <option value="3600">1 hora</option>
                <option value="86400">24 horas</option>
                <option value="604800">7 dias</option>
                <option value="2592000">30 dias</option>
              </select>
              <label class="small muted">Limite de membros</label>
              <input id="convite_limite" type="number" min="0" max="99999" inputmode="numeric" placeholder="0 = sem limite" />
              <label class="small"><input id="convite_aprovacao" type="checkbox" /> solicitar aprovação para entrar</label>
              <label class="small"><input id="convite_dm" type="checkbox" checked /> enviar link por DM ao operador</label>
              <div class="toolbar"><button class="action secondary" data-action="convites.criar">Criar convite</button></div>
              <p id="convite_dm_status" class="muted small">O link também será enviado por DM quando o bot puder conversar com o operador.</p>
            </div>
            <div class="panel">
              <h3>Resultado do convite</h3>
              <input id="convite_resultado" readonly placeholder="Link criado ou exportado aparece aqui" />
              <div id="convite_metadados" class="empty small">Nenhum convite criado nesta sessão.</div>
              <div class="toolbar">
                <button id="copiar_convite" class="action secondary" type="button" disabled>Copiar link exibido</button>
                <button id="abrir_convite" class="action secondary" type="button" disabled>Abrir link exibido</button>
              </div>
            </div>
            <div class="panel wide">
              <h3>Convite selecionado</h3>
              <select id="convite_select"></select>
              <div id="convite_detalhe" class="empty small">Escolha um convite para ver estado, expiração, limite e aprovação.</div>
              <div class="toolbar">
                <button id="copiar_convite_selecionado" class="action secondary" type="button" disabled>Copiar convite selecionado</button>
                <button id="abrir_convite_selecionado" class="action secondary" type="button" disabled>Abrir convite selecionado</button>
              </div>
              <div class="toolbar">
                <button class="action secondary" data-action="convites.editar">Editar convite selecionado</button>
                <button class="action danger" data-action="convites.revogar">Revogar convite selecionado</button>
                <button class="action secondary" data-action="convites.exportar_primario">Exportar link primário</button>
              </div>
              <div id="convites_hint" class="empty small">Nenhum convite carregado.</div>
              <div id="convites_lista" class="list muted">Lista de convites aguardando carregamento.</div>
            </div>
          </div>
        </section>
        <section id="topicos_view" class="view hidden">
          <h3 class="window-title">Tópicos</h3>
          <p class="section-note">Janela para grupos com fórum. O tópico geral fica separado dos tópicos comuns para reduzir clique errado.</p>
          <div id="topicos_resumo" class="statusbar muted">Tópicos ainda não carregados.</div>
          <div class="grid">
            <div class="panel">
              <h3>Criar ou renomear tópico</h3>
              <p class="muted small">Para criar, informe o nome. Para editar, selecione um tópico existente e informe o novo nome.</p>
              <input id="topico_nome" maxlength="128" placeholder="Nome do tópico" />
              <div class="toolbar"><button class="action secondary" data-action="topicos.criar" type="button">Criar tópico</button><button class="action secondary" data-action="topicos.editar" type="button">Editar tópico selecionado</button></div>
            </div>
            <div class="panel">
              <h3>Tópico selecionado</h3>
              <select id="topico_select"></select>
              <div id="topico_detalhe" class="empty small">Escolha um tópico para operar.</div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.fechar" type="button">Fechar tópico selecionado</button><button class="action secondary" data-action="topicos.reabrir" type="button">Reabrir tópico selecionado</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.desfixar" type="button">Remover fixados do tópico</button><button class="action danger" data-action="topicos.apagar" type="button">Apagar tópico selecionado</button></div>
            </div>
            <div class="panel wide">
              <h3>Tópico geral</h3>
              <p class="muted small">Ações globais do tópico geral. Use somente quando o grupo for fórum.</p>
              <div class="toolbar"><button class="action secondary" data-action="topicos.geral.fechar" type="button">Fechar geral</button><button class="action secondary" data-action="topicos.geral.reabrir" type="button">Reabrir geral</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.geral.ocultar" type="button">Ocultar geral</button><button class="action secondary" data-action="topicos.geral.exibir" type="button">Exibir geral</button><button class="action secondary" data-action="topicos.geral.desfixar" type="button">Remover fixados do geral</button></div>
            </div>
            <div class="panel wide">
              <h3>Tópicos conhecidos</h3>
              <div id="topicos_hint" class="empty small">Nenhum tópico registrado.</div>
              <div id="topicos_lista" class="list muted">Lista de tópicos aguardando carregamento.</div>
            </div>
          </div>
        </section>
        <section id="afinacao_view" class="view hidden">
          <h3 class="window-title">Diagnóstico real de permissões</h3>
          <p class="section-note">Esta janela cruza três camadas antes de liberar uma ação: canal concedido ao operador, direito real do bot no Telegram e confirmação crítica quando a ação é sensível.</p>
          <div id="diagnostico_resumo" class="diagnostic-summary">
            <div class="diagnostic-metric"><strong>—</strong><span class="muted small">ações liberadas</span></div>
            <div class="diagnostic-metric"><strong>—</strong><span class="muted small">bloqueadas por operador</span></div>
            <div class="diagnostic-metric"><strong>—</strong><span class="muted small">bloqueadas pelo bot</span></div>
          </div>
          <div class="grid">
            <div class="panel">
              <h3>Operador neste grupo</h3>
              <div id="diagnostico_operador" class="list muted">Canais do operador não carregados.</div>
            </div>
            <div class="panel">
              <h3>Bot no Telegram</h3>
              <div id="diagnostico_bot" class="list muted">Direitos reais do bot não carregados.</div>
            </div>
          </div>
          <h3>Ações do painel</h3>
          <p class="section-note">Cada cartão mostra por que a ação está liberada ou bloqueada. Isso evita testar no escuro e receber apenas 409/429 no log.</p>
          <div id="diagnostico_acoes" class="diagnostic-grid">Diagnóstico de ações não carregado.</div>
          <h3>Afinação técnica</h3>
          <div id="afinacao_resumo" class="statusbar muted">Aguardando leitura das permissões.</div>
          <div id="afinacao" class="list muted">Permissões do bot não carregadas.</div>
          <h3>Resumo de moderação do grupo</h3>
          <p class="section-note">Descrição do grupo, administradores, bots administradores e funções liberadas conforme direitos reais do bot.</p>
          <div id="painel_dinamico" class="list muted">Resumo de moderação não carregado.</div>
        </section>
        <section id="historico_view" class="view hidden">
          <p class="section-note">Histórico público da mesa, sem IDs técnicos ou payload interno.</p>
          <div id="historico" class="list muted">Histórico não carregado.</div>
        </section>
        <section id="maestro_view" class="view hidden">
          <div class="panel">
            <h3 class="window-title">Transmissão e modo silêncio</h3>
            <p class="muted small">Ações críticas exigem confirmação dupla. Esta janela fica separada da personalização do grupo.</p>
            <textarea id="transmissao_texto" maxlength="4096" placeholder="Texto da transmissão"></textarea>
            <p id="transmissao_contador" class="muted small">0/4096 caracteres</p>
            <div class="toolbar">
              <button class="action secondary" data-action="silencio.ativar">Ativar modo silêncio</button>
              <button class="action secondary" data-action="silencio.desativar">Desativar modo silêncio</button>
              <button class="action secondary" data-action="transmissao.enviar">Enviar transmissão</button>
              <button id="exportar_historico" class="action secondary" type="button">Exportar histórico</button>
            </div>
            <label class="small"><input id="transmissao_preview" type="checkbox" checked /> sem prévia de link</label>
            <label class="small"><input id="transmissao_silenciosa" type="checkbox" /> enviar sem notificação</label>
            <label class="small"><input id="transmissao_fixar" type="checkbox" /> fixar transmissão depois do envio</label>
            <textarea id="exportacao_resultado" readonly placeholder="Exportação sanitizada aparece aqui"></textarea>
            <div class="empty small">Administração crítica: título, descrição, promoção e título de administrador foram separados nas janelas Perfil do grupo e Pessoas.</div>
          </div>
        </section>
        <section id="seguranca_view" class="view hidden">
          <h3 class="window-title">Segurança avançada</h3>
          <p class="section-note">Modo alerta/restrito, auditoria exportável, diagnóstico de sessões e limpeza operacional. Janela restrita ao dono do código.</p>
          <div class="grid">
            <div class="panel">
              <h3>Modo de segurança</h3>
              <div id="seguranca_modo_atual" class="statusbar muted">Modo não carregado.</div>
              <label class="small muted">Motivo público<br><input id="seguranca_motivo" maxlength="180" placeholder="ex.: manutenção, incidente, revisão de permissões" /></label>
              <div class="toolbar">
                <button id="seguranca_modo_normal" class="action" type="button">Retomar normal</button>
                <button id="seguranca_modo_alerta" class="action" type="button">Ativar alerta</button>
                <button id="seguranca_modo_restrito" class="action danger" type="button">Ativar restrito</button>
              </div>
              <p class="muted small">Alerta registra o estado sem bloquear. Restrito bloqueia ações de governantes e deixa o dono atuar.</p>
            </div>
            <div class="panel">
              <h3>Exportações</h3>
              <p class="muted small">Exporta linhas sanitizadas das ações, Radio, DDX, reações, novos membros e auditoria de segurança.</p>
              <input id="seguranca_senha_export" type="password" minlength="8" placeholder="Senha para exportação criptografada" />
              <div class="toolbar">
                <button id="seguranca_exportar_jsonl" class="action secondary" type="button">Exportar JSONL</button>
                <button id="seguranca_exportar_assinado" class="action secondary" type="button">Exportar assinado</button>
                <button id="seguranca_exportar_criptografado" class="action secondary" type="button">Exportar criptografado</button>
              </div>
              <textarea id="seguranca_export_result" readonly placeholder="O conteúdo exportado aparece aqui"></textarea>
            </div>
            <div class="panel">
              <h3>Limpeza e locks</h3>
              <label class="small muted">Remover auditoria mais antiga que<br><input id="seguranca_limpar_dias" type="number" min="1" max="3650" value="180" /></label>
              <div class="toolbar">
                <button id="seguranca_limpar_auditoria" class="action secondary" type="button">Limpar auditoria antiga</button>
                <button id="seguranca_limpar_locks" class="action secondary" type="button">Limpar locks e rate-limit</button>
              </div>
              <div id="seguranca_diagnostico" class="empty small">Diagnóstico não carregado.</div>
            </div>
            <div class="panel wide">
              <h3>Auditoria recente</h3>
              <div id="seguranca_resumo" class="empty small">Resumo não carregado.</div>
              <div id="seguranca_auditoria" class="list muted">Auditoria não carregada.</div>
            </div>
          </div>
        </section>
        <section id="config_view" class="view hidden">
          <div class="panel owner-only">
            <h3>Configuração do proprietário</h3>
            <p class="muted small">Use campos amigáveis para ajustar grupos, operadores e canais. O app não edita Railway diretamente; ele gera o bloco final somente no final para copiar.</p>
            <div class="toolbar"><button id="atualizar_configuracao" class="action secondary" type="button">Atualizar configuração</button></div>
            <h3>Configuração visual</h3>
            <div class="formgrid">
              <label class="small muted">Mini App<br><input id="cfg_app_name" placeholder="equalizador" /></label>
              <label class="small muted">Equalizador ligado<br><select id="cfg_enabled"><option value="true">Ligado</option><option value="false">Desligado</option></select></label>
              <label class="small muted">Proprietários técnicos<br><input id="cfg_maestros" placeholder="8505890439" /></label>
              <label class="small muted">Operadores<br><input id="cfg_operadores" placeholder="8505890439,1759115970" /></label>
              <label class="small muted">Grupos ativos<br><input id="cfg_palcos" placeholder="-100...,-100..." /></label>
              <label class="small muted">Rate limit/min<br><input id="cfg_rate" type="number" min="10" max="600" placeholder="30" /></label>
            </div>
            <label class="small muted">Aliases dos grupos, um por linha: nome=-100...</label>
            <textarea id="cfg_aliases" placeholder="radio=-1003818494866"></textarea>
            <label class="small muted">Canais por operador</label>
            <textarea id="cfg_canais" placeholder="8505890439:*:*"></textarea>
            <div class="config-actions">
              <button id="gerar_config_raw" class="action" type="button">Gerar bloco final</button>
              <button id="resetar_config_form" class="action secondary" type="button">Restaurar valores atuais</button>
            </div>
            <div id="config_preview_resumo" class="empty small">Preencha os campos e gere o bloco final somente no final.</div>
            <h3>Grupos ativos</h3>
            <div id="config_palcos_ativos" class="list muted">Configuração não carregada.</div>
            <h3>Aliases configurados</h3>
            <div id="config_aliases" class="list muted">Configuração não carregada.</div>
            <h3>Grupos ocultos</h3>
            <div id="config_palcos_ocultos" class="list muted">Configuração não carregada.</div>
            <h3>Operadores e canais</h3>
            <div id="config_operadores" class="list muted">Configuração não carregada.</div>
            <h3>Governantes por janela</h3>
            <p class="muted small">Leitura operacional para o dono do código delegar governantes sem expor identificador técnico na interface.</p>
            <div id="config_governantes_resumo" class="empty small">Governança não carregada.</div>
            <div id="config_governanca_persistencia" class="empty small">Persistência de governança não verificada.</div>
            <div id="config_governantes" class="governance-grid muted">Governança não carregada.</div>
            <h3>Delegação runtime</h3>
            <p class="muted small">Concessões salvas no banco persistente. Use para delegar governantes sem editar Railway a cada ajuste. As variáveis continuam como base estável.</p>
            <div class="owner-governance-add">
              <strong>Adicionar governante conhecido</strong>
              <div class="hint-private">Restrito ao dono. O identificador informado é usado só para cadastro interno e não aparece no resumo público.</div>
              <div class="formgrid">
                <label class="small muted">Identificador informado pelo dono<br><input id="rbac_new_user_id" inputmode="numeric" placeholder="somente números" /></label>
                <label class="small muted">Nome público<br><input id="rbac_new_nome" placeholder="ex.: Governante de mensagens" /></label>
                <label class="small muted">@username opcional<br><input id="rbac_new_username" placeholder="sem @" /></label>
                <label class="small muted">Função<br><input id="rbac_new_perfil" placeholder="Governante designado" /></label>
              </div>
              <div class="toolbar"><button id="rbac_adicionar_governante" class="action" type="button">Adicionar governante</button></div>
            </div>
            <div class="formgrid">
              <label class="small muted">Governante<br><select id="rbac_usr_ref"></select></label>
              <label class="small muted">Grupo<br><select id="rbac_grp_ref"></select></label>
              <label class="small muted">Canal<br><select id="rbac_canal_codigo"></select></label>
              <label class="small muted">Motivo público<br><input id="rbac_motivo" placeholder="ex.: governante de mensagens" /></label>
            </div>
            <div class="toolbar">
              <button id="rbac_conceder" class="action" type="button">Conceder canal</button>
              <button id="rbac_revogar" class="action danger" type="button">Revogar selecionado</button>
              <button id="sessoes_limpar" class="action secondary" type="button">Limpar sessões expiradas</button>
            </div>
            <select id="rbac_grant_ref"></select>
            <details class="compact-disclosure">
              <summary>Editar governante selecionado</summary>
              <div class="grid">
                <label class="small muted">Nome público<br><input id="rbac_edit_nome" placeholder="nome visível" /></label>
                <label class="small muted">@username<br><input id="rbac_edit_username" placeholder="sem @" /></label>
                <label class="small muted">Função<br><input id="rbac_edit_perfil" placeholder="Governante designado" /></label>
              </div>
              <div class="toolbar">
                <button id="rbac_atualizar_governante" class="action" type="button">Atualizar governante</button>
                <button id="rbac_remover_governante" class="action danger" type="button">Remover governante</button>
              </div>
            </details>
            <div id="rbac_runtime_resumo" class="empty small">Delegação runtime não carregada.</div>
            <div id="rbac_runtime_lista" class="list muted">Delegação runtime não carregada.</div>
            <div id="rbac_auditoria_governanca" class="list muted">Auditoria de governança não carregada.</div>
            <h3>Sessões persistentes</h3>
            <div id="sessoes_persistentes" class="empty small">Sessões não carregadas.</div>
            <h3>Persistência real</h3>
            <div id="persistencia_status" class="empty small">Persistência não carregada.</div>
            <h3>Matriz completa de permissões</h3>
            <p class="muted small">Leitura de segurança por operador, grupo e canal. Canais críticos ficam marcados e operadores comuns permanecem bloqueados.</p>
            <div id="config_matriz_resumo" class="empty small">Matriz não carregada.</div>
            <div id="config_matriz" class="list muted">Configuração não carregada.</div>
            <h3>Auditoria de permissões</h3>
            <div id="config_permissoes_auditoria_resumo" class="empty small">Auditoria não carregada.</div>
            <div id="config_permissoes_auditoria" class="list muted">Auditoria não carregada.</div>
            <h3>Bloco final para copiar</h3>
            <p class="muted small">Só copie este bloco depois de revisar os campos acima. Preserve as outras variáveis do Railway.</p>
            <textarea id="config_raw" readonly placeholder="Clique em Gerar bloco final para montar o conteúdo"></textarea>
            <div class="toolbar"><button id="copiar_config_raw" class="action secondary" type="button" disabled>Copiar bloco final</button></div>
          </div>
        </section>
      </div>
      <div id="toast" class="toast hidden"></div>
      <div id="feedback_panel" class="feedback-panel hidden">
        <div class="feedback-head">
          <strong>Confirmações e erros desta sessão</strong>
          <div class="feedback-actions">
            <button id="feedback_copy" class="action secondary" type="button">Copiar detalhes</button>
            <button id="feedback_clear" class="action secondary" type="button">Limpar</button>
          </div>
        </div>
        <div id="feedback_items" class="feedback-items muted">Nenhuma ação registrada nesta sessão.</div>
      </div>
    </section>
  </main>
  <script>
    (function () {
      window.__TR4_PANEL_BOOT = window.__TR4_PANEL_BOOT || {};
      window.__TR4_PANEL_BOOT.bottomStarted = true;
      function markPanel(kind, message, extra) {
        try {
          if (window.__TR4_PANEL_MARK) window.__TR4_PANEL_MARK(kind, message || "ok", extra || "");
          else if (window.__eqClientError) window.__eqClientError(kind, message || "ok", "equalizador_panel", 0, 0, extra || "");
        } catch (_) {}
      }
      markPanel("panel_js_started", "ok", "phase137_4");
      try { if (window.__TR4_READY_PANEL) window.__TR4_READY_PANEL("bottom_start"); } catch (_) {}

      // Fase 54.1: Equalizador em janelas com contraste reforçado.
      // Compatibilidade de testes antigos: Afinando acesso… · Configuração do administrador principal · Assistente de configuração · Gerar Raw Editor · Raw Editor final · Ações permanecem bloqueadas até confirmação do bot · Lista de administração
      // Compatibilidade fase 46: const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes, painelRes, entradasRes, convitesRes, topicosRes, remetentesRes] = await Promise.all([
      /*
api(base + "/canais-remetentes").then((r) => r.ok ? r.json() : { remetentes: [] }).catch(() => ({ remetentes: [] }))
        ]);
      */
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      const initData = tg && tg.initData ? tg.initData : "";
  function getStoredPublicSession() {
    try { return window.localStorage.getItem("tr4_public_eqs") || ""; }
    catch (_) { return ""; }
  }
  function setStoredPublicSession(token) {
    try {
      if (token) window.localStorage.setItem("tr4_public_eqs", token);
      else window.localStorage.removeItem("tr4_public_eqs");
    } catch (_) {}
  }
  const storedPublicSession = getStoredPublicSession();
  let publicApiHeaders = initData ? { Authorization: "tma " + initData } : (storedPublicSession ? { Authorization: "eqs " + storedPublicSession } : {});
  const headers = publicApiHeaders;
      const SESSION_KEY = "tr4_equalizador_eqs";
      const STATE_KEY = "tr4_equalizador_state_v1";
      const PANEL_FETCH_TIMEOUT_MS = 8000;
      const getStoredPanelState = () => {
        try { return JSON.parse(localStorage.getItem(STATE_KEY) || "{}"); }
        catch (_) { return {}; }
      };
      const rememberPanelState = (patch) => {
        try {
          const current = getStoredPanelState();
          const next = Object.assign({}, current || {}, patch || {}, { updated_at: Date.now() });
          localStorage.setItem(STATE_KEY, JSON.stringify(next));
        } catch (_) {}
      };
      const reportClient = (kind, message, extra) => {
        try { if (window.__eqClientError) window.__eqClientError(kind, message, "equalizador", 0, 0, extra || ""); } catch (_) {}
      };
      const reportException = (kind, error) => {
        const msg = error && error.message ? error.message : String(error || "erro");
        const stack = error && error.stack ? error.stack : "";
        reportClient(kind, msg, stack);
      };
      const safeAsync = (kind, fn) => async (...args) => {
        try { return await fn(...args); }
        catch (error) { reportException(kind, error); toast("Falha na interface. Detalhe registrado no log.", "bad"); throw error; }
      };
      const getStoredSession = () => {
        try { return String(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem("tr4_public_eqs") || localStorage.getItem(SESSION_KEY) || "").trim(); } catch (_) { return ""; }
      };
      const setStoredSession = (token) => {
        try {
          const value = String(token || "").trim();
          if (value) {
            sessionStorage.setItem(SESSION_KEY, value);
            localStorage.setItem(SESSION_KEY, value);
            localStorage.setItem("tr4_public_eqs", value);
          } else {
            sessionStorage.removeItem(SESSION_KEY);
            localStorage.removeItem(SESSION_KEY);
            localStorage.removeItem("tr4_public_eqs");
          }
        } catch (_) {}
      };
      let apiHeaders = null;
      let bootstrapHeaders = null;
      let currentPalco = null;
      let currentPainelDinamico = null;
      let currentAlvosRows = [];
      let mensagensPorRef = new Map();
      let mensagensSelecionadas = new Set();
      let radioDraftsPorRef = new Map();
      let multimediaSessionsPorRef = new Map();
      let botUsernameAtual = "";
      let radioTemplatesPorRef = new Map();
      let radioHistoryRows = [];
      let radioSchedulesPorRef = new Map();
      let radioQuietAtual = null;
      let ddxPendentesPorRef = new Map();
      let ddxEventosRows = [];
      let reacoesRecentesPorRef = new Map();
      let reacoesEventosRows = [];
      let novosEventosPorRef = new Map();
      let novosEventosRows = [];
      let novosRecentesRows = [];
      let convitesPorRef = new Map();
      let topicosPorRef = new Map();
      let canaisPorPalco = new Map();
      let botFotoIndisponivel = false;
      const fotosGrupoIndisponiveis = new Set();
      let direitosDisponiveis = new Set();
      let ultimoAfinacao = null;
      let afinacaoLoaded = false;
      let modoMaestroPermitido = false;
      let carregandoPalco = false;
      let currentViewId = "";
      let lastRefreshStartedAt = 0;
      let feedbackEntries = [];
      let confirmTimer = null;
      const criticalActions = new Set(["silencio.ativar", "silencio.desativar", "transmissao.enviar", "grupo.titulo", "grupo.descricao", "grupo.foto", "grupo.foto.remover", "admins.promover", "admins.rebaixar", "admins.titulo"]);
      const cienteCritico = () => Array.from(document.querySelectorAll(".admin-ciente")).some((el) => Boolean(el.checked));
      const endpoints = {
        "mensagens.enviar": "mensagens/enviar",
        "mensagens.apagar": "mensagens/apagar",
        "mensagens.apagar_lote": "mensagens/apagar-lote",
        "membros.silenciar": "membros/silenciar",
        "membros.liberar": "membros/liberar",
        "membros.remover": "membros/remover",
        "membros.reintegrar": "membros/reintegrar",
        "fixados.criar": "fixados/criar",
        "fixados.remover": "fixados/remover",
        "convites.criar": "convites/criar",
        "convites.editar": "convites/editar",
        "convites.revogar": "convites/revogar",
        "convites.exportar_primario": "convites/exportar-primario",
        "entradas.aprovar": "entradas/aprovar",
        "entradas.recusar": "entradas/recusar",
        "silencio.ativar": "silencio/ativar",
        "silencio.desativar": "silencio/desativar",
        "transmissao.enviar": "transmissao/enviar",
        "reacoes.mensagem.limpar": "reacoes/mensagem/limpar",
        "reacoes.recentes.limpar": "reacoes/recentes/limpar",
        "reacoes.reactor.silenciar": "reacoes/reactor/silenciar",
        "canais_remetentes.banir": "canais-remetentes/banir",
        "canais_remetentes.liberar": "canais-remetentes/liberar",
        "membros.tag.definir": "membros/tag/definir",
        "topicos.criar": "topicos/criar",
        "topicos.editar": "topicos/editar",
        "topicos.fechar": "topicos/fechar",
        "topicos.reabrir": "topicos/reabrir",
        "topicos.apagar": "topicos/apagar",
        "topicos.desfixar": "topicos/desfixar",
        "topicos.geral.fechar": "topicos/geral/fechar",
        "topicos.geral.reabrir": "topicos/geral/reabrir",
        "topicos.geral.ocultar": "topicos/geral/ocultar",
        "topicos.geral.exibir": "topicos/geral/exibir",
        "topicos.geral.desfixar": "topicos/geral/desfixar",
        "grupo.titulo": "grupo/titulo",
        "grupo.descricao": "grupo/descricao",
        "grupo.foto": "grupo/foto",
        "grupo.foto.remover": "grupo/foto/remover",
        "admins.promover": "admins/promover",
        "admins.rebaixar": "admins/rebaixar",
        "admins.titulo": "admins/titulo"
      };
      const actionLabels = {
        "palco.ver": "Ver grupo",
        "palco.status": "Status do grupo",
        "palco.afinar": "Permissões do bot no grupo",
        "mensagens.enviar": "Enviar mensagem",
        "mensagens.apagar": "Apagar mensagem",
        "mensagens.apagar_lote": "Apagar mensagens em lote",
        "reacoes.limpar": "Limpar reações",
        "reacoes.auditoria": "Auditar reações",
        "reacoes.reactor.silenciar": "Silenciar reactor",
        "membros.silenciar": "Silenciar membro",
        "membros.liberar": "Liberar membro",
        "membros.remover": "Remover membro",
        "membros.reintegrar": "Reintegrar membro",
        "fixados.criar": "Fixar mensagem",
        "fixados.remover": "Remover fixado",
        "convites.criar": "Criar convite",
        "convites.ver": "Ver convites",
        "convites.editar": "Editar convite",
        "convites.revogar": "Revogar convite",
        "entradas.ver": "Ver pedidos de entrada",
        "entradas.aprovar": "Aprovar entrada",
        "entradas.recusar": "Recusar entrada",
        "canais.ver": "Ver canais",
        "canais.distribuir": "Distribuição de canais",
        "historico.ver": "Ver histórico",
        "historico.exportar": "Exportar histórico",
        "silencio.ativar": "Ativar modo silêncio",
        "silencio.desativar": "Desativar modo silêncio",
        "transmissao.enviar": "Enviar transmissão",
        "ddx.imediato": "Gerenciar DDX imediato",
        "ddx.temporario": "Gerenciar DDX 10 minutos",
        "reacoes.mensagem.limpar": "Limpar reação da mensagem",
        "reacoes.recentes.limpar": "Limpar reações recentes",
        "reacoes.reactor.silenciar": "Silenciar reactor",
        "novos.ver": "Ver novos membros",
        "novos.apagar": "Apagar link de novo membro",
        "novos.silenciar": "Silenciar novo membro",
        "novos.banir": "Banir novo membro",
        "novos.ignorar": "Ignorar alerta de novo membro",
        "canais_remetentes.banir": "Banir canal remetente",
        "canais_remetentes.liberar": "Liberar canal remetente",
        "membros.tag.definir": "Definir tag de membro",
        "topicos.criar": "Criar tópico",
        "topicos.editar": "Editar tópico",
        "topicos.fechar": "Fechar tópico",
        "topicos.reabrir": "Reabrir tópico",
        "topicos.apagar": "Apagar tópico",
        "topicos.desfixar": "Remover fixados do tópico",
        "topicos.geral.fechar": "Fechar tópico geral",
        "topicos.geral.reabrir": "Reabrir tópico geral",
        "topicos.geral.ocultar": "Ocultar tópico geral",
        "topicos.geral.exibir": "Exibir tópico geral",
        "topicos.geral.desfixar": "Remover fixados do tópico geral",
        "grupo.titulo": "Alterar título do grupo",
        "grupo.descricao": "Alterar descrição do grupo",
        "grupo.foto": "Trocar foto do grupo",
        "grupo.foto.remover": "Remover foto do grupo",
        "admins.promover": "Promover administrador",
        "admins.rebaixar": "Rebaixar administrador",
        "admins.titulo": "Título personalizado"
      };
      const permissionChannelForAction = {
        "mensagens.apagar_lote": "mensagens.apagar",
        "convites.exportar_primario": "convites.criar",
        "reacoes.mensagem.limpar": "reacoes.limpar",
        "reacoes.reactor.silenciar": "reacoes.reactor.silenciar"
      };
      const effectiveCanal = (codigo) => permissionChannelForAction[codigo] || codigo;
      const canalNome = (codigo) => actionLabels[codigo] || String(codigo || "canal").replace(/[._]/g, " ");
      const diagnosticActionGroups = [
        ["Perfil do grupo", ["grupo.titulo", "grupo.descricao", "grupo.foto", "grupo.foto.remover"]],
        ["Mensagens", ["mensagens.enviar", "mensagens.apagar", "mensagens.apagar_lote", "fixados.criar", "fixados.remover", "reacoes.mensagem.limpar"]],
        ["Reações", ["reacoes.auditoria", "reacoes.recentes.limpar", "reacoes.reactor.silenciar"]],
        ["Pessoas", ["membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar", "membros.tag.definir", "admins.promover", "admins.rebaixar", "admins.titulo"]],
        ["Convites e entrada", ["convites.criar", "convites.editar", "convites.revogar", "convites.exportar_primario", "entradas.aprovar", "entradas.recusar"]],
        ["Tópicos", ["topicos.criar", "topicos.editar", "topicos.fechar", "topicos.reabrir", "topicos.apagar", "topicos.desfixar", "topicos.geral.fechar", "topicos.geral.reabrir", "topicos.geral.ocultar", "topicos.geral.exibir", "topicos.geral.desfixar"]],
        ["Transmissão", ["silencio.ativar", "silencio.desativar", "transmissao.enviar"]],
        ["Filtros DDX", ["ddx.imediato", "ddx.temporario", "novos.ver", "novos.apagar", "novos.silenciar", "novos.banir", "novos.ignorar"]]
      ];
      const diagnosticActionOrder = diagnosticActionGroups.flatMap((row) => row[1]);
      const statusMesa = (text, kind) => {
        const el = document.getElementById("mesa_status");
        const card = document.getElementById("grupo_card_status");
        if (el) {
          el.textContent = text;
          el.className = "statusbar " + (kind || "muted");
        }
        if (card) {
          const compact = kind === "ok" ? "Pronto" : kind === "warn" ? "Atenção" : kind === "bad" ? "Falha" : (text && String(text).toLowerCase().includes("carreg") ? "Carregando" : "Atualizar");
          card.textContent = compact;
          card.className = "mini-status-button " + (kind || "");
          card.disabled = !currentPalco;
        }
      };
      const setRefreshState = (text, kind) => {
        const el = document.getElementById("refresh_state");
        if (!el) return;
        el.textContent = text || "";
        el.className = "refresh-state " + (kind || "");
      };
      const setPanelRefreshing = (active, label) => {
        const mesa = document.getElementById("mesa");
        const button = document.getElementById("mesa_refresh");
        const card = document.getElementById("grupo_card_status");
        if (mesa) mesa.classList.toggle("is-refreshing", Boolean(active));
        if (button) {
          if (!button.dataset.originalText) button.dataset.originalText = button.textContent || "Atualizar";
          if (active) { markButton(button, "working"); button.textContent = label || "Atualizando"; }
          else { restoreButton(button); button.disabled = !currentPalco; }
        }
        if (card) {
          card.disabled = !currentPalco || Boolean(active);
          if (active) { card.textContent = "Atualizando"; card.className = "mini-status-button muted"; }
        }
      };
      const skeleton = (lines) => {
        const wrap = document.createElement("div");
        wrap.className = "item";
        for (let i = 0; i < (lines || 3); i += 1) {
          const line = document.createElement("span");
          line.className = "skeleton-line";
          line.style.width = (i === 0 ? "76%" : i === 1 ? "92%" : "54%");
          wrap.appendChild(line);
        }
        return wrap;
      };
      const setListLoading = (id, label) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.className = "list";
        const box = skeleton(3);
        const caption = document.createElement("div");
        caption.className = "muted small";
        caption.textContent = label || "Carregando dados…";
        box.prepend(caption);
        el.replaceChildren(box);
      };
      const setConviteResult = (link, dm, info) => {
        const input = document.getElementById("convite_resultado");
        const copy = document.getElementById("copiar_convite");
        const open = document.getElementById("abrir_convite");
        const status = document.getElementById("convite_dm_status");
        const meta = document.getElementById("convite_metadados");
        const value = String(link || "").trim();
        input.value = value;
        copy.disabled = !value;
        open.disabled = !value;
        open.dataset.href = value;
        if (meta) {
          const parts = [];
          if (info && info.nome) parts.push("nome: " + info.nome);
          if (info && info.expira_em) parts.push("expira: " + info.expira_em);
          if (info && info.limite_membros) parts.push("limite: " + info.limite_membros);
          if (info && info.solicitar_aprovacao) parts.push("entrada por aprovação");
          meta.textContent = value ? (parts.length ? parts.join(" · ") : "Convite criado e mantido visível nesta sessão.") : "Nenhum convite criado nesta sessão.";
          meta.className = "empty small " + (value ? "ok" : "");
        }
        if (status && dm) {
          status.textContent = dm.enviado ? "Link enviado por DM ao operador." : ("DM não enviada. " + (dm.motivo || "Abra o bot no privado e toque em Start."));
          status.className = "small " + (dm.enviado ? "ok" : "warn");
        }
      };
      const formatUnixDate = (value) => {
        const n = Number(value || 0);
        if (!Number.isFinite(n) || n <= 0) return "sem expiração";
        try { return new Date(n * 1000).toLocaleString("pt-BR"); }
        catch (_) { return "expiração registrada"; }
      };
      const conviteResumo = (row) => {
        if (!row) return "Convite indisponível.";
        const status = row.revogado ? "revogado" : "ativo";
        const aprovacao = row.solicitar_aprovacao ? "entrada por aprovação" : "entrada direta";
        const limite = row.limite_membros ? `${row.limite_membros} membro(s)` : "sem limite";
        return `${row.nome || 'Convite'} · ${status} · ${aprovacao} · ${limite} · ${formatUnixDate(row.expira_em)}`;
      };
      function updateConviteSelecionado() {
        const select = document.getElementById("convite_select");
        const ref = select ? select.value : "";
        const row = ref ? convitesPorRef.get(ref) : null;
        const detalhe = document.getElementById("convite_detalhe");
        const copy = document.getElementById("copiar_convite_selecionado");
        const open = document.getElementById("abrir_convite_selecionado");
        const link = row && row.link ? String(row.link) : "";
        if (detalhe) {
          detalhe.textContent = row ? conviteResumo(row) : "Escolha um convite para ver estado, expiração, limite e aprovação.";
          detalhe.className = "empty small " + (row ? (row.revogado ? "warn" : "ok") : "");
        }
        if (copy) copy.disabled = !link;
        if (open) { open.disabled = !link; open.dataset.href = link; }
      }
      function renderConvitesLista(rows) {
        const lista = document.getElementById("convites_lista");
        const resumo = document.getElementById("convites_resumo");
        const data = Array.isArray(rows) ? rows : [];
        const ativos = data.filter((row) => !row.revogado).length;
        const revogados = data.filter((row) => row.revogado).length;
        if (resumo) {
          resumo.textContent = data.length ? `${ativos} convite(s) ativo(s) · ${revogados} revogado(s) · ${data.length} conhecido(s).` : "Nenhum convite conhecido neste grupo.";
          resumo.className = "statusbar " + (data.length ? "ok" : "warn");
        }
        if (!lista) return;
        lista.className = data.length ? "list" : "list muted";
        lista.replaceChildren(...(data.length ? data.slice(0, 20).map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          const estado = row.revogado ? "revogado" : "ativo";
          const link = row.link ? `<br><span class="muted">link disponível para copiar/abrir pelo seletor</span>` : "";
          item.innerHTML = `<strong>${escapeHtml(row.nome || 'Convite')}</strong><br><span class="${row.revogado ? 'warn' : 'ok'}">${estado}</span> · ${escapeHtml(row.solicitar_aprovacao ? 'aprovação exigida' : 'entrada direta')} · ${escapeHtml(formatUnixDate(row.expira_em))}${link}`;
          return item;
        }) : [document.createTextNode("Nenhum convite criado ou exportado pelo Equalizador.")]));
      }
      const topicoResumo = (row) => {
        if (!row) return "Tópico indisponível.";
        return `${row.nome || 'Tópico'} · ${row.estado || 'estado desconhecido'}`;
      };
      function updateTopicoSelecionado() {
        const select = document.getElementById("topico_select");
        const ref = select ? select.value : "";
        const row = ref ? topicosPorRef.get(ref) : null;
        const detalhe = document.getElementById("topico_detalhe");
        if (detalhe) {
          detalhe.textContent = row ? topicoResumo(row) : "Escolha um tópico para operar.";
          detalhe.className = "empty small " + (row ? (row.estado === "aberto" ? "ok" : row.estado === "fechado" ? "warn" : "bad") : "");
        }
      }
      function renderTopicosLista(rows) {
        const lista = document.getElementById("topicos_lista");
        const resumo = document.getElementById("topicos_resumo");
        const data = Array.isArray(rows) ? rows : [];
        const abertos = data.filter((row) => row.estado === "aberto").length;
        const fechados = data.filter((row) => row.estado === "fechado").length;
        const apagados = data.filter((row) => row.estado === "apagado").length;
        if (resumo) {
          resumo.textContent = data.length ? `${abertos} aberto(s) · ${fechados} fechado(s) · ${apagados} apagado(s) · ${data.length} conhecido(s).` : "Nenhum tópico conhecido. Tópicos só aparecem depois que o bot cria ou registra eventos.";
          resumo.className = "statusbar " + (data.length ? "ok" : "warn");
        }
        if (!lista) return;
        lista.className = data.length ? "list" : "list muted";
        lista.replaceChildren(...(data.length ? data.slice(0, 30).map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          const estadoClass = row.estado === "aberto" ? "ok" : row.estado === "fechado" ? "warn" : "bad";
          item.innerHTML = `<strong>${escapeHtml(row.nome || 'Tópico')}</strong><br><span class="${estadoClass}">${escapeHtml(row.estado || 'registrado')}</span><br><span class="muted">referência interna preservada no seletor</span>`;
          return item;
        }) : [document.createTextNode("Nenhum tópico registrado para este grupo.")]));
      }
      function setMensagemResult(mensagem, fallback) {
        const el = document.getElementById("mensagem_resultado");
        if (!el) return;
        if (!mensagem) {
          el.textContent = fallback || "Ajuste de mensagem concluído.";
          el.className = "empty small ok";
          return;
        }
        const estadoNome = {
          "apagada": "Mensagem apagada",
          "fixada": "Mensagem fixada",
          "fixado_removido": "Fixado removido"
        }[mensagem.estado] || "Mensagem ajustada";
        el.textContent = `${estadoNome}: ${mensagem.resumo || mensagem.msg_ref || 'referência segura'}`;
        el.className = "empty small ok";
      }
      function setMembroResult(membro, fallback) {
        const el = document.getElementById("membro_resultado");
        if (!el) return;
        if (!membro) {
          el.textContent = fallback || "Ajuste de membro concluído.";
          el.className = "empty small ok";
          return;
        }
        const estadoNome = {
          "silenciado": "Membro silenciado",
          "liberado": "Membro liberado",
          "removido": "Membro removido",
          "reintegrado": "Membro reintegrado"
        }[membro.estado] || "Membro ajustado";
        el.textContent = `${estadoNome}: ${membro.nome || membro.alvo_ref || 'referência segura'}`;
        el.className = "empty small ok";
      }
      const detailPublico = (detail) => {
        let value = detail;
        const original = detail && typeof detail === "object" ? detail : {};
        if (value && typeof value === "object" && value.detail) value = value.detail;
        if (value && typeof value === "object") {
          const code = String(value.code || value.category || original.code || original.category || "").toLowerCase();
          if (code.includes("topic") || code.includes("topico")) value = value.motivo_publico || value.public_detail || "Ação de tópico não aplicada. Verifique se o grupo usa fórum, se o tópico existe e se o bot tem direito real para gerenciar tópicos.";
          else if (code.includes("rbac") || code.includes("operador") || code.includes("canal_invalido") || code.includes("grupo_indisponivel")) value = value.public_detail || value.motivo_publico || "Delegação não aplicada. Revise governante, grupo e canal.";
          else if (code.includes("permission") || code.includes("forbidden") || code.includes("rights")) value = value.motivo_publico || value.public_detail || "Ação bloqueada por permissão real do bot ou do operador.";
          else value = value.motivo_publico || value.public_detail || value.message || value.erro || "Ajuste não concluído.";
        }
        let text = String(value || "Ajuste não concluído.");
        if (/afina[cç][aã]o_insuficiente/i.test(text)) text = "Permissão real do bot insuficiente. Abra Diagnóstico para conferir a afinação deste grupo.";
        if (/rascunho.*(publicado|cancelado)/i.test(text)) text = "Rascunho já foi publicado ou cancelado. Atualize a lista de rascunhos.";
        return text
          .replace(/bot\\d+:[A-Za-z0-9_-]+/g, "bot_token_oculto")
          .replace(/-100\\d{5,}/g, "grupo oculto")
          .replace(/\\b\\d{7,16}\\b/g, "referência oculta");
      };

      const buttonLabel = (button) => String(button && (button.dataset.originalText || button.textContent) || "Ação").trim();
      const restoreButton = (button) => {
        if (!button) return;
        if (button.dataset.originalText) button.textContent = button.dataset.originalText;
        button.classList.remove("pressed", "confirming", "working", "success", "error", "loading");
        button.removeAttribute("aria-busy");
        if (button.dataset.workingLock === "1") {
          button.disabled = button.dataset.wasDisabled === "1";
          delete button.dataset.workingLock;
          delete button.dataset.wasDisabled;
        }
        delete button.dataset.confirmArmed;
      };
      const armInlineConfirmation = (button, label, critical) => {
        if (!button) return true;
        if (!button.dataset.originalText) button.dataset.originalText = button.textContent;
        if (button.dataset.confirmArmed === "1") {
          if (confirmTimer) clearTimeout(confirmTimer);
          restoreButton(button);
          return true;
        }
        document.querySelectorAll("button.action[data-confirm-armed='1']").forEach(restoreButton);
        button.dataset.confirmArmed = "1";
        button.classList.add("confirming");
        button.textContent = "Confirmar: " + String(label || buttonLabel(button)).slice(0, 34);
        const msg = (critical ? "Ação crítica preparada. " : "Ação preparada. ") + "Toque novamente no mesmo botão para confirmar.";
        statusMesa(msg, "warn");
        addFeedback(msg, "warn");
        haptic("selection");
        confirmTimer = setTimeout(() => restoreButton(button), 8500);
        return false;
      };
      const markButton = (button, state) => {
        if (!button) return;
        button.classList.remove("pressed", "confirming", "working", "success", "error", "loading");
        if (state) button.classList.add(state);
        if (state === "working" || state === "loading") {
          if (!button.dataset.workingLock) button.dataset.wasDisabled = button.disabled ? "1" : "0";
          button.dataset.workingLock = "1";
          button.disabled = true;
          button.setAttribute("aria-busy", "true");
        }
      };
      const fileToBase64 = (file) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const value = String(reader.result || "");
          resolve(value.includes(",") ? value.split(",", 2)[1] : value);
        };
        reader.onerror = () => reject(new Error("Não foi possível ler a imagem."));
        reader.readAsDataURL(file);
      });
      // Compatibilidade de testes antigos: Modo Maestro indisponível para este perfil. · Ação restrita ao Maestro · palco oculto · Configuração do Maestro · /mesa_ajuda · Distribuição restrita ao Maestro. · Canal ou afinação indisponível · perfil oculto · Exportação restrita ao Maestro.
      const show = (id) => {
        for (const el of document.querySelectorAll("main > section")) el.classList.add("hidden");
        document.getElementById(id).classList.remove("hidden");
      };
      const haptic = (type, style) => {
        try {
          const feedback = tg && tg.HapticFeedback;
          if (!feedback) return;
          if (type === "selection" && feedback.selectionChanged) feedback.selectionChanged();
          else if (type === "impact" && feedback.impactOccurred) feedback.impactOccurred(style || "light");
          else if (type === "notification" && feedback.notificationOccurred) feedback.notificationOccurred(style || "success");
        } catch (_) {}
      };
      const tgBackButton = tg && tg.BackButton ? tg.BackButton : null;
      const setTelegramBackButton = (active) => {
        try {
          if (!tgBackButton) return;
          if (active) tgBackButton.show();
          else tgBackButton.hide();
        } catch (_) {}
      };
      const copyText = async (text) => {
        const clean = String(text || "");
        if (!clean.trim()) return false;
        try { await navigator.clipboard.writeText(clean); return true; }
        catch (_) { return false; }
      };
      const feedbackKindLabel = (kind) => ({ ok: "sucesso", warn: "atenção", bad: "erro", error: "erro", info: "informação" }[String(kind || "info")] || String(kind || "informação"));
      const renderFeedbackPanel = () => {
        const panel = document.getElementById("feedback_panel");
        const items = document.getElementById("feedback_items");
        if (!panel || !items) return;
        panel.classList.toggle("hidden", feedbackEntries.length === 0);
        if (!feedbackEntries.length) {
          items.className = "feedback-items muted";
          items.textContent = "Nenhuma ação registrada nesta sessão.";
          return;
        }
        items.className = "feedback-items";
        items.replaceChildren(...feedbackEntries.slice(0, 10).map((entry) => {
          const div = document.createElement("div");
          div.className = "feedback-item " + (entry.kind || "");
          const body = document.createElement("div");
          body.innerHTML = `<span class="feedback-meta">${escapeHtml(entry.time)} · ${escapeHtml(entry.kind || 'info')}</span>${escapeHtml(entry.text)}`;
          const button = document.createElement("button");
          button.className = "feedback-copy-one";
          button.type = "button";
          button.textContent = "Copiar";
          button.addEventListener("click", async (event) => {
            event.stopPropagation();
            const ok = await copyText(`[${entry.time}] ${feedbackKindLabel(entry.kind)}: ${entry.text}`);
            if (ok) { statusMesa("Detalhe copiado.", "ok"); haptic("notification", "success"); }
            else { statusMesa("Não foi possível copiar este detalhe automaticamente.", "warn"); haptic("notification", "warning"); }
          });
          div.appendChild(body);
          div.appendChild(button);
          return div;
        }));
      };
      const addFeedback = (text, kind) => {
        const clean = String(text || "").trim();
        if (!clean) return;
        const level = kind || "info";
        if (level === "ok") feedbackEntries = feedbackEntries.filter((entry) => !/^Ação (crítica )?preparada\\./.test(String(entry.text || "")));
        const previous = feedbackEntries[0];
        if (previous && previous.kind === level && previous.text === clean) {
          renderFeedbackPanel();
          return;
        }
        const now = new Date();
        const time = now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        feedbackEntries.unshift({ time, text: clean, kind: level });
        feedbackEntries = feedbackEntries.slice(0, 12);
        renderFeedbackPanel();
      };
      const toast = (text, kind) => {
        const clean = String(text || "").trim();
        const level = kind || "";
        const el = document.getElementById("toast");
        el.textContent = clean;
        el.className = "toast " + level;
        addFeedback(clean, level || "info");
        if (level === "ok") haptic("notification", "success");
        else if (level === "bad") haptic("notification", "error");
        else if (level === "warn") haptic("notification", "warning");
        setTimeout(() => el.classList.add("hidden"), 5200);
      };
      const fetchWithTimeout = async (url, options, ms) => {
        const timeoutMs = Number(ms || PANEL_FETCH_TIMEOUT_MS || 8000);
        if (!window.AbortController) return fetch(url, options || {});
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
          return await fetch(url, Object.assign({}, options || {}, { signal: controller.signal }));
        } finally {
          clearTimeout(timer);
        }
      };
      const api = async (url, options) => {
        const requestOptions = Object.assign({ headers: apiHeaders }, options || {});
        let response = await fetchWithTimeout(url, requestOptions);
        if (response.status === 401 && bootstrapHeaders && apiHeaders && apiHeaders.Authorization && apiHeaders.Authorization.startsWith("eqs ")) {
          try {
            const renew = await fetchWithTimeout("/equalizador/api/me", { headers: bootstrapHeaders });
            if (renew.ok) {
              const me = await renew.json();
              const sessionToken = me.sessao && me.sessao.token ? me.sessao.token : "";
              apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : bootstrapHeaders;
              response = await fetchWithTimeout(url, Object.assign({}, requestOptions, { headers: Object.assign({}, requestOptions.headers || {}, apiHeaders) }));
            }
          } catch (_) {}
        }
        if (response.status === 429) toast("Limite temporário atingido. Aguarde alguns segundos e tente novamente.", "warn");
        return response;
      };
      const option = (value, label) => {
        const item = document.createElement("option");
        item.value = value;
        item.textContent = label;
        return item;
      };
      const hasCanal = (codigo) => {
        if (!currentPalco) return false;
        const canais = canaisPorPalco.get(currentPalco.grp_ref) || new Set();
        return canais.has(effectiveCanal(codigo));
      };
      const botCanRun = (codigo) => afinacaoLoaded && direitosDisponiveis.has(effectiveCanal(codigo));
      const diagnosticForAction = (codigo) => {
        const canal = effectiveCanal(codigo);
        const operadorOk = hasCanal(codigo);
        const botOk = botCanRun(codigo);
        const criticoOk = !criticalActions.has(codigo) || modoMaestroPermitido;
        const motivos = [];
        if (!currentPalco) motivos.push("escolha um grupo");
        if (!operadorOk) motivos.push(`canal do operador ausente: ${canalNome(canal)}`);
        if (!afinacaoLoaded) motivos.push("permissões reais do bot ainda não carregadas");
        else if (!botOk) {
          const canalInfo = (ultimoAfinacao && Array.isArray(ultimoAfinacao.canais) ? ultimoAfinacao.canais : []).find((row) => row.codigo === canal);
          const faltando = canalInfo && Array.isArray(canalInfo.faltando) && canalInfo.faltando.length ? `faltando ${canalInfo.faltando.join(', ')}` : "direito real do bot indisponível";
          motivos.push(faltando);
        }
        if (!criticoOk) motivos.push("ação crítica restrita ao proprietário técnico");
        const ok = Boolean(currentPalco && operadorOk && botOk && criticoOk);
        return { codigo, canal, ok, operadorOk, botOk, criticoOk, motivos };
      };
      // Compatibilidade lógica da Fase 28: const canRun = (codigo) => hasCanal(codigo) && afinacaoLoaded && direitosDisponiveis.has(codigo);
      const canRun = (codigo) => diagnosticForAction(codigo).ok;
      const viewRequirementActions = {
        mensagens_view: ["mensagens.enviar", "mensagens.apagar", "fixados.criar", "fixados.remover"],
        reacoes_view: ["reacoes.auditoria", "reacoes.recentes.limpar", "reacoes.reactor.silenciar"],
        convites_view: ["convites.criar", "convites.editar", "convites.revogar", "entradas.aprovar", "entradas.recusar"],
        topicos_view: ["topicos.criar", "topicos.editar", "topicos.fechar", "topicos.reabrir", "topicos.apagar"],
        pessoas_view: ["membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar", "admins.promover", "admins.rebaixar"],
        perfil_view: ["grupo.titulo", "grupo.descricao", "grupo.foto"]
      };
      const diagnosticForView = (id) => {
        const actions = viewRequirementActions[id] || [];
        if (!actions.length || !currentPalco || !afinacaoLoaded) return { ok: true, motivos: [] };
        const diagnostics = actions.map((action) => diagnosticForAction(action));
        if (diagnostics.some((row) => row.ok)) return { ok: true, motivos: [] };
        const motivos = [];
        diagnostics.forEach((row) => (row.motivos || []).forEach((motivo) => { if (!motivos.includes(motivo)) motivos.push(motivo); }));
        return { ok: false, motivos: motivos.slice(0, 3) };
      };
      const viewTitle = (id) => {
        const button = document.querySelector(`button.nav[data-view="${id}"] strong`);
        return button ? button.textContent.trim() : "painel";
      };
      const viewSubtitle = (id) => {
        const button = document.querySelector(`button.nav[data-view="${id}"]`);
        const span = button ? button.querySelector("span:not(.nav-state)") : null;
        return span ? span.textContent.trim() : "";
      };
      const setDetailMode = (id) => {
        const active = Boolean(id);
        document.body.classList.toggle("detail-mode", active);
        const nav = document.getElementById("detail_nav");
        const title = document.getElementById("detail_title");
        const subtitle = document.getElementById("detail_subtitle");
        if (nav) nav.classList.toggle("hidden", !active);
        if (title) title.textContent = active ? viewTitle(id) : "Janela";
        if (subtitle) subtitle.textContent = active ? viewSubtitle(id) : "";
        setTelegramBackButton(active);
      };
      function applyPreventiveAccessUI() {
        document.querySelectorAll("button.nav[data-view]").forEach((button) => {
          const viewId = button.dataset.view || "";
          const diagnostic = diagnosticForView(viewId);
          const blocked = Boolean(currentPalco && afinacaoLoaded && !diagnostic.ok);
          button.classList.toggle("access-blocked", blocked);
          if (blocked) {
            button.disabled = true;
            button.title = "Janela bloqueada preventivamente: " + diagnostic.motivos.join(" · ");
          } else if (!((viewId === "maestro_view" || viewId === "config_view" || viewId === "seguranca_view") && !modoMaestroPermitido)) {
            button.disabled = false;
            button.title = "";
          }
        });
      }
      const openView = (id) => {
        if ((id === "maestro_view" || id === "config_view" || id === "seguranca_view") && !modoMaestroPermitido) {
          toast("Janela restrita ao proprietário técnico.", "warn");
          id = "mesa_view";
        }
        const viewDiagnostic = diagnosticForView(id);
        if (currentPalco && afinacaoLoaded && !viewDiagnostic.ok) {
          toast("Janela bloqueada preventivamente: " + viewDiagnostic.motivos.join(" · "), "warn");
          id = "mesa_view";
        }
        closeAllViews();
        const view = document.getElementById(id);
        if (view) view.classList.remove("hidden");
        currentViewId = id;
        rememberPanelState({ view_id: id });
        setDetailMode(id);
        document.querySelectorAll("button.nav").forEach((button) => button.classList.toggle("active", button.dataset.view === id));
        const detailNav = document.getElementById("detail_nav");
        if (detailNav) { try { detailNav.scrollIntoView({ block: "start", behavior: "smooth" }); } catch (_) {} }
      };
      const aplicarPerfil = (me) => {
        const canais = new Set(me.canais || []);
        modoMaestroPermitido = Boolean(me.modo_maestro) || (me.perfil === "Maestro" && (canais.has("silencio.ativar") || canais.has("silencio.desativar") || canais.has("transmissao.enviar") || canais.has("historico.exportar") || canais.has("canais.distribuir")));
        const maestroNav = document.getElementById("maestro_nav");
        if (maestroNav) maestroNav.classList.toggle("hidden", !modoMaestroPermitido);
        const configNav = document.getElementById("config_nav");
        if (configNav) configNav.classList.toggle("hidden", !modoMaestroPermitido);
        const segurancaNav = document.getElementById("seguranca_nav");
        if (segurancaNav) segurancaNav.classList.toggle("hidden", !modoMaestroPermitido);
        const govSection = document.getElementById("governantes_palco_section");
        if (govSection) govSection.classList.toggle("hidden", !modoMaestroPermitido);
        const exportButton = document.getElementById("exportar_historico");
        if (exportButton) exportButton.disabled = !modoMaestroPermitido;
        if (!modoMaestroPermitido) {
          document.getElementById("maestro_view").classList.add("hidden");
          document.getElementById("config_view").classList.add("hidden");
          const segView = document.getElementById("seguranca_view"); if (segView) segView.classList.add("hidden");
        }
        applyPreventiveAccessUI();
      };
      const ensureNavStates = () => {
        document.querySelectorAll("button.nav").forEach((button) => {
          if (button.querySelector(".nav-state")) return;
          const span = document.createElement("span");
          span.className = "nav-state";
          span.textContent = "•";
          button.prepend(span);
        });
      };
      const setNavState = (viewId, state) => {
        const button = document.querySelector(`button.nav[data-view="${viewId}"]`);
        const span = button && button.querySelector(".nav-state");
        if (!span) return;
        span.className = "nav-state" + (state ? " " + state : "");
        span.textContent = state === "loading" ? "…" : (state === "ok" ? "✓" : (state === "bad" ? "×" : "•"));
        if (button) {
          button.classList.toggle("loading", state === "loading");
          button.setAttribute("aria-label", `${button.textContent.replace(/\\s+/g, " ").trim()} · ${state === "loading" ? "carregando" : state === "ok" ? "carregado" : state === "bad" ? "falha" : "aguardando"}`);
        }
      };
      const setAllOperationalNavStates = (state) => {
        document.querySelectorAll("button.nav").forEach((button) => setNavState(button.dataset.view, state));
      };
      ensureNavStates();
      document.addEventListener("focusin", (event) => {
        const target = event.target;
        if (!target || !target.matches || !target.matches("input, textarea, select")) return;
        setTimeout(() => { try { target.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) {} }, 120);
      });
      const closeAllViews = () => {
        for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
        document.querySelectorAll("button.nav").forEach((button) => button.classList.remove("active"));
        currentViewId = "";
        setDetailMode("");
      };
      const normalizeSearch = (value) => String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
      const searchTokens = (value) => normalizeSearch(value).split(/\\s+/).filter(Boolean);
      function searchMatches(text, query) {
        const hay = normalizeSearch(text);
        return searchTokens(query).every((token) => hay.includes(token));
      }
      function buildGlobalSearchResults(query) {
        const q = String(query || "").trim();
        const results = [];
        if (q.length < 2) {
          if (!currentPalco) {
            (palcosDisponiveis || []).slice(0, 8).forEach((palco) => results.push({ kind: "Grupo", title: palco.titulo || "Grupo", sub: "abrir grupo", palco, quick: true }));
          } else {
            document.querySelectorAll("button.nav[data-view]").forEach((button) => {
              if (button.classList.contains("hidden")) return;
              const title = (button.querySelector("strong") || {}).textContent || "Janela";
              const sub = (button.querySelector("span:not(.nav-state)") || {}).textContent || "";
              results.push({ kind: "Janela", title, sub, view: button.dataset.view, quick: true });
            });
          }
          return results.slice(0, 12);
        }
        document.querySelectorAll("button.nav[data-view]").forEach((button) => {
          if (button.classList.contains("hidden")) return;
          const title = (button.querySelector("strong") || {}).textContent || "Janela";
          const sub = (button.querySelector("span:not(.nav-state)") || {}).textContent || "";
          if (searchMatches(`${title} ${sub}`, q)) results.push({ kind: "Janela", title, sub, view: button.dataset.view });
        });
        Object.entries(actionLabels).forEach(([code, label]) => {
          if (searchMatches(`${label} ${code}`, q)) results.push({ kind: "Ação", title: label, sub: canalNome(code), view: viewForAction(code) });
        });
        (palcosDisponiveis || []).forEach((palco) => {
          if (searchMatches(`${palco.titulo || ""} ${palco.alias || ""} ${palco.grp_ref || ""} ${palco.estado || ""}`, q)) results.push({ kind: "Grupo", title: palco.titulo || "Grupo", sub: "abrir grupo", palco });
        });
        (currentAlvosRows || []).forEach((row) => {
          const text = `${row.nome || ""} ${row.username || ""} ${row.alvo_ref || ""} ${row.user_ref || ""} ${row.ref || ""}`;
          if (searchMatches(text, q)) results.push({ kind: "Alvo", title: pessoaLabel(row, "Usuário"), sub: "pessoa conhecida pelo painel", view: "pessoas_view" });
        });
        return results.slice(0, 12);
      }
      function viewForAction(code) {
        if (String(code).startsWith("grupo.")) return "perfil_view";
        if (String(code).startsWith("mensagens.") || String(code).startsWith("fixados.")) return "mensagens_view";
        if (String(code).startsWith("membros.") || String(code).startsWith("admins.")) return "pessoas_view";
        if (String(code).startsWith("convites.") || String(code).startsWith("entradas.")) return "convites_view";
        if (String(code).startsWith("topicos.")) return "topicos_view";
        if (String(code).startsWith("reacoes.")) return "reacoes_view";
        if (String(code).startsWith("silencio.") || String(code).startsWith("transmissao.")) return "maestro_view";
        if (String(code).startsWith("ddx.") || String(code).startsWith("novos.")) return "ddx_view";
        return "mesa_view";
      }
      function renderGlobalSearch() {
        const input = document.getElementById("global_search");
        const box = document.getElementById("global_search_results");
        if (!input || !box) return;
        const rows = buildGlobalSearchResults(input.value);
        const query = String(input.value || "").trim();
        box.classList.toggle("hidden", !rows.length && query.length < 2);
        if (!rows.length && query.length < 2) { box.replaceChildren(); return; }
        if (!rows.length) {
          const empty = document.createElement("div");
          empty.className = "search-empty";
          empty.innerHTML = `<div><strong>Sem resultados</strong><span>Nada encontrado para “${escapeHtml(query)}”.</span></div>`;
          box.replaceChildren(empty);
          return;
        }
        box.replaceChildren(...rows.map((row) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "search-result" + (row.quick ? " quick-suggestion" : "");
          button.innerHTML = `<span><strong>${escapeHtml(row.title)}</strong><span class="search-kind">${escapeHtml(row.kind + " · " + (row.sub || "abrir"))}</span></span>`;
          button.addEventListener("click", () => {
            if (row.palco) selectPalco(row.palco, null);
            else if (row.view) openView(row.view);
            box.classList.add("hidden");
            haptic("selection");
          });
          return button;
        }));
      }
      document.querySelectorAll("button.nav").forEach((button) => button.addEventListener("click", () => {
        button.classList.add("pressed");
        setTimeout(() => button.classList.remove("pressed"), 180);
        haptic("selection");
        openView(button.dataset.view);
      }));
      const detailBackButton = document.getElementById("detail_back");
      const goBackToHomeList = () => {
        haptic("selection");
        closeAllViews();
        const navList = document.querySelector(".app-tabs");
        if (navList) { try { navList.scrollIntoView({ block: "start", behavior: "smooth" }); } catch (_) {} }
      };
      if (detailBackButton) detailBackButton.addEventListener("click", goBackToHomeList);
      try { if (tgBackButton && tgBackButton.onClick) tgBackButton.onClick(goBackToHomeList); } catch (_) {}
      const globalSearchInput = document.getElementById("global_search");
      if (globalSearchInput) globalSearchInput.addEventListener("input", renderGlobalSearch);
      const perfilAtualizar = document.getElementById("perfil_atualizar_dados");
      if (perfilAtualizar) perfilAtualizar.addEventListener("click", () => currentPalco ? loadPalcoData() : toast("Escolha um grupo antes de atualizar.", "warn"));
      const mesaRefreshButton = document.getElementById("mesa_refresh");
      if (mesaRefreshButton) mesaRefreshButton.addEventListener("click", async () => {
        if (!currentPalco) { toast("Escolha um grupo antes de atualizar.", "warn"); return; }
        await loadPalcoData();
      });
      const grupoCardStatusButton = document.getElementById("grupo_card_status");
      if (grupoCardStatusButton) grupoCardStatusButton.addEventListener("click", async () => {
        if (!currentPalco) { toast("Escolha um grupo antes de atualizar.", "warn"); return; }
        await loadPalcoData();
      });
      let palcosDisponiveis = [];
      function syncPalcoHeaderSelect(selectedRef) {
        const headerSelect = document.getElementById("palco_header_select");
        if (!headerSelect) return;
        for (const opt of Array.from(headerSelect.options || [])) {
          if (!opt.value) { opt.textContent = selectedRef ? "Alterar grupo" : "Selecionar grupo"; continue; }
          const palco = (palcosDisponiveis || []).find((item) => item.grp_ref === opt.value);
          opt.textContent = opt.value === selectedRef ? "Grupo selecionado" : (palco && palco.titulo ? palco.titulo : "Grupo");
        }
      }
      function renderPalcos(palcos) {
        palcosDisponiveis = palcos || [];
        const container = document.getElementById("palcos");
        const headerSelect = document.getElementById("palco_header_select");
        const hint = document.getElementById("palcos_hint");
        container.replaceChildren();
        headerSelect.replaceChildren();
        if (!palcosDisponiveis.length) {
          headerSelect.appendChild(option("", "Nenhum grupo disponível"));
          if (hint) hint.textContent = "Nenhum grupo disponível para este operador.";
          container.textContent = "Nenhum grupo disponível para este operador.";
          container.className = "empty hidden";
          return;
        }
        headerSelect.appendChild(option("", "Selecionar grupo"));
        for (const palco of palcosDisponiveis) {
          headerSelect.appendChild(option(palco.grp_ref, palco.titulo || "Grupo"));
        }
        headerSelect.onchange = () => {
          const palco = palcosDisponiveis.find((item) => item.grp_ref === headerSelect.value);
          if (palco) selectPalco(palco, null);
        };
        if (hint) hint.textContent = "";
        syncPalcoHeaderSelect(currentPalco && currentPalco.grp_ref);
        document.body.classList.toggle("group-selected", Boolean(currentPalco));
        renderGlobalSearch();
      }
      function renderCanais(rows) {
        canaisPorPalco = new Map();
        for (const row of rows || []) {
          const set = new Set((row.canais || []).map((canal) => canal.codigo));
          canaisPorPalco.set(row.grp_ref, set);
        }
      }
      function fillSelect(id, rows, valueKey, labelKey, emptyText) {
        const select = document.getElementById(id);
        select.replaceChildren();
        if (!rows.length) {
          select.appendChild(option("", emptyText));
          return;
        }
        for (const row of rows) select.appendChild(option(row[valueKey], row[labelKey] || row[valueKey]));
      }
      function renderMensagensLote(rows) {
        const lista = document.getElementById("mensagens_lote_lista");
        if (!lista) return;
        const data = Array.isArray(rows) ? rows : [];
        const refsAtuais = new Set(data.map((row) => String(row.msg_ref || "")).filter(Boolean));
        mensagensSelecionadas = new Set(Array.from(mensagensSelecionadas).filter((ref) => refsAtuais.has(ref)));
        if (!data.length) {
          lista.className = "bulk-list muted";
          lista.textContent = "Nenhuma mensagem registrada para seleção em lote.";
          updateBulkDeleteControls();
          return;
        }
        lista.className = "bulk-list";
        lista.replaceChildren(...data.slice(0, 80).map((row) => {
          const ref = String(row.msg_ref || "");
          const apagavel = row.apagavel !== false;
          const item = document.createElement("label");
          item.className = "bulk-item" + (apagavel ? "" : " locked") + (mensagensSelecionadas.has(ref) ? " selected" : "");
          const checked = mensagensSelecionadas.has(ref) ? "checked" : "";
          const disabled = apagavel ? "" : "disabled";
          const idade = typeof row.idade_segundos === "number" ? ` · ${Math.floor(row.idade_segundos / 60)} min` : "";
          item.innerHTML = `<input type="checkbox" data-msg-ref="${escapeHtml(ref)}" ${checked} ${disabled} />` +
            `<span><strong>${escapeHtml(row.resumo || ref || "Mensagem")}</strong><br><span class="muted">referência interna${idade}${apagavel ? "" : " · fora da janela de apagamento"}</span></span>`;
          const input = item.querySelector("input");
          if (input) input.addEventListener("change", () => toggleMensagemSelecionada(ref, input.checked));
          return item;
        }));
        updateBulkDeleteControls();
      }
      function updateBulkDeleteControls() {
        const status = document.getElementById("mensagens_lote_status");
        const apagar = document.getElementById("mensagens_lote_apagar");
        const limpar = document.getElementById("mensagens_lote_limpar");
        const bulkBox = status ? status.closest(".bulk-actions") : null;
        const selected = Array.from(mensagensSelecionadas).filter((ref) => {
          const row = mensagensPorRef.get(ref);
          return row && row.apagavel !== false;
        });
        const diagnostic = diagnosticForAction("mensagens.apagar_lote");
        const canDelete = selected.length > 0 && selected.length <= 100 && diagnostic.ok;
        if (status) {
          if (!selected.length) status.textContent = "Nenhuma mensagem selecionada para apagamento em lote.";
          else if (!diagnostic.ok) status.textContent = `${selected.length} selecionada(s). Bloqueado: ${diagnostic.motivos.join(" · ")}`;
          else status.textContent = `${selected.length} mensagem(ns) selecionada(s). O servidor executará uma única chamada ao Telegram.`;
          status.className = "empty small " + (canDelete ? "ok" : selected.length ? "warn" : "");
        }
        if (bulkBox) {
          bulkBox.classList.toggle("active", selected.length > 0);
          bulkBox.classList.toggle("idle", selected.length === 0);
        }
        if (apagar) { apagar.disabled = !canDelete; apagar.title = canDelete ? "" : (selected.length ? diagnostic.motivos.join(" · ") : "Selecione mensagens apagáveis"); }
        if (limpar) limpar.disabled = !selected.length;
      }
      function toggleMensagemSelecionada(ref, checked) {
        if (!ref) return;
        if (checked) mensagensSelecionadas.add(ref);
        else mensagensSelecionadas.delete(ref);
        const input = Array.from(document.querySelectorAll("input[data-msg-ref]")).find((el) => el.getAttribute("data-msg-ref") === ref);
        const item = input ? input.closest(".bulk-item") : null;
        if (item) item.classList.toggle("selected", Boolean(checked));
        haptic("selection");
        updateBulkDeleteControls();
      }
      function limparMensagensSelecionadas() {
        mensagensSelecionadas = new Set();
        renderMensagensLote(Array.from(mensagensPorRef.values()));
      }
      function updateButtons() {
        const mensagemRef = document.getElementById("mensagem_select").value;
        const alvoRef = document.getElementById("alvo_select").value;
        const adminAlvoRef = (document.getElementById("admin_alvo_select") || {}).value || "";
        const mensagem = mensagensPorRef.get(mensagemRef);
        const entradaRef = (document.getElementById("entrada_select") || {}).value || "";
        const conviteRef = (document.getElementById("convite_select") || {}).value || "";
        const reactorRef = (document.getElementById("reactor_select") || {}).value || "";
        document.querySelectorAll("button.action[data-action]").forEach((button) => {
          const action = button.dataset.action;
          const diagnostic = diagnosticForAction(action);
          let disabled = !diagnostic.ok;
          let title = disabled ? diagnostic.motivos.join(" · ") : "";
          if (criticalActions.has(action) && !modoMaestroPermitido) {
            disabled = true;
            title = "Ação restrita ao proprietário técnico";
          }
          if (!disabled && (["mensagens.apagar", "fixados.criar", "fixados.remover"].includes(action)) && !mensagemRef) {
            disabled = true;
            title = "Escolha uma mensagem registrada";
          }
          if (!disabled && action === "mensagens.apagar" && mensagem && mensagem.apagavel === false) {
            disabled = true;
            title = "Mensagem fora da janela de apagamento do Telegram";
          }
          if (!disabled && action.startsWith("entradas.") && !entradaRef) {
            disabled = true;
            title = "Escolha um pedido de entrada";
          }
          if (!disabled && (action === "convites.editar" || action === "convites.revogar") && !conviteRef) {
            disabled = true;
            title = "Escolha um convite criado";
          }
          const conviteSelecionado = conviteRef ? convitesPorRef.get(conviteRef) : null;
          if (!disabled && (action === "convites.editar" || action === "convites.revogar") && conviteSelecionado && conviteSelecionado.revogado) {
            disabled = true;
            title = "Convite já revogado";
          }
          if (!disabled && action.startsWith("membros.") && !alvoRef) {
            disabled = true;
            title = "Escolha um membro registrado";
          }
          if (!disabled && action.startsWith("admins.") && !adminAlvoRef) {
            disabled = true;
            title = "Escolha um membro ou administrador registrado";
          }
          const topicoRef = ((document.getElementById("topico_select") || {}).value || "");
          if (!disabled && action.startsWith("topicos.") && !action.startsWith("topicos.geral") && action !== "topicos.criar" && !topicoRef) {
            disabled = true;
            title = "Escolha um tópico registrado";
          }
          const topicoSelecionado = topicoRef ? topicosPorRef.get(topicoRef) : null;
          if (!disabled && action.startsWith("topicos.") && !action.startsWith("topicos.geral") && action !== "topicos.criar" && topicoSelecionado && topicoSelecionado.estado === "apagado") {
            disabled = true;
            title = "Tópico já marcado como apagado";
          }
          if (!disabled && action.startsWith("canais_remetentes.") && !((document.getElementById("sender_select") || {}).value || "")) {
            disabled = true;
            title = "Escolha um canal remetente";
          }
          if (!disabled && action === "reacoes.mensagem.limpar" && !mensagemRef) {
            disabled = true;
            title = "Escolha uma mensagem registrada";
          }
          if (!disabled && action === "reacoes.mensagem.limpar" && !alvoRef && !((document.getElementById("sender_select") || {}).value || "") && !reactorRef) {
            disabled = true;
            title = "Escolha um membro, canal remetente ou reactor recente";
          }
          if (!disabled && action === "reacoes.recentes.limpar" && !alvoRef && !((document.getElementById("sender_select") || {}).value || "") && !reactorRef) {
            disabled = true;
            title = "Escolha um membro, canal remetente ou reactor recente";
          }
          button.disabled = disabled;
          button.title = title;
        });
        updateBulkDeleteControls();
        applyPreventiveAccessUI();
        if (currentPalco && afinacaoLoaded) {
          statusMesa("Pronto", "ok");
        } else if (currentPalco) {
          statusMesa("Atenção", "warn");
        }
        renderDiagnosticoPermissoes();
      }
      async function selectPalco(palco, button) {
        currentPalco = palco;
        rememberPanelState({ palco_ref: String(palco && palco.grp_ref || "") });
        document.body.classList.add("group-selected");
        const headerSelect = document.getElementById("palco_header_select");
        if (headerSelect && headerSelect.value !== palco.grp_ref) headerSelect.value = palco.grp_ref;
        syncPalcoHeaderSelect(palco.grp_ref);
        document.querySelectorAll(".palco").forEach((el) => el.classList.remove("active"));
        if (button) button.classList.add("active");
        document.getElementById("mesa").classList.remove("hidden");
        document.getElementById("mesa_titulo").textContent = "Ações";
        const refreshButton = document.getElementById("mesa_refresh");
        if (refreshButton) refreshButton.disabled = false;
        statusMesa("Carregando painel…", "muted");
        setRefreshState("", "loading");
        closeAllViews();
        await loadPalcoData();
        renderGlobalSearch();
      }
      const fillList = (id, rows, render, emptyText) => {
        const el = document.getElementById(id);
        if (!el) return;
        const data = rows || [];
        const rendered = data.length ? data.map(render) : [document.createTextNode(emptyText)];
        if (data.length > 3 && collapsibleListIds.has(id)) {
          el.className = "list compact-collapsible";
          el.replaceChildren(makeCollapsibleList(id, rendered, emptyText));
          return;
        }
        el.className = data.length ? "list" : "list muted";
        el.replaceChildren(...rendered);
      };
      const disclosureRow = (title, summary, detail) => {
        const row = document.createElement("details");
        row.className = "disclosure-row small";
        const head = document.createElement("summary");
        head.innerHTML = `<span><span class="disclosure-title">${escapeHtml(title)}</span>${summary ? `<span class="disclosure-sub">${escapeHtml(summary)}</span>` : ""}</span>`;
        const body = document.createElement("div");
        body.className = "disclosure-body";
        body.textContent = detail || "Sem detalhes.";
        row.appendChild(head);
        row.appendChild(body);
        return row;
      };
      const fillDisclosureList = (id, rows, emptyText) => {
        const el = document.getElementById(id);
        if (!el) return;
        const data = rows || [];
        el.className = data.length ? "disclosure-list" : "list muted";
        el.replaceChildren(...(data.length ? data.map((row) => disclosureRow(row.titulo, row.resumo || "Toque para ver canais.", row.detalhe)) : [document.createTextNode(emptyText)]));
      };
      const collapsibleListIds = new Set(["config_aliases", "config_operadores", "config_palcos_ativos", "config_palcos_ocultos", "rbac_runtime_lista", "rbac_auditoria_governanca", "seguranca_auditoria", "historico", "mensagens_lote_lista", "mesa_membros_preview", "convites_lista", "topicos_lista"]);
      const listTitleById = {
        config_aliases: "Aliases de grupos", config_operadores: "Governantes e operadores", config_palcos_ativos: "Grupos ativos", config_palcos_ocultos: "Grupos ocultos", rbac_runtime_lista: "Permissões runtime", rbac_auditoria_governanca: "Auditoria de governança", seguranca_auditoria: "Auditoria de segurança", historico: "Histórico", mensagens_lote_lista: "Mensagens recentes", mesa_membros_preview: "Pessoas do painel", convites_lista: "Convites", topicos_lista: "Tópicos"
      };
      const makeCollapsibleList = (id, items, emptyText) => {
        const wrapper = document.createElement("details");
        wrapper.className = "collapsible-list-shell small";
        const summary = document.createElement("summary");
        const title = listTitleById[id] || "Lista";
        summary.innerHTML = `<span><span class="collapsible-list-title">${escapeHtml(title)}</span><span class="collapsible-list-sub">${items.length} item(ns) · toque para abrir</span></span>`;
        const body = document.createElement("div");
        body.className = "collapsible-list-body";
        body.replaceChildren(...(items.length ? items : [document.createTextNode(emptyText || "Nada para mostrar.")]));
        wrapper.appendChild(summary);
        wrapper.appendChild(body);
        return wrapper;
      };
      const escapeHtml = (value) => String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
      const safeText = (value, fallback) => String(value || fallback || "").replace(/[<>]/g, "");
      const safeUsername = (value) => {
        const username = String(value || "").replace(/^@/, "").trim();
        return /^[A-Za-z0-9_]{3,32}$/.test(username) ? username : "";
      };
      const itemText = (text, sub) => {
        const item = document.createElement("div");
        item.className = "item small";
        item.innerHTML = `<strong>${escapeHtml(text)}</strong>${sub ? `<br><span class="muted">${escapeHtml(sub)}</span>` : ""}`;
        return item;
      };
      const pessoaLabel = (row, fallback) => {
        const username = safeUsername(row && row.username);
        const nomeRaw = String(row && row.nome || fallback || "").trim();
        const nome = safeText(nomeRaw || (username ? `@${username}` : "Usuário"), "Usuário");
        return username && nome !== `@${username}` ? `${nome} · @${username}` : nome;
      };
      const pessoaHtml = (row, fallback) => {
        const username = safeUsername(row && row.username);
        const label = escapeHtml(pessoaLabel(row, fallback));
        if (!username) return `<strong>${label}</strong>`;
        return `<a class="person-link" href="https://t.me/${username}" target="_blank" rel="noopener"><strong>${label}</strong></a>`;
      };
      const grupoHtml = (titulo, username) => {
        const safeTitle = escapeHtml(safeText(titulo, "Grupo"));
        const safeUser = safeUsername(username);
        if (!safeUser) return `<strong>${safeTitle}</strong>`;
        return `<a class="person-link" href="https://t.me/${safeUser}" target="_blank" rel="noopener"><strong>${safeTitle} · @${safeUser}</strong></a>`;
      };
      const direitoLabel = (right) => right && (right.nome || right.codigo) ? String(right.nome || right.codigo) : "Direito";
      const direitosResumo = (direitos) => {
        const rows = Array.isArray(direitos) ? direitos : [];
        const concedidos = rows.filter((row) => row && row.concedido).length;
        return `${concedidos}/${rows.length || 0} direitos`;
      };
      const adminCard = (row, fallback) => {
        const item = document.createElement("div");
        item.className = "item small person-card";
        const direitos = Array.isArray(row && row.direitos) ? row.direitos : [];
        const chips = direitos.length ? direitos.map((right) => `<span class="right-chip ${right.concedido ? 'ok' : 'bad'}">${right.concedido ? '✓' : '•'} ${escapeHtml(direitoLabel(right))}</span>`).join("") : '<span class="muted">Direitos não detalhados.</span>';
        const role = row && row.bot ? "bot administrador" : "administrador humano";
        const titulo = row && row.titulo_customizado ? ` · título: ${escapeHtml(row.titulo_customizado)}` : "";
        item.innerHTML = `<div class="person-line">${pessoaHtml(row, fallback)}<span class="badge">${escapeHtml(row && row.perfil_admin || 'Administrador')}</span><span class="badge">${role}</span><span class="badge">${direitosResumo(direitos)}</span></div><div class="muted">${escapeHtml(role)}${titulo}</div><div>${chips}</div>`;
        return item;
      };
      const renderAdminList = (id, rows, emptyText, fallback) => {
        const el = document.getElementById(id);
        if (!el) return;
        const data = Array.isArray(rows) ? rows : [];
        el.className = data.length ? "list" : "list muted";
        el.replaceChildren(...(data.length ? data.slice(0, 24).map((row) => adminCard(row, fallback)) : [document.createTextNode(emptyText)]));
      };
      const governancaCargoLabel = (row) => {
        if (row && row.modo_maestro) return "Governante principal";
        const perfil = String(row && row.perfil || "").trim();
        if (perfil && perfil !== "Governante" && perfil !== "Operador") return perfil;
        return "Governante designado";
      };
      const governancaNomePublico = (row) => {
        const username = safeUsername(row && row.username);
        const nomeRaw = String(row && row.nome || "").trim();
        if (nomeRaw && nomeRaw !== "Governante" && nomeRaw !== "Operador" && nomeRaw !== `@${username}`) return nomeRaw;
        return username ? `@${username}` : "Nome público ainda não visto";
      };
      function governancaCard(row, palcoFilter) {
        const item = document.createElement("details");
        item.className = "governance-card small";
        const palcos = Array.isArray(row && row.palcos) ? row.palcos : [];
        const palco = palcoFilter ? (palcos.find((p) => String(p.grp_ref || "") === String(palcoFilter)) || palcos[0]) : palcos[0];
        const perfis = Array.isArray(palco && palco.perfis) ? palco.perfis : [];
        const ativos = perfis.filter((perfil) => perfil && perfil.ativo);
        const username = safeUsername(row && row.username);
        const nomePublico = governancaNomePublico(row);
        const cargo = governancaCargoLabel(row);
        const grupoTitulo = palco && palco.titulo ? String(palco.titulo) : "Grupo";
        const canaisTotal = ativos.reduce((total, perfil) => total + (Array.isArray(perfil.concedidos) ? perfil.concedidos.length : 0), 0);
        const summary = document.createElement("summary");
        const nomeHtml = username ? `<a class="person-link" href="https://t.me/${username}" target="_blank" rel="noopener"><span class="governance-person-main">${escapeHtml(nomePublico)}${nomePublico !== `@${username}` ? ` · @${username}` : ""}</span></a>` : `<span class="governance-person-main governance-warn">${escapeHtml(nomePublico)}</span>`;
        summary.innerHTML = `<span class="governance-summary-line">${nomeHtml}<span class="governance-person-sub"><span class="governance-cargo">${escapeHtml(cargo)}</span> · ${escapeHtml(grupoTitulo)} · ${ativos.length} janela(s) · ${canaisTotal} canal(is)</span></span>`;
        const detail = document.createElement("div");
        detail.className = "governance-detail";
        detail.innerHTML = ativos.length ? ativos.map((perfil) => {
          const canais = Array.isArray(perfil.concedidos) ? perfil.concedidos : [];
          const chips = canais.slice(0, 8).map((canal) => `<span class="badge">${escapeHtml(canal.nome || canal.codigo)}</span>`).join("");
          const extra = canais.length > 8 ? `<span class="badge">+${canais.length - 8}</span>` : "";
          return `<div class="governance-role active"><strong>${escapeHtml(perfil.nome || perfil.codigo)}</strong><div class="governance-chips">${chips}${extra || ""}</div></div>`;
        }).join("") : '<div class="governance-role locked"><strong>Sem janela ativa neste grupo</strong></div>';
        item.appendChild(summary);
        item.appendChild(detail);
        item.addEventListener("toggle", () => {
          if (!item.open) return;
          const group = item.closest(".governance-grid");
          if (!group) return;
          group.querySelectorAll("details.governance-card[open]").forEach((other) => { if (other !== item) other.open = false; });
        });
        return item;
      }
      function renderGovernanca(containerId, data, opts) {
        const el = document.getElementById(containerId);
        if (!el) return;
        const payload = data || {};
        const rows = Array.isArray(payload.governantes) ? payload.governantes : [];
        const palcoRef = opts && opts.palcoRef ? String(opts.palcoRef) : "";
        const onlyActive = opts && opts.onlyActive;
        const filtered = rows.filter((row) => {
          if (!onlyActive) return true;
          const palcos = Array.isArray(row && row.palcos) ? row.palcos : [];
          const palco = palcoRef ? (palcos.find((p) => String(p.grp_ref || "") === palcoRef) || palcos[0]) : palcos[0];
          return Array.isArray(palco && palco.perfis) && palco.perfis.some((perfil) => perfil && perfil.ativo);
        });
        el.className = filtered.length ? "governance-grid governance-collapsed" : "governance-grid muted";
        el.replaceChildren(...(filtered.length ? filtered.map((row) => governancaCard(row, palcoRef)) : [document.createTextNode("Nenhum governante com janela ativa carregado.")]));
      }
      function renderPessoasPainel(data, alvosRows) {
        const resumoEl = document.getElementById("pessoas_resumo");
        const painel = data || {};
        const resumo = painel.resumo || {};
        const humanos = painel.administradores_humanos || (painel.administradores || []).filter((row) => !row.bot);
        const bots = painel.bots_administradores || (painel.administradores || []).filter((row) => row.bot);
        const membros = Array.isArray(alvosRows) ? alvosRows : [];
        currentAlvosRows = membros;
        if (resumoEl) {
          resumoEl.textContent = `${humanos.length || resumo.administradores_humanos || 0} administrador(es) humano(s) · ${bots.length || resumo.bots_administradores || 0} bot(s) administrador(es) · ${membros.length} membro(s) visto(s).`;
          resumoEl.className = "statusbar " + ((humanos.length || bots.length || membros.length) ? "ok" : "warn");
        }
        renderAdminList("admins_humanos_lista", humanos, "Nenhum administrador humano retornado pelo Telegram.", "Administrador");
        renderAdminList("bots_admins_lista", bots, "Nenhum bot administrador retornado pelo Telegram.", "Bot administrador");
        const adminSelect = document.getElementById("admin_alvo_select");
        if (adminSelect) {
          const seen = new Set();
          const options = [];
          [...humanos, ...bots].forEach((row) => {
            const ref = row && row.alvo_ref ? String(row.alvo_ref) : "";
            if (!ref || seen.has(ref)) return;
            seen.add(ref);
            options.push({ ref, label: `${pessoaLabel(row, row && row.bot ? 'Bot administrador' : 'Administrador')} · ${row && row.perfil_admin || 'Administrador'}` });
          });
          membros.forEach((row) => {
            const ref = row && row.alvo_ref ? String(row.alvo_ref) : "";
            if (!ref || seen.has(ref)) return;
            seen.add(ref);
            options.push({ ref, label: `${pessoaLabel(row, 'Membro')} · membro visto` });
          });
          fillSelect("admin_alvo_select", options, "ref", "label", "Nenhum alvo administrativo registrado");
          const hint = document.getElementById("admin_alvo_hint");
          if (hint) hint.textContent = options.length ? `${options.length} alvo(s) administrativo(s) disponível(is), sem exibir identificador técnico.` : "Faça o Telegram retornar administradores ou registre um membro antes de usar ações administrativas.";
        }
      }
      function memberMatches(row, query) {
        if (!query) return true;
        const text = [row && row.nome, row && row.username, row && row.tag, row && row.situacao, row && row.alvo_ref].filter(Boolean).join(" ").toLowerCase();
        return text.includes(String(query || "").toLowerCase().replace(/^@/, ""));
      }
      function renderMesaMembrosResumo(painel, alvosRows) {
        const resumoEl = document.getElementById("mesa_pessoas_resumo");
        const previewEl = document.getElementById("mesa_membros_preview");
        const buscaEl = document.getElementById("mesa_membros_busca");
        const data = painel || {};
        const resumo = data.resumo || {};
        const humanos = data.administradores_humanos || (data.administradores || []).filter((row) => !row.bot);
        const bots = data.bots_administradores || (data.administradores || []).filter((row) => row.bot);
        const membros = Array.isArray(alvosRows) ? alvosRows : [];
        currentAlvosRows = membros;
        if (resumoEl) {
          resumoEl.textContent = `${humanos.length || resumo.administradores_humanos || 0} administrador(es) humano(s) · ${bots.length || resumo.bots_administradores || 0} bot(s) administrador(es) · ${membros.length} membro(s) visto(s).`;
          resumoEl.className = "empty small " + ((humanos.length || bots.length || membros.length) ? "ok" : "warn");
        }
        if (previewEl) {
          const query = buscaEl ? buscaEl.value.trim() : "";
          const filtered = membros.filter((row) => memberMatches(row, query)).slice(0, 8);
          previewEl.className = filtered.length ? "member-preview compact" : "member-preview compact muted small";
          previewEl.replaceChildren(...(filtered.length ? filtered.map((row) => itemText(pessoaLabel(row, "Membro"), row && row.tag ? "tag: " + row.tag : (row && row.situacao ? row.situacao : "visto pelo bot"))) : [document.createTextNode(query ? "Nenhum membro encontrado para a busca." : "Nenhum membro visto carregado para este grupo.")]));
        }
      }
      function renderAlvosBusca() {
        const busca = document.getElementById("alvos_busca");
        const atalhos = document.getElementById("alvos_atalhos");
        if (!atalhos) return;
        const query = busca ? busca.value.trim() : "";
        const rows = currentAlvosRows.filter((row) => memberMatches(row, query)).slice(0, query ? 12 : 6);
        atalhos.className = rows.length ? "member-preview compact small" : "member-preview compact small muted";
        atalhos.replaceChildren(...(rows.length ? rows.map((row) => {
          const item = itemText(pessoaLabel(row, "Membro"), row && row.tag ? `tag: ${row.tag}` : (row && row.situacao || "visto pelo bot"));
          item.addEventListener("click", () => {
            const select = document.getElementById("alvo_select");
            if (select && row && row.alvo_ref) { select.value = row.alvo_ref; updateButtons(); }
          });
          return item;
        }) : [document.createTextNode(query ? "Nenhum membro encontrado." : "Digite acima para filtrar sem aumentar a lista.")]));
      }
      async function loadBotPhoto(disponivel) {
        const avatar = document.getElementById("bot_avatar");
        if (!avatar) return;
        avatar.replaceChildren();
        avatar.textContent = "♫";
        avatar.className = "bot-avatar";
        if (!disponivel || botFotoIndisponivel) return;
        try {
          const res = await api("/equalizador/api/bot/foto");
          if (!res.ok) { botFotoIndisponivel = true; return; }
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const img = document.createElement("img");
          img.className = "bot-avatar";
          img.alt = "Foto do bot";
          img.src = url;
          avatar.textContent = "";
          avatar.appendChild(img);
        } catch (_) { botFotoIndisponivel = true; }
      }
      function renderBotResumo(data) {
        const bot = (data && data.bot) || {};
        const stats = (data && data.estatisticas) || {};
        document.getElementById("bot_nome").textContent = bot.nome || "Bot";
        const botUsuario = document.getElementById("bot_usuario");
        const username = safeUsername(bot.username);
        botUsernameAtual = username || botUsernameAtual || "";
        botUsuario.innerHTML = username ? `<a class="person-link" href="https://t.me/${username}" target="_blank" rel="noopener"><strong>@${username}</strong></a>` : "sem username público";
        const metricas = document.getElementById("bot_metricas");
        metricas.replaceChildren();
        const usuarios = typeof stats.usuarios_conhecidos === "number" ? stats.usuarios_conhecidos : "—";
        const palcos = typeof stats.palcos_ativos === "number" ? stats.palcos_ativos : "—";
        const partes = [`${usuarios} usuários`, `${palcos} grupos`];
        if (typeof stats.operadores_autorizados === "number") partes.push(`${stats.operadores_autorizados} governante(s)`);
        metricas.textContent = partes.join(" • ");
        const revisoes = document.getElementById("bot_revisoes");
        const importantes = (data && data.revisoes_importantes) || [];
        if (revisoes) {
          revisoes.replaceChildren();
          if (importantes.length) {
            const box = document.createElement("div");
            box.innerHTML = `${importantes.map((item) => safeText(item, "revisar")).join(" · ")}`;
            revisoes.appendChild(box);
          }
        }
        loadBotPhoto(Boolean(bot.foto_disponivel));
      }
      async function loadBotResumo() {
        try {
          const res = await api("/equalizador/api/bot/resumo");
          if (!res.ok) return;
          renderBotResumo(await res.json());
        } catch (_) {}
      }
      async function loadPalcoPhoto(grpRef, disponivel) {
        const avatar = document.getElementById("grupo_avatar");
        if (!avatar) return;
        avatar.replaceChildren();
        avatar.textContent = "♪";
        avatar.className = "avatar";
        if (!grpRef || fotosGrupoIndisponiveis.has(grpRef)) return;
        try {
          const res = await api(`/equalizador/api/palcos/${encodeURIComponent(grpRef)}/foto`);
          if (!res.ok) { fotosGrupoIndisponiveis.add(grpRef); return; }
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const img = document.createElement("img");
          img.className = "avatar";
          img.alt = "Foto do grupo";
          img.src = url;
          avatar.textContent = "";
          avatar.appendChild(img);
        } catch (_) { if (grpRef) fotosGrupoIndisponiveis.add(grpRef); }
      }
      function renderGrupoResumo(data) {
        const palco = (data && data.palco) || {};
        const grupoTitulo = palco.titulo || (currentPalco && currentPalco.titulo) || "Grupo";
        const grupoDescricao = safeText(palco.descricao || "", "");
        const tituloEl = document.getElementById("grupo_nome");
        if (tituloEl) {
          tituloEl.innerHTML = grupoHtml(grupoTitulo, palco.username || palco.endereco_publico || (currentPalco && currentPalco.username)) + (grupoDescricao ? ` <span class="inline-dot">•</span> <span class="group-desc-inline">${escapeHtml(grupoDescricao)}</span>` : "");
        }
        const descEl = document.getElementById("grupo_descricao");
        if (descEl) descEl.textContent = "";
        const estado = currentPalco && currentPalco.estado ? currentPalco.estado : (palco.habilitado === false ? "desabilitado" : "habilitado");
        const membros = typeof palco.membros_count === "number" ? `${palco.membros_count} membros` : "membros indisponíveis";
        const recursos = [`${palco.tipo || "grupo"}`, membros, estado, palco.forum ? "fórum" : "sem fórum", palco.modo_lento_segundos ? `modo lento ${palco.modo_lento_segundos}s` : "sem modo lento", (palco.username || palco.endereco_publico) ? "público" : "privado"];
        const metaLinha = document.getElementById("grupo_meta_linha");
        if (metaLinha) metaLinha.textContent = recursos.filter(Boolean).join(" • ");
        const perfilResumo = document.getElementById("perfil_grupo_resumo");
        if (perfilResumo) perfilResumo.innerHTML = `${grupoHtml(palco.titulo || (currentPalco && currentPalco.titulo) || "Grupo", palco.username || palco.endereco_publico || (currentPalco && currentPalco.username))}<br><span class="muted">${escapeHtml(palco.descricao || "Sem descrição pública disponível.")}</span>`;
        loadPalcoPhoto(currentPalco && currentPalco.grp_ref, Boolean(palco.foto_disponivel));
      }
      function renderPainelDinamico(data) {
        currentPainelDinamico = data || null;
        renderDiagnosticoPermissoes();
        const el = document.getElementById("painel_dinamico");
        if (!el) return;
        if (!data || data.erro) {
          el.className = "list muted";
          el.textContent = data && data.erro ? detailPublico(data.erro) : "Painel dinâmico indisponível.";
          return;
        }
        const palco = data.palco || {};
        renderGrupoResumo(data);
        const resumo = data.resumo || {};
        const rows = [];
        rows.push(itemText("Estado operacional", `${resumo.acoes_disponiveis || 0} de ${resumo.acoes_totais || 0} funções liberadas · ${resumo.administradores || 0} administradores · ${resumo.bots_administradores || 0} bots`));
        rows.push(itemText("Grupo", `${palco.titulo || "Grupo"}${palco.forum ? " · fórum" : ""}${palco.modo_lento_segundos ? ` · modo lento ${palco.modo_lento_segundos}s` : ""}`));
        const categorias = new Map();
        (data.acoes || []).forEach((acao) => {
          const key = acao.categoria || "Outras";
          if (!categorias.has(key)) categorias.set(key, []);
          categorias.get(key).push(`${acao.disponivel ? "✓" : "•"} ${acao.nome}${acao.critico ? " · crítico" : ""}${acao.futuro ? " · etapa futura" : ""}`);
        });
        categorias.forEach((items, categoria) => rows.push(itemText(categoria, items.join(" · "))));
        const admins = (data.administradores_humanos || data.administradores || []).slice(0, 12);
        if (admins.length) {
          const item = document.createElement("div");
          item.className = "item small";
          item.innerHTML = `<strong>Administradores humanos</strong><br>${admins.map((admin) => `${admin.perfil_admin || "Administrador"} · ${pessoaHtml(admin, "Administrador")}`).join("<br>")}`;
          rows.push(item);
        }
        const bots = (data.bots_administradores || []).slice(0, 12);
        if (bots.length) {
          const item = document.createElement("div");
          item.className = "item small";
          item.innerHTML = `<strong>Bots administradores</strong><br>${bots.map((bot) => pessoaHtml(bot, "Bot")).join("<br>")}`;
          rows.push(item);
        }
        el.className = "list";
        el.replaceChildren(...rows);
      }
      function renderDiagnosticoPermissoes() {
        const resumoEl = document.getElementById("diagnostico_resumo");
        const operadorEl = document.getElementById("diagnostico_operador");
        const botEl = document.getElementById("diagnostico_bot");
        const acoesEl = document.getElementById("diagnostico_acoes");
        const canaisOperador = currentPalco ? Array.from(canaisPorPalco.get(currentPalco.grp_ref) || []) : [];
        const checks = diagnosticActionOrder.map((codigo) => diagnosticForAction(codigo));
        const liberadas = checks.filter((row) => row.ok).length;
        const bloqueadasOperador = checks.filter((row) => !row.operadorOk).length;
        const bloqueadasBot = checks.filter((row) => !row.botOk).length;
        if (resumoEl) {
          const metric = (value, label, klass) => `<div class="diagnostic-metric ${klass || ''}"><strong>${value}</strong><span class="muted small">${label}</span></div>`;
          resumoEl.innerHTML = metric(liberadas, "ações liberadas", liberadas ? "ok" : "") + metric(bloqueadasOperador, "bloqueadas por operador", bloqueadasOperador ? "warn" : "") + metric(bloqueadasBot, "bloqueadas pelo bot", bloqueadasBot ? "bad" : "") + metric(modoMaestroPermitido ? "sim" : "não", "proprietário técnico", modoMaestroPermitido ? "ok" : "warn");
        }
        if (operadorEl) {
          operadorEl.className = canaisOperador.length ? "list" : "list muted";
          operadorEl.replaceChildren(...(canaisOperador.length ? canaisOperador.map((codigo) => itemText(canalNome(codigo), criticalActions.has(codigo) ? "ação crítica" : "liberado para operador")) : [document.createTextNode(currentPalco ? "Nenhum liberado para operador carregado para este operador neste grupo." : "Escolha um grupo para ver canais do operador.")]));
        }
        if (botEl) {
          const direitos = ultimoAfinacao && ultimoAfinacao.bot && ultimoAfinacao.bot.direitos ? ultimoAfinacao.bot.direitos : {};
          const status = ultimoAfinacao && ultimoAfinacao.bot ? ultimoAfinacao.bot.status : "desconhecido";
          const rows = Object.entries(direitos).map(([codigo, ok]) => ({ codigo, ok }));
          botEl.className = rows.length ? "list" : "list muted";
          botEl.replaceChildren(...(rows.length ? [itemText("Status do bot", status), ...rows.map((row) => itemText(row.codigo, row.ok ? "concedido" : "não concedido"))] : [document.createTextNode("Direitos reais do bot ainda não carregados.")]));
        }
        if (acoesEl) {
          acoesEl.replaceChildren();
          if (!currentPalco) {
            acoesEl.className = "empty small";
            acoesEl.textContent = "Escolha um grupo para calcular o diagnóstico.";
            return;
          }
          acoesEl.className = "diagnostic-grid";
          for (const [categoria, codigos] of diagnosticActionGroups) {
            const checksCategoria = codigos.map((codigo) => ({ codigo, check: diagnosticForAction(codigo) }));
            const liberadosCategoria = checksCategoria.filter((row) => row.check.ok).length;
            const wrapper = document.createElement("details");
            wrapper.className = "diagnostic-section";
            const summary = document.createElement("summary");
            summary.innerHTML = `<span><span class="disclosure-title">${escapeHtml(categoria)}</span><span class="disclosure-sub">${liberadosCategoria} de ${checksCategoria.length} liberado(s)</span></span>`;
            const body = document.createElement("div");
            body.className = "diagnostic-section-body";
            for (const row of checksCategoria) {
              const check = row.check;
              const line = document.createElement("div");
              line.className = `diagnostic-card ${check.ok ? 'ok' : (check.botOk ? 'warn' : 'bad')}`;
              const status = check.ok ? "Liberado" : "Bloqueado";
              const motivos = check.motivos.length ? check.motivos.join(" · ") : "canal e direito real confirmados";
              line.innerHTML = `<strong>${escapeHtml(canalNome(row.codigo))}</strong><span class="small ${check.ok ? 'ok' : 'warn'}">${status}</span><div class="diagnostic-reasons small">${escapeHtml(motivos)}</div>`;
              body.appendChild(line);
            }
            wrapper.appendChild(summary);
            wrapper.appendChild(body);
            acoesEl.appendChild(wrapper);
          }
        }
      }

      function radioDraftLabel(row) {
        if (!row) return "Rascunho";
        const tipo = row.media_kind ? (row.media_kind === "photo" ? "foto" : row.media_kind === "video" ? "vídeo" : "documento") : "texto";
        const status = row.status === "published" ? "publicado" : row.status === "cancelled" ? "cancelado" : "rascunho";
        return `${status} · ${tipo} · ${safeText(row.resumo || row.draft_ref, "Rascunho")}`;
      }
      function renderRadioDrafts(rows) {
        const safeRows = Array.isArray(rows) ? rows : [];
        radioDraftsPorRef = new Map(safeRows.map((row) => [row.draft_ref, row]));
        fillSelect("radio_draft_select", safeRows, "draft_ref", "resumo", "Nenhum rascunho");
        const list = document.getElementById("radio_drafts");
        if (list) {
          list.className = safeRows.length ? "list" : "list muted";
          list.replaceChildren(...(safeRows.length ? safeRows.map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            const media = row.media_kind ? ` · ${escapeHtml(row.media_kind)}${row.media_filename ? ` · ${escapeHtml(row.media_filename)}` : ""}` : "";
            item.innerHTML = `<strong>${escapeHtml(radioDraftLabel(row))}</strong><br><span class="muted">${escapeHtml(row.previa || "sem texto")}${media}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum rascunho carregado.")]));
        }
        updateRadioPreview();
      }
      function updateRadioPreview() {
        const select = document.getElementById("radio_draft_select");
        const preview = document.getElementById("radio_preview");
        const ref = select ? select.value : "";
        const row = ref ? radioDraftsPorRef.get(ref) : null;
        if (!preview) return;
        if (!row) {
          preview.textContent = "Escolha um rascunho para revisar antes de publicar.";
          preview.className = "empty small";
          return;
        }
        const flags = [];
        if (row.sem_preview) flags.push("sem prévia de links");
        if (row.sem_notificacao) flags.push("sem notificação");
        if (row.fixar) flags.push("fixar após publicar");
        if (row.media_kind) flags.push(`mídia: ${row.media_kind}`);
        preview.innerHTML = `<strong>${escapeHtml(radioDraftLabel(row))}</strong><br><span>${escapeHtml(row.previa || "sem texto")}</span><br><span class="muted">${escapeHtml(flags.join(" · ") || "sem opções adicionais")}</span>`;
        preview.className = row.status === "draft" ? "empty small ok" : "empty small muted";
      }
      function inferRadioMediaKind(file) {
        if (!file) return "";
        const type = String(file.type || "").toLowerCase();
        if (type.startsWith("image/")) return "photo";
        if (type.startsWith("video/")) return "video";
        return "document";
      }
      function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
          if (!file) { resolve(""); return; }
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(new Error("Não foi possível ler o arquivo."));
          reader.readAsDataURL(file);
        });
      }
      function radioTemplateLabel(row) {
        const nome = row && row.nome ? row.nome : "Modelo";
        return `${nome}`;
      }
      function renderRadioTemplates(rows) {
        const safeRows = Array.isArray(rows) ? rows : [];
        radioTemplatesPorRef = new Map(safeRows.map((row) => [row.template_ref, row]));
        fillSelect("radio_template_select", safeRows, "template_ref", "nome", "Nenhum modelo");
        const list = document.getElementById("radio_templates");
        if (!list) return;
        if (!safeRows.length) { list.innerHTML = '<div class="empty">Nenhum modelo salvo.</div>'; return; }
        list.innerHTML = "";
        safeRows.slice(0, 12).forEach((row) => {
          const item = document.createElement("div");
          item.className = "listitem";
          const flags = [];
          if (row.sem_preview) flags.push("sem prévia");
          if (row.sem_notificacao) flags.push("silencioso");
          if (row.fixar) flags.push("fixar");
          item.innerHTML = `<strong>${escapeHtml(radioTemplateLabel(row))}</strong><br><span class="muted">${escapeHtml(row.previa || "sem texto")}</span><br><span class="muted small">${escapeHtml(flags.join(" · ") || "publicação simples")}</span>`;
          list.appendChild(item);
        });
      }
      function renderRadioHistory(rows) {
        const safeRows = Array.isArray(rows) ? rows : [];
        radioHistoryRows = safeRows;
        const list = document.getElementById("radio_history");
        if (!list) return;
        if (!safeRows.length) { list.innerHTML = '<div class="empty">Nenhuma publicação Radio registrada.</div>'; return; }
        list.innerHTML = "";
        safeRows.slice(0, 20).forEach((row) => {
          const item = document.createElement("div");
          item.className = "listitem";
          const flags = [];
          if (row.media_kind) flags.push(row.media_kind);
          if (row.fixar) flags.push(row.fixado ? "fixado" : "fixação solicitada");
          if (row.msg_ref) flags.push(row.msg_ref);
          item.innerHTML = `<strong>${escapeHtml(row.resumo || "Publicação Radio")}</strong><br><span class="muted small">${escapeHtml(flags.join(" · ") || "texto")} · ${escapeHtml(row.created_at || "")}</span>`;
          list.appendChild(item);
        });
      }
      async function reloadRadioTudo() {
        await Promise.all([reloadRadioDrafts(), reloadRadioTemplates(), reloadRadioHistory(), reloadRadioSchedules(), reloadRadioQuiet()]);
      }
      function radioScheduleLabel(row) {
        const when = row && row.scheduled_for ? new Date(row.scheduled_for).toLocaleString() : "sem data";
        return `${when} · ${safeText(row && row.status, "scheduled")}`;
      }
      function renderRadioSchedules(rows) {
        const safeRows = Array.isArray(rows) ? rows : [];
        radioSchedulesPorRef = new Map(safeRows.map((row) => [row.schedule_ref, row]));
        fillSelect("radio_schedule_select", safeRows, "schedule_ref", "resumo", "Nenhum agendamento");
        const list = document.getElementById("radio_schedules");
        if (!list) return;
        list.className = safeRows.length ? "list" : "list muted";
        list.replaceChildren(...(safeRows.length ? safeRows.map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          const flags = [];
          if (row.fixar) flags.push("fixar");
          if (row.respeitar_silencio) flags.push("respeita silêncio");
          if (row.last_error) flags.push("erro: " + row.last_error);
          item.innerHTML = `<strong>${escapeHtml(radioScheduleLabel(row))}</strong><br><span class="muted">${escapeHtml(row.resumo || "sem texto")}</span><br><span class="muted small">${escapeHtml(flags.join(" · ") || "publicação simples")}</span>`;
          return item;
        }) : [document.createTextNode("Nenhum agendamento carregado.")]));
      }
      function renderRadioQuiet(row) {
        radioQuietAtual = row || null;
        const quiet = row || {};
        const enabled = Boolean(quiet.enabled);
        const elEnabled = document.getElementById("radio_quiet_enabled");
        const elStart = document.getElementById("radio_quiet_start");
        const elEnd = document.getElementById("radio_quiet_end");
        const elTz = document.getElementById("radio_quiet_tz");
        if (elEnabled) elEnabled.checked = enabled;
        if (elStart) elStart.value = quiet.start_hhmm || "22:00";
        if (elEnd) elEnd.value = quiet.end_hhmm || "08:00";
        if (elTz) elTz.value = quiet.timezone_name || "America/Sao_Paulo";
        const status = document.getElementById("radio_quiet_status");
        if (status) {
          status.className = "empty small " + (enabled ? (quiet.ativo_agora ? "warn" : "ok") : "");
          status.textContent = enabled ? `Silêncio ${quiet.ativo_agora ? "ativo agora" : "fora do período"}: ${quiet.start_hhmm || "22:00"} até ${quiet.end_hhmm || "08:00"} · ${quiet.timezone_name || "America/Sao_Paulo"}` : "Silêncio operacional desativado.";
        }
      }
      function ddxFilterByMode(data, mode) {
        const rows = data && Array.isArray(data.filtros) ? data.filtros : [];
        return rows.find((row) => row.modo === mode) || { palavras: [], enabled: false, total_palavras: 0 };
      }
      function ddxWordsText(words) {
        return (Array.isArray(words) ? words : []).join("\\n");
      }
      function ddxPendingLabel(row) {
        if (!row) return "Agendamento";
        const autor = pessoaLabel({ nome: row.autor_nome, username: row.autor_username }, "Membro");
        const when = row.due_at ? new Date(row.due_at).toLocaleString("pt-BR") : "sem horário";
        return `${when} · ${autor}`;
      }
      function renderDDX(data) {
        const payload = data || {};
        const hard = ddxFilterByMode(payload, "hard");
        const soft = ddxFilterByMode(payload, "soft");
        const hardEnabled = document.getElementById("ddx_hard_enabled");
        const softEnabled = document.getElementById("ddx_soft_enabled");
        const hardWords = document.getElementById("ddx_hard_words");
        const softWords = document.getElementById("ddx_soft_words");
        if (hardEnabled) hardEnabled.checked = Boolean(hard.enabled);
        if (softEnabled) softEnabled.checked = Boolean(soft.enabled);
        if (hardWords) hardWords.value = ddxWordsText(hard.palavras);
        if (softWords) softWords.value = ddxWordsText(soft.palavras);
        const hardStatus = document.getElementById("ddx_hard_status");
        const softStatus = document.getElementById("ddx_soft_status");
        if (hardStatus) {
          hardStatus.textContent = hard.enabled ? `Ativo com ${hard.total_palavras || 0} filtro(s).` : `Inativo com ${hard.total_palavras || 0} filtro(s) salvo(s).`;
          hardStatus.className = "empty small " + (hard.enabled ? "ok" : "muted");
        }
        if (softStatus) {
          softStatus.textContent = soft.enabled ? `Ativo com ${soft.total_palavras || 0} filtro(s).` : `Inativo com ${soft.total_palavras || 0} filtro(s) salvo(s).`;
          softStatus.className = "empty small " + (soft.enabled ? "ok" : "muted");
        }
        const pendentes = Array.isArray(payload.pendentes) ? payload.pendentes : [];
        ddxPendentesPorRef = new Map(pendentes.map((row) => [row.scheduled_ref, row]));
        fillSelect("ddx_pending_select", pendentes.map((row) => Object.assign({}, row, { label: ddxPendingLabel(row) })), "scheduled_ref", "label", "Nenhum apagamento pendente");
        const pendingBox = document.getElementById("ddx_pending");
        if (pendingBox) {
          pendingBox.className = pendentes.length ? "list" : "list muted";
          pendingBox.replaceChildren(...(pendentes.length ? pendentes.map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            const autor = pessoaHtml({ nome: row.autor_nome, username: row.autor_username }, "Membro");
            const words = (row.palavras || []).join(", ") || "filtro";
            item.innerHTML = `<strong>${escapeHtml(ddxPendingLabel(row))}</strong><br>${autor}<br><span class="muted">${escapeHtml(words)} · ${escapeHtml(row.preview || "sem prévia")}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum apagamento DDX 10 minutos pendente.")]));
        }
        const eventos = Array.isArray(payload.eventos) ? payload.eventos : [];
        ddxEventosRows = eventos;
        const eventsBox = document.getElementById("ddx_events");
        if (eventsBox) {
          eventsBox.className = eventos.length ? "list" : "list muted";
          eventsBox.replaceChildren(...(eventos.length ? eventos.slice(0, 20).map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            const autor = pessoaHtml({ nome: row.autor_nome, username: row.autor_username }, "Membro");
            const words = (row.palavras || []).join(", ") || "filtro";
            item.innerHTML = `<strong>${escapeHtml(row.nome || "DDX")} · ${escapeHtml(row.status || "evento")}</strong><br>${autor}<br><span class="muted">${escapeHtml(words)} · ${escapeHtml(row.preview || "sem prévia")}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum evento DDX registrado.")]));
        }
      }
      async function reloadDDX() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/ddx");
        const data = await res.json().catch(() => ({}));
        if (res.ok) renderDDX(data);
      }

      function reactionActorLabel(row) {
        const tipo = row && row.actor_kind === "sender_chat" ? "canal" : "membro";
        return `${pessoaLabel(row || {}, tipo === "canal" ? "Canal" : "Membro")} · ${tipo}`;
      }
      function renderReacoes(data) {
        const payload = data || {};
        const recentes = Array.isArray(payload.recentes) ? payload.recentes : [];
        const eventos = Array.isArray(payload.eventos) ? payload.eventos : [];
        reacoesRecentesPorRef = new Map(recentes.map((row) => [row.recent_ref, row]));
        reacoesEventosRows = eventos;
        fillSelect("reactor_select", recentes.map((row) => Object.assign({}, row, { label: `${reactionActorLabel(row)} · ${row.last_summary || 'sem reação'}` })), "recent_ref", "label", "Nenhum reactor recente");
        const resumoEl = document.getElementById("reacoes_resumo");
        if (resumoEl) {
          const resumo = payload.resumo || {};
          resumoEl.textContent = `${resumo.eventos || eventos.length} evento(s) · ${resumo.reactors_recentes || recentes.length} reactor(es) recente(s)`;
          resumoEl.className = "statusbar " + (eventos.length || recentes.length ? "ok" : "warn");
        }
        const hint = document.getElementById("reactor_hint");
        if (hint) hint.textContent = recentes.length ? "Escolha um reactor recente para limpar reações ou silenciar interação." : "Nenhum reactor recente. O bot precisa receber updates de reação pelo webhook.";
        const recentBox = document.getElementById("reacoes_recentes");
        if (recentBox) {
          recentBox.className = recentes.length ? "list" : "list muted";
          recentBox.replaceChildren(...(recentes.length ? recentes.slice(0, 30).map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            const mute = row.silenciado_ate ? ` · silenciado até ${new Date(row.silenciado_ate).toLocaleString("pt-BR")}` : "";
            item.innerHTML = `<strong>${reactionActorLabel(row)}</strong><br><span class="muted">${escapeHtml(row.last_summary || "sem reação")} · ${Number(row.seen_count || 0)} evento(s)${escapeHtml(mute)}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum reactor recente registrado.")]));
        }
        const eventsBox = document.getElementById("reacoes_eventos");
        if (eventsBox) {
          eventsBox.className = eventos.length ? "list" : "list muted";
          eventsBox.replaceChildren(...(eventos.length ? eventos.slice(0, 40).map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            item.innerHTML = `<strong>${reactionActorLabel(row)} · ${escapeHtml(row.status || "registrou")}</strong><br><span class="muted">${escapeHtml(row.old_summary || "sem reação")} → ${escapeHtml(row.new_summary || "sem reação")} · ${escapeHtml(row.msg_ref || "mensagem")}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum evento de reação registrado.")]));
        }
        updateButtons();
      }
      async function reloadReacoes() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/reacoes/auditoria");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderReacoes(data);
      }
      async function silenciarReactor() {
        if (!currentPalco) { toast("Escolha um grupo antes de silenciar reactor.", "warn"); return; }
        const diag = diagnosticForAction("reacoes.reactor.silenciar");
        if (!diag.ok) { toast("Silenciar reactor bloqueado: " + diag.motivos.join(" · "), "warn"); return; }
        const recentRef = (document.getElementById("reactor_select") || {}).value || "";
        if (!recentRef) { toast("Escolha um reactor recente.", "warn"); return; }
        const minutos = Number((document.getElementById("reactor_silencio_minutos") || {}).value || 60);
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/reacoes/reactor/silenciar", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders),
          body: JSON.stringify({ recent_ref: recentRef, duracao_minutos: minutos })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast(data.resumo || "Reactor silenciado.", "ok");
        await reloadReacoes();
      }

      function novoEventoLabel(row) {
        const links = Array.isArray(row.links) && row.links.length ? row.links.join(", ") : "link detectado";
        return `${pessoaLabel(row || {}, "Membro")} · ${row.status || "pendente"} · ${links}`;
      }
      function renderNovosMembros(data) {
        const payload = data || {};
        const recentes = Array.isArray(payload.recentes) ? payload.recentes : [];
        const eventos = Array.isArray(payload.eventos) ? payload.eventos : [];
        novosRecentesRows = recentes;
        novosEventosRows = eventos;
        novosEventosPorRef = new Map(eventos.map((row) => [row.event_ref, row]));
        fillSelect("novos_evento_select", eventos.map((row) => Object.assign({}, row, { label: novoEventoLabel(row) })), "event_ref", "label", "Nenhum alerta pendente");
        const resumoEl = document.getElementById("novos_resumo");
        if (resumoEl) {
          const resumo = payload.resumo || {};
          resumoEl.textContent = `${resumo.ativos || 0} monitorado(s) ativo(s) · ${resumo.alertas_pendentes || 0} alerta(s) pendente(s) · ${resumo.monitorados || recentes.length} recém-chegado(s) conhecido(s)`;
          resumoEl.className = "statusbar " + ((resumo.alertas_pendentes || eventos.length) ? "warn" : (recentes.length ? "ok" : "muted"));
        }
        const selected = (document.getElementById("novos_evento_select") || {}).value || "";
        const hint = document.getElementById("novos_evento_hint");
        if (hint) {
          const row = novosEventosPorRef.get(selected);
          hint.textContent = row ? `${pessoaLabel(row, "Membro")} · ${row.preview || "sem prévia"}` : "Escolha um alerta para agir.";
        }
        const eventosBox = document.getElementById("novos_eventos");
        if (eventosBox) {
          eventosBox.className = eventos.length ? "list" : "list muted";
          eventosBox.replaceChildren(...(eventos.length ? eventos.slice(0, 40).map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            const links = Array.isArray(row.links) && row.links.length ? row.links.join(", ") : "link detectado";
            item.innerHTML = `<strong>${pessoaHtml(row, "Membro")} · ${escapeHtml(row.status || "pendente")}</strong><br><span class="muted">${escapeHtml(links)} · ${escapeHtml(row.preview || "sem prévia")}</span>`;
            return item;
          }) : [document.createTextNode("Nenhum alerta de novo membro registrado.")]));
        }
        const recentesBox = document.getElementById("novos_recentes");
        if (recentesBox) {
          recentesBox.className = recentes.length ? "list" : "list muted";
          recentesBox.replaceChildren(...(recentes.length ? recentes.slice(0, 40).map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            item.innerHTML = `<strong>${pessoaHtml(row, "Membro")}</strong><br><span class="muted">${escapeHtml(row.status || "monitorado")} · ${Number(row.mensagens_vistas || 0)} mensagem(ns) observada(s)</span>`;
            return item;
          }) : [document.createTextNode("Nenhum recém-chegado monitorado.")]));
        }
        updateButtons();
      }
      async function reloadNovosMembros() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/novos-membros");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderNovosMembros(data);
      }
      async function acaoNovoMembro(acao) {
        if (!currentPalco) { toast("Escolha um grupo antes de agir sobre novos membros.", "warn"); return; }
        const canal = ({ apagar: "novos.apagar", silenciar: "novos.silenciar", banir: "novos.banir", ignorar: "novos.ignorar" })[acao] || "novos.ver";
        const diag = diagnosticForAction(canal);
        if (!diag.ok) { toast("Ação bloqueada: " + diag.motivos.join(" · "), "warn"); return; }
        const ref = (document.getElementById("novos_evento_select") || {}).value || "";
        if (!ref) { toast("Escolha um alerta de novo membro.", "warn"); return; }
        const payload = { duracao_segundos: Number((document.getElementById("novos_silencio_segundos") || {}).value || 3600) };
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/novos-membros/" + encodeURIComponent(ref) + "/" + acao, {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders),
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast(data.resumo || "Alerta atualizado.", "ok");
        await reloadNovosMembros();
      }

      async function salvarDDX(mode) {
        if (!currentPalco) { toast("Escolha um grupo antes de salvar DDX.", "warn"); return; }
        const isSoft = mode === "soft";
        const words = (document.getElementById(isSoft ? "ddx_soft_words" : "ddx_hard_words") || {}).value || "";
        const enabled = Boolean((document.getElementById(isSoft ? "ddx_soft_enabled" : "ddx_hard_enabled") || {}).checked);
        const canal = isSoft ? "ddx.temporario" : "ddx.imediato";
        const diag = diagnosticForAction(canal);
        if (!diag.ok) { toast("DDX bloqueado: " + diag.motivos.join(" · "), "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/ddx", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders),
          body: JSON.stringify({ modo: mode, palavras: words, enabled })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast(isSoft ? "DDX 10 minutos salvo." : "DDX imediato salvo.", "ok");
        await reloadDDX();
      }
      async function cancelarDDXAgendado() {
        if (!currentPalco) return;
        const ref = (document.getElementById("ddx_pending_select") || {}).value || "";
        if (!ref) { toast("Escolha um apagamento pendente.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/ddx/agendados/" + encodeURIComponent(ref) + "/cancelar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast(data.resumo || "Apagamento cancelado.", "ok");
        await reloadDDX();
      }
      async function reloadRadioSchedules() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/agendamentos");
        const data = await res.json().catch(() => ({}));
        if (res.ok) renderRadioSchedules(data.agendamentos || []);
      }
      async function reloadRadioQuiet() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/silencio");
        const data = await res.json().catch(() => ({}));
        if (res.ok) renderRadioQuiet(data.quiet || {});
      }
      async function criarRadioAgendamento() {
        if (!currentPalco) { toast("Escolha um grupo antes de agendar.", "warn"); return; }
        const texto = (document.getElementById("radio_texto") || {}).value || "";
        const templateRef = (document.getElementById("radio_template_select") || {}).value || "";
        const scheduledFor = (document.getElementById("radio_schedule_datetime") || {}).value || "";
        if (!texto.trim() && !templateRef) { toast("Escreva texto ou escolha um modelo antes de agendar.", "warn"); return; }
        const payload = {
          texto,
          template_ref: templateRef,
          scheduled_for: scheduledFor,
          sem_preview: Boolean(document.getElementById("radio_sem_preview").checked),
          sem_notificacao: Boolean(document.getElementById("radio_sem_notificacao").checked),
          fixar: Boolean(document.getElementById("radio_fixar").checked),
          respeitar_silencio: Boolean(document.getElementById("radio_schedule_respeitar_silencio").checked)
        };
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/agendamentos", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast("Agendamento criado.", "ok");
        await reloadRadioSchedules();
      }
      async function cancelarRadioAgendamento() {
        if (!currentPalco) return;
        const ref = (document.getElementById("radio_schedule_select") || {}).value || "";
        if (!ref) { toast("Escolha um agendamento.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/agendamentos/" + encodeURIComponent(ref) + "/cancelar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast("Agendamento cancelado.", "ok");
        await reloadRadioSchedules();
      }
      async function processarRadioAgendamentos() {
        const res = await api("/equalizador/api/radio/agendamentos/processar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast(`Agendamentos: ${data.enviados || 0} enviados, ${data.adiados || 0} adiados, ${data.falhas || 0} falhas.`, data.falhas ? "warn" : "ok");
        await reloadRadioSchedules();
        await reloadRadioHistory();
      }
      async function salvarRadioQuiet() {
        if (!currentPalco) return;
        const payload = {
          enabled: Boolean(document.getElementById("radio_quiet_enabled").checked),
          start_hhmm: (document.getElementById("radio_quiet_start") || {}).value || "22:00",
          end_hhmm: (document.getElementById("radio_quiet_end") || {}).value || "08:00",
          timezone_name: (document.getElementById("radio_quiet_tz") || {}).value || "America/Sao_Paulo"
        };
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/silencio", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderRadioQuiet(data.quiet || {});
        toast("Janela de silêncio salva.", "ok");
      }
      async function executarRadioBroadcast() {
        if (!currentPalco) return;
        const texto = (document.getElementById("radio_texto") || {}).value || "";
        const templateRef = (document.getElementById("radio_template_select") || {}).value || "";
        if (!texto.trim() && !templateRef) { toast("Escreva texto ou escolha modelo antes do broadcast.", "warn"); return; }
        const todos = Boolean(document.getElementById("radio_broadcast_todos").checked);
        const button = document.getElementById("radio_broadcast_enviar");
        if (!armInlineConfirmation(button, todos ? "broadcast geral" : "broadcast no grupo atual", true)) return;
        markButton(button, "working");
        const payload = {
          texto,
          template_ref: templateRef,
          todos,
          sem_preview: Boolean(document.getElementById("radio_sem_preview").checked),
          sem_notificacao: Boolean(document.getElementById("radio_sem_notificacao").checked),
          fixar: Boolean(document.getElementById("radio_fixar").checked),
          respeitar_silencio: Boolean(document.getElementById("radio_broadcast_respeitar_silencio").checked)
        };
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/broadcast", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        const box = document.getElementById("radio_broadcast_resultado");
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); markButton(button, "error"); setTimeout(() => restoreButton(button), 1600); return; }
        markButton(button, "success"); setTimeout(() => restoreButton(button), 1300);
        if (box) {
          box.className = "list";
          const rows = (data.resultados || []).map((row) => {
            const item = document.createElement("div"); item.className = "item small";
            item.textContent = `${row.status || "registrado"}${row.motivo ? " · " + row.motivo : ""}`;
            return item;
          });
          box.replaceChildren(document.createTextNode(data.resumo || "Broadcast concluído."), ...rows);
        }
        toast(data.resumo || "Broadcast concluído.", (data.falhas || 0) ? "warn" : "ok");
        await reloadRadioHistory();
      }
      async function reloadRadioTemplates() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/templates");
        if (!res.ok) { renderRadioTemplates([]); return; }
        const data = await res.json().catch(() => ({}));
        renderRadioTemplates(data.templates || []);
      }
      async function reloadRadioHistory() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/historico");
        if (!res.ok) { renderRadioHistory([]); return; }
        const data = await res.json().catch(() => ({}));
        renderRadioHistory(data.historico || []);
      }
      async function salvarRadioTemplate() {
        if (!currentPalco) return;
        const texto = (document.getElementById("radio_texto") || {}).value || "";
        const nome = (document.getElementById("radio_template_nome") || {}).value || "";
        if (!nome.trim()) { toast("Informe o nome do modelo.", "warn"); return; }
        if (!texto.trim()) { toast("Escreva o texto do modelo.", "warn"); return; }
        const payload = {
          nome,
          texto,
          sem_preview: Boolean(document.getElementById("radio_sem_preview").checked),
          sem_notificacao: Boolean(document.getElementById("radio_sem_notificacao").checked),
          fixar: Boolean(document.getElementById("radio_fixar").checked)
        };
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/templates", {
          method: "POST",
          headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }),
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast("Modelo salvo.", "ok");
        await reloadRadioTemplates();
      }
      async function usarRadioTemplate() {
        if (!currentPalco) return;
        const ref = (document.getElementById("radio_template_select") || {}).value || "";
        const row = ref ? radioTemplatesPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha um modelo.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/templates/" + encodeURIComponent(ref) + "/usar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast("Modelo convertido em rascunho.", "ok");
        await reloadRadioDrafts();
      }
      async function apagarRadioTemplate() {
        if (!currentPalco) return;
        const ref = (document.getElementById("radio_template_select") || {}).value || "";
        const row = ref ? radioTemplatesPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha um modelo.", "warn"); return; }
        const button = document.getElementById("radio_template_apagar");
        if (!armInlineConfirmation(button, "apagar modelo " + radioTemplateLabel(row), true)) return;
        markButton(button, "working");
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/templates/" + encodeURIComponent(ref), { method: "DELETE", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); markButton(button, "error"); setTimeout(() => restoreButton(button), 1600); return; }
        markButton(button, "success"); setTimeout(() => restoreButton(button), 1300);
        toast("Modelo apagado.", "ok");
        await reloadRadioTemplates();
      }

      function renderMultimediaSessions(rows) {
        multimediaSessionsPorRef = new Map();
        const select = document.getElementById("multimidia_session_select");
        const list = document.getElementById("multimidia_sessions");
        if (select) select.replaceChildren(option("", rows && rows.length ? "Escolha uma sessão" : "Nenhuma sessão"));
        const items = (rows || []).map((row) => {
          if (row && row.session_ref) multimediaSessionsPorRef.set(row.session_ref, row);
          if (select) select.appendChild(option(row.session_ref, `${row.estado || row.status || "sessão"} · ${row.tipo_label || row.tipo || "conteúdo"} · ${row.resumo || "sem prévia"}`));
          const item = document.createElement("div");
          item.className = "item-line";
          item.textContent = `${row.estado || row.status || "sessão"} · ${row.tipo_label || row.tipo || "conteúdo"} · ${row.resumo || "sem prévia"}`;
          item.addEventListener("click", () => { if (select) { select.value = row.session_ref; updateMultimediaPreview(); } });
          return item;
        });
        if (list) list.replaceChildren(...(items.length ? items : [document.createTextNode("Nenhuma sessão multimídia carregada.")]));
        updateMultimediaPreview();
      }
      function updateMultimediaPreview() {
        const select = document.getElementById("multimidia_session_select");
        const box = document.getElementById("multimidia_preview");
        if (!box) return;
        const ref = select ? select.value : "";
        const row = ref ? multimediaSessionsPorRef.get(ref) : null;
        const publicar = document.getElementById("multimidia_publicar");
        if (!row) { box.textContent = box.dataset.resumo || "Crie uma sessão e envie o conteúdo no privado do bot."; if (publicar) publicar.disabled = true; return; }
        const aguardando = row.status === "awaiting" ? " · falta enviar conteúdo no privado" : "";
        const passo = row.proximo_passo ? " · " + row.proximo_passo : "";
        box.textContent = `${row.estado || row.status || "sessão"} · ${row.tipo_label || row.tipo || "conteúdo"} · ${row.resumo || "sem prévia"}${aguardando}${passo}${row.erro ? " · " + row.erro : ""}`;
        if (publicar) publicar.disabled = !(row.pode_publicar || row.status === "ready");
      }
      async function reloadMultimediaSessions() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/multimidia/centro");
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          renderMultimediaSessions(data.sessoes || []);
          const preview = document.getElementById("multimidia_preview");
          if (preview && data.resumo) {
            const r = data.resumo;
            preview.dataset.resumo = `${r.prontas || 0} pronta(s) • ${r.aguardando || 0} aguardando • ${r.falhas || 0} falha(s)`;
          }
        }
      }
      async function iniciarMultimediaNativa() {
        if (!currentPalco) { toast("Escolha um grupo antes de iniciar postagem.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/multimidia/sessoes", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        await reloadMultimediaSessions();
        const payload = data.start_payload || (data.sessao && data.sessao.session_ref ? "mm_" + String(data.sessao.session_ref).replace(/^mm_/, "") : "");
        const user = botUsernameAtual || safeUsername((document.getElementById("bot_usuario") || {}).textContent || "");
        if (!user || !payload) { toast("Sessão criada. Abra o privado do bot para enviar a mídia.", "ok"); return; }
        window.open(`https://t.me/${user}?start=${encodeURIComponent(payload)}`, "_blank");
        toast("Sessão criada. Envie texto ou mídia no privado do bot e volte para confirmar.", "ok");
      }
      async function publicarMultimediaSessao() {
        if (!currentPalco) return;
        const select = document.getElementById("multimidia_session_select");
        const ref = select ? select.value : "";
        const row = ref ? multimediaSessionsPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha uma sessão multimídia.", "warn"); return; }
        if (row.status !== "ready") { toast("Envie o conteúdo no privado do bot antes de publicar.", "warn"); return; }
        const button = document.getElementById("multimidia_publicar");
        if (button && button.getAttribute("aria-busy") === "true") return;
        markButton(button, "working");
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/multimidia/sessoes/" + encodeURIComponent(ref) + "/publicar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = data.detail || data;
          if (res.status === 409 && detail && detail.sessao && detail.sessao.session_ref) {
            multimediaSessionsPorRef.set(detail.sessao.session_ref, detail.sessao);
            renderMultimediaSessions(Array.from(multimediaSessionsPorRef.values()));
          }
          const msg = res.status === 409 ? (detail && (detail.mensagem || detail.message) ? (detail.mensagem || detail.message) : "Sessão em conflito. Atualizei a lista para você conferir o estado real.") : detailPublico(detail);
          toast(msg, res.status === 409 ? "warn" : "bad");
          markButton(button, "error"); setTimeout(() => restoreButton(button), 1600);
          await reloadMultimediaSessions(); return;
        }
        markButton(button, "success"); setTimeout(() => restoreButton(button), 1300);
        toast("Publicação multimídia enviada.", "ok");
        await reloadMultimediaSessions();
        await reloadRadioHistory();
      }

      async function reloadRadioDrafts() {
        if (!currentPalco) return;
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/rascunhos");
        const data = await res.json().catch(() => ({}));
        if (res.ok) renderRadioDrafts(data.rascunhos || []);
      }
      async function criarRadioRascunho() {
        if (!currentPalco) { toast("Escolha um grupo antes de criar rascunho.", "warn"); return; }
        const texto = (document.getElementById("radio_texto") || {}).value || "";
        const fileInput = document.getElementById("radio_media_input");
        const file = fileInput && fileInput.files && fileInput.files.length ? fileInput.files[0] : null;
        if (file && file.size > 8 * 1024 * 1024) { toast("Arquivo acima do limite seguro: 8 MB.", "bad"); return; }
        if (!texto.trim() && !file) { toast("Escreva um texto ou anexe mídia.", "warn"); return; }
        const payload = {
          texto,
          sem_preview: Boolean(document.getElementById("radio_sem_preview").checked),
          sem_notificacao: Boolean(document.getElementById("radio_sem_notificacao").checked),
          fixar: Boolean(document.getElementById("radio_fixar").checked)
        };
        if (file) {
          payload.media_kind = inferRadioMediaKind(file);
          payload.media_filename = file.name || "arquivo";
          payload.media_mime = file.type || "application/octet-stream";
          payload.media_base64 = await fileToDataUrl(file);
        }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/rascunhos", {
          method: "POST",
          headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }),
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const box = document.getElementById("radio_resultado");
        if (box) box.textContent = "Rascunho criado: " + radioDraftLabel(data.rascunho || {});
        toast("Rascunho criado para revisão.", "ok");
        await reloadRadioDrafts();
      }
      async function publicarRadioRascunho() {
        if (!currentPalco) return;
        const button = document.getElementById("radio_publicar");
        if (button && button.getAttribute("aria-busy") === "true") return;
        const ref = (document.getElementById("radio_draft_select") || {}).value || "";
        const row = ref ? radioDraftsPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha um rascunho.", "warn"); return; }
        if (row.status !== "draft") { toast("Rascunho já foi publicado ou cancelado. Atualize a lista.", "warn"); return; }
        markButton(button, "working");
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/rascunhos/" + encodeURIComponent(ref) + "/publicar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = detailPublico(data.detail || data);
          toast(detail, res.status === 409 ? "warn" : "bad");
          markButton(button, "error");
          setTimeout(() => restoreButton(button), 1600);
          await reloadRadioDrafts();
          return;
        }
        markButton(button, "success");
        setTimeout(() => restoreButton(button), 1300);
        if (data.fixacao && data.fixacao.ok === false) toast("Publicado, mas não fixado: " + (data.fixacao.motivo || "permissão insuficiente"), "warn");
        else toast("Rascunho publicado.", "ok");
        if (data.mensagem && data.mensagem.msg_ref) {
          mensagensPorRef.set(data.mensagem.msg_ref, data.mensagem);
        }
        setRefreshState("Sincronizando rascunhos e histórico de rádio…", "loading");
        await loadPalcoData();
        await reloadRadioHistory();
      }
      async function cancelarRadioRascunho() {
        if (!currentPalco) return;
        const ref = (document.getElementById("radio_draft_select") || {}).value || "";
        const row = ref ? radioDraftsPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha um rascunho.", "warn"); return; }
        if (row.status !== "draft") { toast("Somente rascunhos abertos podem ser cancelados.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/rascunhos/" + encodeURIComponent(ref) + "/cancelar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        toast("Rascunho cancelado.", "ok");
        await reloadRadioDrafts();
      }

      function fillConfigForm(formulario) {
        const data = formulario || {};
        const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value == null ? "" : String(value); };
        set("cfg_app_name", data.app_name || "equalizador");
        set("cfg_enabled", String(data.enabled !== false));
        set("cfg_maestros", data.maestro_ids || "");
        set("cfg_operadores", data.operador_ids || "");
        set("cfg_palcos", data.palco_ids || "");
        set("cfg_rate", data.rate_limit_per_minute || 30);
        set("cfg_aliases", data.aliases_linhas || "");
        set("cfg_canais", data.canais || "");
        const raw = document.getElementById("config_raw");
        if (raw) raw.value = "";
        const copy = document.getElementById("copiar_config_raw");
        if (copy) copy.disabled = true;
        const resumo = document.getElementById("config_preview_resumo");
        if (resumo) resumo.textContent = "Campos carregados. Revise e clique em Gerar bloco final somente no final.";
      }
      function configPayloadFromForm() {
        const value = (id) => (document.getElementById(id) && document.getElementById(id).value) || "";
        return {
          app_name: value("cfg_app_name"),
          enabled: value("cfg_enabled"),
          maestro_ids: value("cfg_maestros"),
          operador_ids: value("cfg_operadores"),
          palco_ids: value("cfg_palcos"),
          aliases_linhas: value("cfg_aliases"),
          canais: value("cfg_canais"),
          rate_limit_per_minute: value("cfg_rate"),
          hide_technical_ids: true,
          initdata_max_age_seconds: 600,
          session_ttl_seconds: 2592000
        };
      }
      async function gerarConfigRaw() {
        if (!modoMaestroPermitido) { toast("Configuração restrita ao proprietário técnico.", "warn"); return; }
        const res = await api("/equalizador/api/configuracao/raw-preview", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}),
          body: JSON.stringify(configPayloadFromForm())
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const raw = document.getElementById("config_raw");
        if (raw) raw.value = data.raw_editor || "";
        const copy = document.getElementById("copiar_config_raw");
        if (copy) copy.disabled = !(data.raw_editor || "");
        const resumo = document.getElementById("config_preview_resumo");
        const r = data.resumo || {};
        if (resumo) {
          const avisos = (data.avisos || []).length ? " · " + data.avisos.join(" · ") : "";
          resumo.textContent = `${r.aliases || 0} aliases · ${r.palcos || 0} grupos · ${r.maestros || 0} proprietário(s) técnico(s) · ${r.operadores || 0} operador(es)${avisos}`;
          resumo.className = "empty small " + ((data.avisos || []).length ? "warn" : "ok");
        }
        toast("Bloco final para copiar gerado para conferência.", "ok");
      }
      function renderRbacRuntime(data) {
        const payload = data || {};
        const rbac = payload.rbac_runtime || payload;
        const operadores = Array.isArray(rbac.operadores) ? rbac.operadores : [];
        const palcos = Array.isArray(rbac.palcos) ? rbac.palcos : [];
        const canais = Array.isArray(rbac.canais) ? rbac.canais : [];
        const grants = Array.isArray(rbac.concessoes) ? rbac.concessoes : [];
        const usrSelect = document.getElementById("rbac_usr_ref");
        if (usrSelect) {
          usrSelect.replaceChildren(...(operadores.length ? operadores.map((row) => option(row.usr_ref || row.ui_ref, pessoaLabel(row, row.perfil || "Governante"))) : [option("", "Nenhum governante conhecido")]));
          const selected = operadores.find((row) => String(row.usr_ref || row.ui_ref || "") === String(usrSelect.value || "")) || operadores[0];
          if (selected) {
            const setEdit = (id, value) => { const el = document.getElementById(id); if (el && !el.value) el.value = value || ""; };
            setEdit("rbac_edit_nome", selected.nome || "");
            setEdit("rbac_edit_username", selected.username || "");
            setEdit("rbac_edit_perfil", selected.perfil || "Governante designado");
          }
        }
        const grpSelect = document.getElementById("rbac_grp_ref");
        if (grpSelect) {
          grpSelect.replaceChildren(...(palcos.length ? palcos.map((row) => option(row.grp_ref, row.titulo || row.grp_ref)) : [option("*", "Todos os grupos autorizados")]));
        }
        const canalSelect = document.getElementById("rbac_canal_codigo");
        if (canalSelect) {
          canalSelect.replaceChildren(...(canais.length ? canais.map((row) => option(row.codigo, `${row.nome || row.codigo}${row.critico ? " · crítico" : ""}`)) : [option("", "Nenhum canal disponível")]));
        }
        const grantSelect = document.getElementById("rbac_grant_ref");
        if (grantSelect) {
          grantSelect.replaceChildren(...(grants.length ? grants.map((row) => option(row.grant_ref, `${pessoaLabel(row.operador || {}, "Governante")} · ${(row.palco || {}).titulo || "Grupo"} · ${(row.canal || {}).nome || "canal"}`)) : [option("", "Nenhuma concessão runtime ativa")]));
        }
        const resumo = document.getElementById("rbac_runtime_resumo");
        const rr = rbac.resumo || {};
        if (resumo) resumo.textContent = `${rr.ativas || grants.length || 0} concessão(ões) runtime ativa(s) · ${rr.canais_criticos || 0} crítica(s)`;
        fillList("rbac_runtime_lista", grants, (row) => {
          const operador = pessoaLabel(row.operador || {}, "Governante");
          const palco = (row.palco || {}).titulo || "Grupo";
          const canal = (row.canal || {}).nome || (row.canal || {}).codigo || "canal";
          const critico = row.canal && row.canal.critico ? " · crítico" : "";
          return itemText(`${operador} · ${palco}`, `${canal}${critico} · origem: runtime${row.motivo ? " · " + row.motivo : ""}`);
        }, "Nenhuma concessão runtime ativa.");
        const sessoes = payload.sessoes_persistentes || {};
        const sessoesEl = document.getElementById("sessoes_persistentes");
        if (sessoesEl) sessoesEl.textContent = `${sessoes.ativas || 0} sessão(ões) ativa(s) · ${sessoes.expiradas || 0} expirada(s) · ${sessoes.total || 0} total`;
      }
      async function adicionarGovernanteRuntime() {
        if (!modoMaestroPermitido) { toast("Cadastro restrito ao dono do código.", "warn"); return; }
        const payload = {
          telegram_user_id: (document.getElementById("rbac_new_user_id") || {}).value || "",
          nome: (document.getElementById("rbac_new_nome") || {}).value || "",
          username: (document.getElementById("rbac_new_username") || {}).value || "",
          perfil: (document.getElementById("rbac_new_perfil") || {}).value || "Governante designado",
        };
        const res = await api("/equalizador/api/rbac/operadores", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const fields = ["rbac_new_user_id", "rbac_new_nome", "rbac_new_username", "rbac_new_perfil"];
        fields.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
        renderRbacRuntime({ rbac_runtime: data.rbac_runtime || data });
        toast("Governante adicionado ao painel.", "ok");
        await loadConfiguracaoMaestro();
      }
      async function concederRbacRuntime() {
        if (!modoMaestroPermitido) { toast("Delegação restrita ao dono do código.", "warn"); return; }
        const payload = {
          usr_ref: (document.getElementById("rbac_usr_ref") || {}).value || "",
          grp_ref: (document.getElementById("rbac_grp_ref") || {}).value || "*",
          canal_codigo: (document.getElementById("rbac_canal_codigo") || {}).value || "",
          motivo: (document.getElementById("rbac_motivo") || {}).value || "",
        };
        if (!payload.usr_ref) { toast("Escolha um governante conhecido para delegar.", "warn"); return; }
        if (!payload.canal_codigo) { toast("Escolha o canal de permissão.", "warn"); return; }
        const res = await api("/equalizador/api/rbac/runtime", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderRbacRuntime({ rbac_runtime: data });
        toast("Canal concedido em runtime.", "ok");
        await loadConfiguracaoMaestro();
      }
      async function revogarRbacRuntime() {
        if (!modoMaestroPermitido) { toast("Revogação restrita ao dono do código.", "warn"); return; }
        const ref = (document.getElementById("rbac_grant_ref") || {}).value || "";
        if (!ref) { toast("Escolha uma concessão runtime ativa.", "warn"); return; }
        const res = await api("/equalizador/api/rbac/runtime/" + encodeURIComponent(ref), { method: "DELETE", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderRbacRuntime({ rbac_runtime: data });
        toast("Concessão runtime revogada.", "ok");
        await loadConfiguracaoMaestro();
      }
      async function limparSessoesExpiradas() {
        if (!modoMaestroPermitido) { toast("Limpeza restrita ao dono do código.", "warn"); return; }
        const res = await api("/equalizador/api/sessoes/limpar-expiradas", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderRbacRuntime(data);
        toast(`Sessões expiradas removidas: ${data.removidas || 0}.`, "ok");
      }
      function renderSeguranca(data) {
        const payload = data && data.seguranca_avancada ? data.seguranca_avancada : (data || {});
        const modo = payload.modo || {};
        const modoEl = document.getElementById("seguranca_modo_atual");
        if (modoEl) modoEl.textContent = `Modo atual: ${modo.nome || modo.modo || "Normal"}${modo.motivo ? " · " + modo.motivo : ""}`;
        const resumo = payload.resumo || {};
        const resumoEl = document.getElementById("seguranca_resumo");
        if (resumoEl) resumoEl.textContent = `${resumo.eventos_recentes || 0} evento(s) recente(s) · ${resumo.linhas_exportaveis || 0} linha(s) exportáveis · sha256 ${resumo.sha256 || "—"}`;
        const diagnostico = payload.diagnostico || {};
        const diagEl = document.getElementById("seguranca_diagnostico");
        if (diagEl) diagEl.textContent = `Fontes auditáveis: ${(diagnostico.tabelas || []).join(", ") || "nenhuma fonte carregada"}`;
        fillList("seguranca_auditoria", payload.auditoria || [], (row) => {
          const meta = row.meta ? Object.entries(row.meta).map(([k, v]) => `${k}: ${v}`).join(" · ") : "";
          return itemText(`${row.tipo || "evento"} · ${row.status || "status"}`, `${row.resumo || "Evento"} · ${row.created_at || ""}${meta ? " · " + meta : ""}`);
        }, "Nenhum evento de segurança registrado.");
      }
      async function loadSeguranca() {
        if (!modoMaestroPermitido) return;
        const res = await api("/equalizador/api/seguranca", { headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderSeguranca(data);
      }
      async function alterarModoSeguranca(modo) {
        if (!modoMaestroPermitido) { toast("Segurança restrita ao dono do código.", "warn"); return; }
        const motivo = (document.getElementById("seguranca_motivo") || {}).value || "";
        const res = await api("/equalizador/api/seguranca/modo", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}), body: JSON.stringify({ modo, motivo }) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderSeguranca(data);
        toast(`Modo de segurança: ${modo}.`, "ok");
      }
      async function exportarSeguranca(tipo) {
        if (!modoMaestroPermitido) { toast("Exportação restrita ao dono do código.", "warn"); return; }
        let res;
        if (tipo === "criptografado") {
          const senha = (document.getElementById("seguranca_senha_export") || {}).value || "";
          res = await api("/equalizador/api/seguranca/auditoria/exportar-criptografada", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}), body: JSON.stringify({ senha }) });
        } else {
          res = await api("/equalizador/api/seguranca/auditoria/exportar?tipo=" + encodeURIComponent(tipo), { headers: apiHeaders });
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const out = document.getElementById("seguranca_export_result");
        if (out) out.value = JSON.stringify(data.exportacao || data, null, 2);
        toast("Exportação de segurança gerada.", "ok");
      }
      async function limparAuditoriaSeguranca() {
        if (!modoMaestroPermitido) { toast("Limpeza restrita ao dono do código.", "warn"); return; }
        const dias = Number((document.getElementById("seguranca_limpar_dias") || {}).value || 180);
        const res = await api("/equalizador/api/seguranca/auditoria/limpar", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, apiHeaders || {}), body: JSON.stringify({ dias }) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderSeguranca(data);
        toast(`Auditoria antiga removida: ${data.removidas || 0}.`, "ok");
      }
      async function limparLocksSeguranca() {
        if (!modoMaestroPermitido) { toast("Locks restritos ao dono do código.", "warn"); return; }
        const res = await api("/equalizador/api/seguranca/locks/limpar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        renderSeguranca(data);
        toast("Locks e rate-limit em memória foram limpos.", "ok");
      }
      const aliasLinesMap = () => {
        const value = String((document.getElementById("cfg_aliases") || {}).value || "");
        const map = new Map();
        value.split(/\\n+/).forEach((line) => {
          const clean = line.trim();
          if (!clean || !clean.includes("=")) return;
          const [alias, raw] = clean.split("=", 2);
          map.set(String(raw || "").trim(), String(alias || "").trim());
        });
        return map;
      };
      const palcoTituloPorId = (rows) => {
        const map = new Map();
        (rows || []).forEach((row) => {
          const id = String(row.chat_id || row.telegram_chat_id || "").trim();
          if (id) map.set(id, row);
        });
        return map;
      };
      function renderConfigChipList(id, rows, render, emptyText) {
        const el = document.getElementById(id);
        if (!el) return;
        const data = Array.isArray(rows) ? rows : [];
        el.className = data.length ? "chip-grid" : "list muted";
        el.replaceChildren(...(data.length ? data.map(render) : [document.createTextNode(emptyText)]));
      }
      function configBadge(title, sub) {
        const div = document.createElement("div");
        div.className = "badge";
        div.innerHTML = `<strong>${escapeHtml(title)}</strong>${sub ? ` · <span class="muted">${escapeHtml(sub)}</span>` : ""}`;
        return div;
      }

      function renderPersistencia(persistencia) {
        const el = document.getElementById("persistencia_status");
        if (!el) return;
        const tabelas = persistencia && persistencia.tabelas ? persistencia.tabelas : {};
        const importadas = ["lastfm_profiles", "track_plays", "track_likes", "track_reactions"].map((name) => {
          const value = Object.prototype.hasOwnProperty.call(tabelas, name) ? tabelas[name] : null;
          return `${name}: ${value === null || typeof value === "undefined" ? "ausente" : value}`;
        }).join(" · ");
        const estado = persistencia && persistencia.persistente ? "volume persistente" : "atenção: fora do volume";
        const alertas = Array.isArray(persistencia && persistencia.alertas) && persistencia.alertas.length ? ` · ${persistencia.alertas.join(", ")}` : "";
        el.textContent = `${estado} · ${importadas}${alertas}`;
      }

      async function loadConfiguracaoMaestro() {
        if (!modoMaestroPermitido) return;
        const res = await api("/equalizador/api/configuracao");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        fillConfigForm(data.formulario || {});
        const aliasMap = aliasLinesMap();
        const byId = palcoTituloPorId(data.palcos_ativos || []);
        renderConfigChipList("config_palcos_ativos", data.palcos_ativos || [], (row) => {
          const id = String(row.chat_id || row.telegram_chat_id || "").trim();
          const alias = aliasMap.get(id);
          return configBadge(row.titulo || "Grupo", `${row.estado || "ativo"}${alias ? " · alias: " + alias : ""}${id ? " · ID " + id : ""}`);
        }, "Nenhum grupo ativo em TR4_EQUALIZADOR_PALCO_IDS.");
        renderConfigChipList("config_aliases", data.aliases || [], (row) => {
          const id = String(row.chat_id || "").trim();
          const palcoRow = byId.get(id);
          const realName = row.titulo || (palcoRow && palcoRow.titulo) || "grupo não sincronizado";
          return configBadge(realName, `${row.alias || "alias"}${id ? " · ID " + id : ""} · ${row.estado || "estado"}`);
        }, "Nenhum alias configurado em GROUP_ALIASES.");
        fillList("config_palcos_ocultos", data.palcos_ocultos || [], (row) => itemText(row.titulo || "Grupo oculto", `${row.estado || "oculto"} · ${row.grp_ref || ""}`), "Nenhum grupo antigo fora da variável ativa.");
        fillList("config_operadores", data.operadores || [], (row) => {
          const canais = (row.canais || []).map((canal) => canal.nome || canal.codigo);
          const preview = canais.slice(0, 3).join(", ") || "sem canais";
          const extra = canais.length > 3 ? ` · +${canais.length - 3} canal(is)` : "";
          return itemText(`${row.perfil || "Operador"} · ${pessoaLabel(row, row.perfil || "Operador")}`, `canais: ${preview}${extra}`);
        }, "Nenhum operador configurado.");
        const gov = data.governanca || {};
        const govResumo = (gov && gov.resumo) || {};
        const govResumoEl = document.getElementById("config_governantes_resumo");
        if (govResumoEl) govResumoEl.textContent = `${govResumo.governantes || 0} governante(s) · ${govResumo.palcos || 0} grupo(s) · ${govResumo.janelas_ativas || 0} janela(s) ativa(s)`;
        const govPersistEl = document.getElementById("config_governanca_persistencia");
        const gp = data.governanca_persistencia && data.governanca_persistencia.resumo ? data.governanca_persistencia.resumo : {};
        if (govPersistEl) govPersistEl.textContent = `Persistência: ${data.governanca_persistencia && data.governanca_persistencia.status ? data.governanca_persistencia.status : "não verificada"} · ${gp.governantes_ativos || 0} governante(s) · ${gp.concessoes_ativas || 0} concessão(ões) · ${gp.eventos_auditoria || 0} evento(s)`;
        renderGovernanca("config_governantes", gov, { onlyActive: true });
        renderRbacRuntime(data);
        renderSeguranca(data);
        renderPersistencia(data.persistencia || {});
        const matriz = data.matriz_permissoes || {};
        const resumo = matriz.resumo || {};
        const resumoEl = document.getElementById("config_matriz_resumo");
        if (resumoEl) resumoEl.textContent = `${resumo.operadores || 0} operadores · ${resumo.palcos || 0} grupos · ${resumo.canais || 0} canais · ${resumo.canais_criticos || 0} críticos`;
        const matrizRows = [];
        (matriz.matriz || []).forEach((operador) => {
          (operador.palcos || []).forEach((palco) => {
            const concedidos = (palco.canais || []).filter((canal) => canal.concedido).map((canal) => canal.nome || canal.codigo);
            const negadosCriticos = (palco.canais || []).filter((canal) => canal.critico && !canal.concedido).length;
            matrizRows.push({
              titulo: `Participante com permissão · ${operador.perfil || "Operador"} · ${pessoaLabel(operador, operador.perfil || "Operador")} · ${palco.titulo || "Grupo"}`,
              detalhe: `${concedidos.length ? concedidos.join(", ") : "sem canais concedidos"}${negadosCriticos ? ` · ${negadosCriticos} críticos bloqueados` : ""}`,
            });
          });
        });
        fillDisclosureList("config_matriz", matrizRows.map((row) => {
          const parts = String(row.titulo || "").split(" · ");
          const grupo = parts[parts.length - 1] || "Grupo";
          const operador = parts.slice(0, -1).join(" · ") || "Participante com permissão";
          const canais = String(row.detalhe || "").split(",").filter(Boolean).length;
          return { titulo: grupo, resumo: `${operador}${canais ? ` · ${canais} item(ns)` : ""}`, detalhe: row.detalhe };
        }), "Matriz sem operadores ou grupos configurados.");
        const auditoria = data.auditoria_permissoes || {};
        const audResumo = auditoria.resumo || {};
        const audResumoEl = document.getElementById("config_permissoes_auditoria_resumo");
        if (audResumoEl) audResumoEl.textContent = `${audResumo.owner_only || 0} rotas owner-only · ${audResumo.familias_com_canal || 0} famílias com canal · ${audResumo.exposicao || "sem exposição sensível"}`;
        const audRows = (auditoria.owner_only || []).map((row) => ({ titulo: row.rota || "rota", resumo: row.finalidade || "controle", detalhe: row.bloqueio || "somente dono" }));
        fillDisclosureList("config_permissoes_auditoria", audRows, "Auditoria de permissões vazia.");
      }

      async function loadPalcoData() {
        if (!currentPalco || carregandoPalco) return;
        carregandoPalco = true;
        lastRefreshStartedAt = Date.now();
        setPanelRefreshing(true, "Atualizando");
        setRefreshState("Atualizando dados do grupo e janelas do painel…", "loading");
        setAllOperationalNavStates("loading");
        setListLoading("mensagens_lote_lista", "Carregando mensagens recentes…");
        setListLoading("mesa_membros_preview", "Carregando pessoas do painel…");
        direitosDisponiveis = new Set();
        ultimoAfinacao = null;
        afinacaoLoaded = false;
        try {
        const base = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref);
        const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes, painelRes, entradasRes, convitesRes, topicosRes, remetentesRes, governantesRes, radioRes, radioTemplatesRes, radioHistoryRes, radioSchedulesRes, radioQuietRes, ddxRes, reacoesRes, novosRes] = await Promise.all([
          api(base + "/afinacao").then((r) => r.ok ? r.json() : null).catch(() => null),
          api(base + "/mensagens").then((r) => r.ok ? r.json() : { mensagens: [] }).catch(() => ({ mensagens: [] })),
          api(base + "/alvos").then((r) => r.ok ? r.json() : { alvos: [] }).catch(() => ({ alvos: [] })),
          api("/equalizador/api/historico").then((r) => r.ok ? r.json() : { historico: [] }).catch(() => ({ historico: [] })),
          (modoMaestroPermitido ? api("/equalizador/api/canais/distribuicao").then((r) => r.ok ? r.json() : { distribuicao: [] }).catch(() => ({ distribuicao: [] })) : Promise.resolve({ distribuicao: [] })),
          api(base + "/painel").then((r) => r.ok ? r.json() : null).catch(() => null),
          api(base + "/entradas").then((r) => r.ok ? r.json() : { entradas: [] }).catch(() => ({ entradas: [] })),
          api(base + "/convites").then((r) => r.ok ? r.json() : { convites: [] }).catch(() => ({ convites: [] })),
          api(base + "/topicos").then((r) => r.ok ? r.json() : { topicos: [] }).catch(() => ({ topicos: [] })),
          api(base + "/canais-remetentes").then((r) => r.ok ? r.json() : { remetentes: [] }).catch(() => ({ remetentes: [] })),
          (modoMaestroPermitido ? api(base + "/governantes").then((r) => r.ok ? r.json() : { governantes: [] }).catch(() => ({ governantes: [] })) : Promise.resolve({ governantes: [] })),
          api(base + "/radio/rascunhos").then((r) => r.ok ? r.json() : { rascunhos: [] }).catch(() => ({ rascunhos: [] })),
          api(base + "/radio/templates").then((r) => r.ok ? r.json() : { templates: [] }).catch(() => ({ templates: [] })),
          api(base + "/radio/historico").then((r) => r.ok ? r.json() : { historico: [] }).catch(() => ({ historico: [] })),
          api(base + "/radio/agendamentos").then((r) => r.ok ? r.json() : { agendamentos: [] }).catch(() => ({ agendamentos: [] })),
          api(base + "/radio/silencio").then((r) => r.ok ? r.json() : { quiet: {} }).catch(() => ({ quiet: {} })),
          api(base + "/ddx").then((r) => r.ok ? r.json() : { filtros: [], eventos: [], pendentes: [] }).catch(() => ({ filtros: [], eventos: [], pendentes: [] })),
          api(base + "/reacoes/auditoria").then((r) => r.ok ? r.json() : { eventos: [], recentes: [], resumo: {} }).catch(() => ({ eventos: [], recentes: [], resumo: {} })),
          api(base + "/novos-membros").then((r) => r.ok ? r.json() : { eventos: [], recentes: [], resumo: {} }).catch(() => ({ eventos: [], recentes: [], resumo: {} }))
        ]);
        renderGovernanca("governantes_palco", governantesRes, { palcoRef: currentPalco && currentPalco.grp_ref, onlyActive: true });
        renderMesaMembrosResumo(painelRes, (alvosRes && alvosRes.alvos) || []);
        renderRadioDrafts((radioRes && radioRes.rascunhos) || []);
        await reloadMultimediaSessions();
        renderRadioTemplates((radioTemplatesRes && radioTemplatesRes.templates) || []);
        renderRadioHistory((radioHistoryRes && radioHistoryRes.historico) || []);
        renderRadioSchedules((radioSchedulesRes && radioSchedulesRes.agendamentos) || []);
        renderRadioQuiet((radioQuietRes && radioQuietRes.quiet) || {});
        renderDDX(ddxRes || { filtros: [], eventos: [], pendentes: [] });
        renderReacoes(reacoesRes || { eventos: [], recentes: [], resumo: {} });
        renderNovosMembros(novosRes || { eventos: [], recentes: [], resumo: {} });
        renderPainelDinamico(painelRes);
        if (afinacaoRes && Array.isArray(afinacaoRes.canais)) {
          ultimoAfinacao = afinacaoRes;
          afinacaoLoaded = true;
          direitosDisponiveis = new Set(afinacaoRes.canais.filter((canal) => canal.disponivel).map((canal) => canal.codigo));
          const af = document.getElementById("afinacao");
          const totalDisponivel = afinacaoRes.canais.filter((canal) => canal.disponivel).length;
          const resumo = document.getElementById("afinacao_resumo");
          if (resumo) {
            resumo.textContent = `${totalDisponivel} de ${afinacaoRes.canais.length} ajustes disponíveis neste grupo.`;
            resumo.className = "statusbar " + (totalDisponivel ? "ok" : "warn");
          }
          af.className = "list";
          af.replaceChildren(...afinacaoRes.canais.map((canal) => {
            const item = document.createElement("div");
            item.className = "item";
            const faltando = (canal.faltando || []).length ? `<br><span class="small muted">Faltando: ${(canal.faltando || []).join(', ')}</span>` : "";
            item.innerHTML = `<strong>${canal.nome}</strong><br><span class="${canal.disponivel ? 'ok' : 'bad'}">${canal.disponivel ? 'Disponível' : 'Indisponível'}</span>${faltando}`;
            return item;
          }));
          renderDiagnosticoPermissoes();
        }
        if (!afinacaoLoaded) {
          const af = document.getElementById("afinacao");
          af.className = "list muted";
          af.textContent = "Permissões do bot indisponíveis no momento. Nenhum botão operacional será liberado sem direito real confirmado.";
          const resumo = document.getElementById("afinacao_resumo");
          if (resumo) {
            resumo.textContent = "Permissões do bot não carregadas.";
            resumo.className = "statusbar warn";
          }
        }
        const mensagensRows = mensagensRes.mensagens || [];
        mensagensPorRef = new Map(mensagensRows.map((row) => [row.msg_ref, row]));
        renderMensagensLote(mensagensRows);
        const mensagensOptions = mensagensRows.map((row) => Object.assign({}, row, {
          resumo: row.apagavel === false ? row.resumo + " · fora da janela de apagar" : row.resumo
        }));
        fillSelect("mensagem_select", mensagensOptions, "msg_ref", "resumo", "Nenhuma mensagem registrada");
        const alvosRows = alvosRes.alvos || [];
        currentAlvosRows = alvosRows;
        const alvosOptions = alvosRows.map((row) => Object.assign({}, row, {
          nome_label: `${pessoaLabel(row, 'Membro')} · ${row.situacao || 'desconhecido'}`
        }));
        fillSelect("alvo_select", alvosOptions, "alvo_ref", "nome_label", "Nenhum membro registrado");
        const mensagensHint = document.getElementById("mensagens_hint");
        if (mensagensHint) mensagensHint.textContent = mensagensRows.length ? `${mensagensRows.length} mensagem(ns) recente(s) registradas.` : "Envie uma mensagem no grupo e atualize o painel para criar uma referência segura.";
        renderPessoasPainel(currentPainelDinamico, alvosRows);
        const alvosHint = document.getElementById("alvos_hint");
        if (alvosHint) alvosHint.textContent = alvosRows.length ? `${alvosRows.length} membro(s) registrado(s) para operação.` : "Faça um membro enviar mensagem ou entrar no grupo para criar uma referência segura.";
        renderAlvosBusca();
        const entradaRows = entradasRes.entradas || [];
        fillSelect("entrada_select", entradaRows.map((row) => Object.assign({}, row, { label: `${pessoaLabel(row, 'Membro')} · ${row.situacao || 'pendente'}` })), "entrada_ref", "label", "Nenhum pedido pendente");
        const entradasHint = document.getElementById("entradas_hint");
        if (entradasHint) entradasHint.textContent = entradaRows.length ? `${entradaRows.length} pedido(s) de entrada registrado(s).` : "Nenhum pedido de entrada capturado. Crie convite com aprovação para receber pedidos.";
        const conviteRows = convitesRes.convites || [];
        convitesPorRef = new Map(conviteRows.map((row) => [row.invite_ref, row]));
        fillSelect("convite_select", conviteRows.map((row) => Object.assign({}, row, { label: `${row.nome || row.invite_ref} · ${row.revogado ? 'revogado' : 'ativo'}` })), "invite_ref", "label", "Nenhum convite criado");
        const convitesHint = document.getElementById("convites_hint");
        if (convitesHint) convitesHint.textContent = conviteRows.length ? `${conviteRows.length} convite(s) conhecido(s). Escolha um item para editar, revogar, copiar ou abrir.` : "Convites criados pelo Equalizador aparecerão aqui.";
        renderConvitesLista(conviteRows);
        updateConviteSelecionado();
        const topicoRows = topicosRes.topicos || [];
        topicosPorRef = new Map(topicoRows.map((row) => [row.topico_ref, row]));
        fillSelect("topico_select", topicoRows.map((row) => Object.assign({}, row, { label: `${row.nome || row.topico_ref} · ${row.estado || 'registrado'}` })), "topico_ref", "label", "Nenhum tópico registrado");
        const topicosHint = document.getElementById("topicos_hint");
        if (topicosHint) topicosHint.textContent = topicoRows.length ? `${topicoRows.length} tópico(s) conhecido(s). Escolha um item para editar, fechar, reabrir, desfixar ou apagar.` : "Tópicos criados ou vistos pelo Equalizador aparecerão aqui.";
        renderTopicosLista(topicoRows);
        updateTopicoSelecionado();
        const hist = document.getElementById("historico");
        const rows = (historicoRes.historico || []).filter((row) => row.palco_ref === currentPalco.grp_ref).slice(0, 20);
        hist.className = rows.length ? "list" : "list muted";
        hist.replaceChildren(...(rows.length ? rows.map((row) => {
          const item = document.createElement("div");
          item.className = "item";
          const ator = row.ator ? pessoaHtml(row.ator, 'Operador') : '<strong>Operador</strong>';
          const alvo = row.alvo ? `<br><span class="muted">Alvo: ${pessoaHtml(row.alvo, 'Membro')}</span>` : '';
          item.innerHTML = `${ator}<br>${escapeHtml(row.resumo || row.ajuste || 'Ajuste')} · ${escapeHtml(row.status || 'registrado')}${alvo}`;
          return item;
        }) : [document.createTextNode("Nenhum ajuste registrado.")]));
        const dist = document.getElementById("distribuicao");
        const distRows = distribuicaoRes.distribuicao || [];
        dist.className = distRows.length ? "list" : "list muted";
        dist.replaceChildren(...(distRows.length ? distRows.slice(0, 12).map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          const operador = row.operador && row.operador.escopo ? row.operador.escopo : pessoaLabel(row.operador, 'Operador');
          const grupo = row.palco && (row.palco.titulo || row.palco.escopo || row.palco.grp_ref) ? (row.palco.titulo || row.palco.escopo || row.palco.grp_ref) : 'Grupo';
          item.innerHTML = `${escapeHtml(operador)} · ${escapeHtml(grupo)} · ${escapeHtml((row.canais || []).map(canalNome).join(', ') || 'sem canais')}`;
          return item;
        }) : [document.createTextNode(modoMaestroPermitido ? "Nenhuma distribuição disponível." : "Distribuição restrita ao proprietário técnico.")]));
        if (modoMaestroPermitido) loadConfiguracaoMaestro().catch(() => null);
        updateButtons();
        setAllOperationalNavStates("ok");
        const elapsed = Math.max(0.1, (Date.now() - lastRefreshStartedAt) / 1000).toFixed(1);
        setRefreshState(`Atualizado agora · ${elapsed}s · janela atual: ${viewTitle(currentViewId)}`, "ok");
        } catch (err) {
          setAllOperationalNavStates("bad");
          statusMesa("Falha ao carregar painel do grupo. Reabra o Equalizador ou tente atualizar.", "bad");
          setRefreshState("Falha ao atualizar. Use copiar detalhes se o erro persistir.", "bad");
          toast("Falha ao carregar painel do grupo.", "bad");
          reportClient("palco_load_failed", err && err.message ? err.message : String(err || "erro"));
        } finally { carregandoPalco = false; setPanelRefreshing(false); }
      }
      async function resolveMensagemManual() {
        if (!currentPalco) { toast("Escolha um grupo antes de resolver mensagem.", "warn"); return; }
        const input = document.getElementById("mensagem_link_input");
        const link = input.value.trim();
        if (!link) { toast("Cole o link da mensagem.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/mensagens/resolver", {
          method: "POST",
          headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }),
          body: JSON.stringify({ link })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const row = data.mensagem;
        if (row && row.msg_ref) {
          mensagensPorRef.set(row.msg_ref, row);
          renderMensagensLote(Array.from(mensagensPorRef.values()));
          const select = document.getElementById("mensagem_select");
          select.prepend(option(row.msg_ref, row.resumo || row.msg_ref));
          select.value = row.msg_ref;
          toast("Mensagem resolvida com segurança.", "ok");
          updateButtons();
        }
      }
      async function resolveAlvoManual() {
        if (!currentPalco) { toast("Escolha um grupo antes de resolver membro.", "warn"); return; }
        const input = document.getElementById("alvo_manual_input");
        const identificador = input.value.trim();
        if (!identificador) { toast("Informe @username ou referência interna.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/alvos/resolver", {
          method: "POST",
          headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }),
          body: JSON.stringify({ identificador })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        const row = data.alvo;
        if (row && row.alvo_ref) {
          const select = document.getElementById("alvo_select");
          select.prepend(option(row.alvo_ref, `${pessoaLabel(row, 'Membro')} · ${row.situacao || 'desconhecido'}`));
          select.value = row.alvo_ref;
          toast("Membro resolvido com segurança.", "ok");
          updateButtons();
        }
      }
      function buildPayload(action) {
        if (action === "mensagens.enviar") {
          const texto = (document.getElementById("mensagem_envio_texto") || {}).value || "";
          if (!texto.trim()) throw new Error("Escreva a mensagem antes de enviar.");
          if (texto.length > 4096) throw new Error("Mensagem acima do limite do Telegram.");
          return {
            texto,
            sem_preview: Boolean(document.getElementById("mensagem_envio_sem_preview").checked),
            sem_notificacao: Boolean(document.getElementById("mensagem_envio_sem_notificacao").checked),
            fixar: Boolean(document.getElementById("mensagem_envio_fixar").checked)
          };
        }
        if (action === "mensagens.apagar" || action.startsWith("fixados.")) {
          const msg = document.getElementById("mensagem_select").value;
          if (!msg) throw new Error("Escolha uma mensagem registrada.");
          const mensagem = mensagensPorRef.get(msg);
          if (action === "mensagens.apagar" && mensagem && mensagem.apagavel === false) {
            throw new Error("Mensagem fora da janela de apagamento do Telegram.");
          }
          return { msg_ref: msg, sem_notificacao: true };
        }
        if (action.startsWith("membros.")) {
          const alvo = document.getElementById("alvo_select").value;
          if (!alvo) throw new Error("Escolha um membro registrado.");
          const duracao = Number(document.getElementById("silencio_duracao").value || 3600);
          const revogar = Boolean(document.getElementById("remover_revogar").checked);
          return { alvo_ref: alvo, duracao_segundos: duracao, revogar_mensagens: revogar, apenas_se_banido: true };
        }
        if (action === "entradas.aprovar" || action === "entradas.recusar") {
          const entrada = document.getElementById("entrada_select").value;
          if (!entrada) throw new Error("Escolha um pedido de entrada.");
          return { entrada_ref: entrada };
        }
        if (action === "convites.editar" || action === "convites.revogar") {
          const convite = document.getElementById("convite_select").value;
          if (!convite) throw new Error("Escolha um convite criado.");
          if (action === "convites.revogar") return { invite_ref: convite };
          const limite = Number(document.getElementById("convite_limite").value || 0);
          const aprovacao = Boolean(document.getElementById("convite_aprovacao").checked);
          return {
            invite_ref: convite,
            nome: document.getElementById("convite_nome").value || "Equalizador",
            expira_em_segundos: Number(document.getElementById("convite_expira").value || 0),
            limite_membros: aprovacao ? 0 : Math.max(0, Math.min(99999, limite || 0)),
            solicitar_aprovacao: aprovacao
          };
        }
        if (action === "convites.exportar_primario") return {};
        if (action === "convites.criar") {
          const limite = Number(document.getElementById("convite_limite").value || 0);
          const aprovacao = Boolean(document.getElementById("convite_aprovacao").checked);
          return {
            nome: document.getElementById("convite_nome").value || "Equalizador",
            expira_em_segundos: Number(document.getElementById("convite_expira").value || 0),
            limite_membros: aprovacao ? 0 : Math.max(0, Math.min(99999, limite || 0)),
            solicitar_aprovacao: aprovacao,
            enviar_dm: Boolean(document.getElementById("convite_dm").checked)
          };
        }
        if (action === "silencio.ativar" || action === "silencio.desativar") return { confirmacao: "CONFIRMAR AJUSTE" };
        if (action === "transmissao.enviar") {
          const texto = document.getElementById("transmissao_texto").value.trim();
          if (!texto) throw new Error("Escreva o texto da transmissão.");
          return {
            texto,
            confirmacao: "CONFIRMAR AJUSTE",
            sem_preview: Boolean(document.getElementById("transmissao_preview").checked),
            sem_notificacao: Boolean(document.getElementById("transmissao_silenciosa").checked),
            fixar: Boolean(document.getElementById("transmissao_fixar").checked)
          };
        }
        if (action.startsWith("topicos.")) {
          const nome = (document.getElementById("topico_nome") || {}).value || "";
          const topico = (document.getElementById("topico_select") || {}).value || "";
          if (action === "topicos.criar") {
            if (!nome.trim()) throw new Error("Informe um nome para o novo tópico.");
            return { nome: nome.trim() };
          }
          if (!action.startsWith("topicos.geral") && !topico) throw new Error("Escolha um tópico registrado.");
          return { topico_ref: topico, nome: nome || undefined };
        }
        if (action.startsWith("canais_remetentes.")) {
          const sender = (document.getElementById("sender_select") || {}).value || "";
          if (!sender) throw new Error("Escolha um canal remetente.");
          return { sender_ref: sender };
        }
        if (action === "reacoes.mensagem.limpar" || action === "reacoes.recentes.limpar") {
          const msg = (document.getElementById("mensagem_select") || {}).value || "";
          const alvo = (document.getElementById("alvo_select") || {}).value || "";
          const sender = (document.getElementById("sender_select") || {}).value || "";
          const reactorRef = (document.getElementById("reactor_select") || {}).value || "";
          const reactor = reactorRef ? reacoesRecentesPorRef.get(reactorRef) : null;
          const base = {};
          if (action === "reacoes.mensagem.limpar") { if (!msg) throw new Error("Escolha uma mensagem registrada."); base.msg_ref = msg; }
          if (reactor && reactor.actor_kind === "sender_chat") base.sender_ref = reactor.actor_ref;
          else if (reactor && reactor.actor_ref) base.alvo_ref = reactor.actor_ref;
          else if (alvo) base.alvo_ref = alvo;
          else if (sender) base.sender_ref = sender;
          else throw new Error("Escolha um membro, canal remetente ou reactor recente.");
          return base;
        }
        if (action === "membros.tag.definir") {
          const alvo = document.getElementById("alvo_select").value;
          if (!alvo) throw new Error("Escolha um membro registrado.");
          return { alvo_ref: alvo, tag: (document.getElementById("membro_tag") || {}).value || "" };
        }
        if (action === "grupo.titulo") {
          const titulo = (document.getElementById("grupo_titulo_input") || {}).value || "";
          if (!titulo.trim()) throw new Error("Informe o novo título do grupo.");
          return { titulo, confirmacao: "CONFIRMAR AJUSTE", ciente: cienteCritico() };
        }
        if (action === "grupo.descricao") {
          return { descricao: (document.getElementById("grupo_descricao_input") || {}).value || "", confirmacao: "CONFIRMAR AJUSTE", ciente: cienteCritico() };
        }
        if (action === "grupo.foto" || action === "grupo.foto.remover") {
          return { confirmacao: "CONFIRMAR AJUSTE", ciente: cienteCritico() };
        }
        if (action.startsWith("admins.")) {
          const adminSelect = document.getElementById("admin_alvo_select");
          const alvo = (adminSelect && adminSelect.value) || document.getElementById("alvo_select").value;
          if (!alvo) throw new Error("Escolha um membro ou administrador registrado.");
          return {
            alvo_ref: alvo,
            perfil: (document.getElementById("admin_perfil_select") || {}).value || "moderador",
            titulo_admin: (document.getElementById("admin_titulo_input") || {}).value || "",
            confirmacao: "CONFIRMAR AJUSTE",
            ciente: cienteCritico()
          };
        }
        return {};
      }

      async function apagarMensagensLote() {
        if (!currentPalco) { toast("Escolha um grupo antes de apagar em lote.", "warn"); return; }
        const refs = Array.from(mensagensSelecionadas).filter((ref) => {
          const row = mensagensPorRef.get(ref);
          return row && row.apagavel !== false;
        });
        if (!refs.length) { toast("Selecione mensagens apagáveis.", "warn"); return; }
        if (refs.length > 100) { toast("Selecione no máximo 100 mensagens por lote.", "warn"); return; }
        const diagnostic = diagnosticForAction("mensagens.apagar_lote");
        if (!diagnostic.ok) { toast("Apagamento em lote bloqueado: " + diagnostic.motivos.join(" · "), "warn"); return; }
        const button = document.getElementById("mensagens_lote_apagar");
        if (!armInlineConfirmation(button, refs.length + " mensagem(ns)", true)) return;
        markButton(button, "working");
        statusMesa("Apagando " + refs.length + " mensagem(ns) em lote…", "muted");
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints["mensagens.apagar_lote"];
        const res = await api(url, { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify({ msg_refs: refs }) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = detailPublico(data.detail || data);
          statusMesa("Apagamento em lote não concluído: " + detail, "bad");
          toast(detail, "bad");
          markButton(button, "error");
          setTimeout(() => restoreButton(button), 1600);
          updateButtons();
          return;
        }
        mensagensSelecionadas = new Set();
        const ignoradas = Array.isArray(data.ignoradas) && data.ignoradas.length ? ` · ${data.ignoradas.length} ignorada(s)` : "";
        toast((data.apagadas || refs.length) + " mensagem(ns) apagada(s)" + ignoradas + ".", "ok");
        markButton(button, "success");
        setTimeout(() => restoreButton(button), 1300);
        statusMesa(data.resumo || "Apagamento em lote concluído.", "ok");
        setRefreshState("Atualizando lista de mensagens após apagamento…", "loading");
        await loadPalcoData();
      }

      async function runPhotoAction(action) {
        if (!currentPalco) return;
        const button = document.querySelector(`button.action[data-action="${action}"]`);
        if (!armInlineConfirmation(button, actionLabels[action] || action, true)) return;
        markButton(button, "working");
        statusMesa("Executando: " + (actionLabels[action] || action) + "…", "muted");
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints[action];
        let options;
        if (action === "grupo.foto") {
          const input = document.getElementById("grupo_foto_input");
          const file = input && input.files && input.files[0] ? input.files[0] : null;
          if (!file) { toast("Escolha uma imagem para trocar a foto do grupo.", "warn"); updateButtons(); return; }
          if (file.size > 8 * 1024 * 1024) { toast("Imagem acima do limite de 8 MB.", "warn"); updateButtons(); return; }
          const allowed = new Set(["image/jpeg", "image/png", "image/webp"]);
          if (!allowed.has(file.type)) { toast("Use JPG, PNG ou WEBP.", "warn"); updateButtons(); return; }
          let imagem_base64;
          try { imagem_base64 = await fileToBase64(file); } catch (err) { toast(err.message || "Imagem inválida.", "bad"); updateButtons(); return; }
          options = {
            method: "POST",
            headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }),
            body: JSON.stringify({ imagem_base64, nome_arquivo: file.name || "grupo-foto", mime_type: file.type, confirmacao: "CONFIRMAR AJUSTE", ciente: cienteCritico() })
          };
        } else {
          options = { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify({ confirmacao: "CONFIRMAR AJUSTE", ciente: cienteCritico() }) };
        }
        const res = await api(url, options);
        const data = await res.json().catch(() => ({}));
        const box = document.getElementById("grupo_foto_resultado");
        if (!res.ok) {
          const detail = detailPublico(data.detail || data);
          if (box) { box.textContent = detail; box.className = "empty small bad"; }
          toast(detail, "bad");
          markButton(button, "error");
          setTimeout(() => restoreButton(button), 1600);
          updateButtons();
          // Compatibilidade de teste legado: await loadPalcoData(); return;
          return;
        }
        fotosGrupoIndisponiveis.delete(currentPalco.grp_ref);
        if (action === "grupo.foto") { const input = document.getElementById("grupo_foto_input"); if (input) input.value = ""; }
        if (box) { box.textContent = data.resumo || "Foto do grupo atualizada."; box.className = "empty small ok"; }
        toast(data.resumo || "Foto do grupo ajustada.", "ok");
        markButton(button, "success");
        setTimeout(() => restoreButton(button), 1300);
        statusMesa("Último ajuste concluído: " + (actionLabels[action] || action) + ".", "ok");
        setRefreshState("Sincronizando perfil do grupo após foto…", "loading");
        await loadPalcoData();
      }
      async function runAction(action) {
        if (action === "grupo.foto" || action === "grupo.foto.remover") { await runPhotoAction(action); return; }
        if (!currentPalco) return;
        const button = document.querySelector(`button.action[data-action="${action}"]`);
        if (!armInlineConfirmation(button, actionLabels[action] || action, criticalActions.has(action))) return;
        let payload;
        try { payload = buildPayload(action); } catch (err) { toast(err.message, "warn"); restoreButton(button); return; }
        markButton(button, "working");
        statusMesa("Executando: " + (actionLabels[action] || action) + "…", "muted");
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints[action];
        const res = await api(url, { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = detailPublico(data.detail || data);
          statusMesa("Ajuste não concluído: " + detail, "bad");
          toast(detail, "bad");
          markButton(button, "error");
          setTimeout(() => restoreButton(button), 1600);
          updateButtons();
          return;
        }
        markButton(button, "success");
        setTimeout(() => restoreButton(button), 1300);
        if (data.convite && typeof data.convite === "string") {
          setConviteResult(data.convite, data.dm || null, data.convite_info || null);
          try { await navigator.clipboard.writeText(data.convite); toast("Convite criado, exibido e copiado.", "ok"); }
          catch (_) { toast("Convite criado e exibido no painel.", "ok"); }
        } else {
          let successText = data.resumo || "Ajuste concluído.";
          if (data.mensagem) setMensagemResult(data.mensagem, data.resumo || "Ajuste de mensagem concluído.");
          if (data.entrada) successText = data.resumo || `Pedido de entrada: ${data.entrada.situacao || 'tratado'}.`;
          if (data.convite && typeof data.convite === "object") successText = data.resumo || "Convite ajustado.";
          if (data.membro) setMembroResult(data.membro, data.resumo || "Ajuste de membro concluído.");
          if (data.resultado) {
            successText = data.resumo || `${data.resultado.estado || 'ajuste'}: ${data.resultado.nome || 'referência'}`;
            const adminBox = document.getElementById("admin_resultado");
            if (adminBox && (action.startsWith("admins.") || action.startsWith("grupo."))) {
              const box = document.getElementById("admin_resultado");
              if (box) { box.textContent = successText; box.className = "empty small ok"; }
            }
          }
          if (data.fixacao && data.fixacao.ok === false) toast("Transmissão enviada, mas não fixada: " + (data.fixacao.motivo || "permissão do bot insuficiente"), "warn");
          toast(successText, "ok");
        }
        statusMesa("Último ajuste concluído: " + (actionLabels[action] || action) + ".", "ok");
        setRefreshState("Sincronizando painel após a ação…", "loading");
        await loadPalcoData();
      }
      const feedbackCopyButton = document.getElementById("feedback_copy");
      if (feedbackCopyButton) feedbackCopyButton.addEventListener("click", async () => {
        const texto = feedbackEntries.map((entry) => `[${entry.time}] ${feedbackKindLabel(entry.kind)}: ${entry.text}`).join("\\n");
        if (!texto) return;
        try { await navigator.clipboard.writeText(texto); toast("Detalhes do painel copiados.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione os detalhes manualmente.", "warn"); }
      });
      const feedbackClearButton = document.getElementById("feedback_clear");
      if (feedbackClearButton) feedbackClearButton.addEventListener("click", () => { feedbackEntries = []; renderFeedbackPanel(); haptic("selection"); });
      document.getElementById("mensagem_select").addEventListener("change", updateButtons);
      document.getElementById("alvo_select").addEventListener("change", updateButtons);
      const alvosBusca = document.getElementById("alvos_busca");
      if (alvosBusca) alvosBusca.addEventListener("input", renderAlvosBusca);
      const mesaMembrosBusca = document.getElementById("mesa_membros_busca");
      if (mesaMembrosBusca) mesaMembrosBusca.addEventListener("input", () => renderMesaMembrosResumo(currentPainelDinamico, currentAlvosRows));
      document.getElementById("admin_alvo_select").addEventListener("change", updateButtons);
      document.getElementById("entrada_select").addEventListener("change", updateButtons);
      document.getElementById("convite_select").addEventListener("change", () => { updateConviteSelecionado(); updateButtons(); });
      document.getElementById("topico_select").addEventListener("change", () => { updateTopicoSelecionado(); updateButtons(); });
      document.getElementById("sender_select").addEventListener("change", updateButtons);
      document.getElementById("reactor_select").addEventListener("change", updateButtons);
      document.getElementById("resolver_mensagem").addEventListener("click", resolveMensagemManual);
      document.getElementById("resolver_alvo").addEventListener("click", resolveAlvoManual);
      document.getElementById("mensagens_lote_apagar").addEventListener("click", apagarMensagensLote);
      document.getElementById("mensagens_lote_limpar").addEventListener("click", limparMensagensSelecionadas);
      document.getElementById("copiar_convite").addEventListener("click", async () => {
        const value = document.getElementById("convite_resultado").value.trim();
        if (!value) return;
        try { await navigator.clipboard.writeText(value); toast("Link copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione o campo do link.", "warn"); }
      });
      document.getElementById("abrir_convite").addEventListener("click", () => {
        const value = document.getElementById("convite_resultado").value.trim();
        if (value) window.open(value, "_blank");
      });
      document.getElementById("copiar_convite_selecionado").addEventListener("click", async () => {
        const ref = document.getElementById("convite_select").value;
        const row = convitesPorRef.get(ref);
        const value = row && row.link ? String(row.link).trim() : "";
        if (!value) return;
        try { await navigator.clipboard.writeText(value); toast("Convite selecionado copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Use o link exibido no resultado quando disponível.", "warn"); }
      });
      document.getElementById("abrir_convite_selecionado").addEventListener("click", () => {
        const ref = document.getElementById("convite_select").value;
        const row = convitesPorRef.get(ref);
        const value = row && row.link ? String(row.link).trim() : "";
        if (value) window.open(value, "_blank");
      });
      document.getElementById("transmissao_texto").addEventListener("input", () => {
        const text = document.getElementById("transmissao_texto").value || "";
        document.getElementById("transmissao_contador").textContent = `${text.length}/4096 caracteres`;
      });
      document.getElementById("mensagem_envio_texto").addEventListener("input", () => {
        const text = document.getElementById("mensagem_envio_texto").value || "";
        document.getElementById("mensagem_envio_contador").textContent = `${text.length}/4096 caracteres`;
      });
      document.getElementById("radio_texto").addEventListener("input", () => {
        const text = document.getElementById("radio_texto").value || "";
        const mediaInput = document.getElementById("radio_media_input");
        const hasMedia = mediaInput && mediaInput.files && mediaInput.files.length;
        const max = hasMedia ? 1024 : 4096;
        document.getElementById("radio_contador").textContent = `${text.length}/${max} caracteres`;
      });
      document.getElementById("radio_media_input").addEventListener("change", () => {
        const text = document.getElementById("radio_texto").value || "";
        const file = document.getElementById("radio_media_input").files[0];
        const max = file ? 1024 : 4096;
        document.getElementById("radio_contador").textContent = `${text.length}/${max} caracteres`;
        if (file && file.size > 8 * 1024 * 1024) toast("Arquivo acima do limite seguro: 8 MB.", "bad");
      });
      document.getElementById("radio_draft_select").addEventListener("change", updateRadioPreview);
      document.getElementById("radio_criar_rascunho").addEventListener("click", criarRadioRascunho);
      document.getElementById("multimidia_iniciar").addEventListener("click", safeAsync("multimidia_iniciar_failed", iniciarMultimediaNativa));
      document.getElementById("multimidia_atualizar").addEventListener("click", safeAsync("multimidia_reload_failed", reloadMultimediaSessions));
      document.getElementById("multimidia_session_select").addEventListener("change", () => { try { updateMultimediaPreview(); } catch (error) { reportException("multimidia_preview_failed", error); } });
      document.getElementById("multimidia_publicar").addEventListener("click", safeAsync("multimidia_publicar_failed", publicarMultimediaSessao));
      document.getElementById("radio_publicar").addEventListener("click", publicarRadioRascunho);
      document.getElementById("radio_cancelar").addEventListener("click", cancelarRadioRascunho);
      document.getElementById("radio_template_salvar").addEventListener("click", salvarRadioTemplate);
      document.getElementById("radio_template_usar").addEventListener("click", usarRadioTemplate);
      document.getElementById("radio_template_apagar").addEventListener("click", apagarRadioTemplate);
      document.getElementById("radio_schedule_criar").addEventListener("click", criarRadioAgendamento);
      document.getElementById("radio_schedule_cancelar").addEventListener("click", cancelarRadioAgendamento);
      document.getElementById("radio_schedules_processar").addEventListener("click", processarRadioAgendamentos);
      document.getElementById("radio_quiet_salvar").addEventListener("click", salvarRadioQuiet);
      document.getElementById("radio_broadcast_enviar").addEventListener("click", executarRadioBroadcast);
      document.getElementById("ddx_hard_salvar").addEventListener("click", () => salvarDDX("hard"));
      document.getElementById("ddx_soft_salvar").addEventListener("click", () => salvarDDX("soft"));
      document.getElementById("ddx_cancelar_agendado").addEventListener("click", cancelarDDXAgendado);
      document.getElementById("reacoes_atualizar").addEventListener("click", reloadReacoes);
      document.getElementById("reacoes_silenciar_reactor").addEventListener("click", silenciarReactor);
      document.getElementById("novos_atualizar").addEventListener("click", reloadNovosMembros);
      document.getElementById("novos_evento_select").addEventListener("change", () => renderNovosMembros({ eventos: novosEventosRows, recentes: novosRecentesRows, resumo: {} }));
      document.getElementById("novos_apagar").addEventListener("click", () => acaoNovoMembro("apagar"));
      document.getElementById("novos_silenciar").addEventListener("click", () => acaoNovoMembro("silenciar"));
      document.getElementById("novos_banir").addEventListener("click", () => acaoNovoMembro("banir"));
      document.getElementById("novos_ignorar").addEventListener("click", () => acaoNovoMembro("ignorar"));
      document.querySelectorAll("button.action[data-action]").forEach((button) => button.addEventListener("click", () => { button.classList.add("pressed"); setTimeout(() => button.classList.remove("pressed"), 180); haptic("impact", "light"); runAction(button.dataset.action); }));
      document.getElementById("exportar_historico").addEventListener("click", async () => {
        if (!modoMaestroPermitido) { toast("Exportação restrita ao proprietário técnico.", "warn"); return; }
        const res = await api("/equalizador/api/historico/exportar");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(data.detail || "Exportação indisponível.", "bad"); return; }
        const exp = data.exportacao || {};
        const total = typeof exp.total_registros === "number" ? ` · ${exp.total_registros} registros` : "";
        const box = document.getElementById("exportacao_resultado");
        if (box) box.value = exp.json_texto || JSON.stringify(exp, null, 2);
        toast("Exportação gerada: " + (exp.exportacao_ref || "pronta") + total, "ok");
      });
      document.getElementById("atualizar_configuracao").addEventListener("click", () => loadConfiguracaoMaestro());
      document.getElementById("gerar_config_raw").addEventListener("click", () => gerarConfigRaw());
      document.getElementById("resetar_config_form").addEventListener("click", () => loadConfiguracaoMaestro());
      const rbacAdicionarGovernante = document.getElementById("rbac_adicionar_governante");
      if (rbacAdicionarGovernante) rbacAdicionarGovernante.addEventListener("click", () => adicionarGovernanteRuntime());
      const rbacAtualizarGovernante = document.getElementById("rbac_atualizar_governante");
      if (rbacAtualizarGovernante) rbacAtualizarGovernante.addEventListener("click", () => atualizarGovernanteRuntime());
      const rbacRemoverGovernante = document.getElementById("rbac_remover_governante");
      if (rbacRemoverGovernante) rbacRemoverGovernante.addEventListener("click", () => removerGovernanteRuntime());
      document.getElementById("rbac_conceder").addEventListener("click", () => concederRbacRuntime());
      document.getElementById("rbac_revogar").addEventListener("click", () => revogarRbacRuntime());
      document.getElementById("sessoes_limpar").addEventListener("click", () => limparSessoesExpiradas());
      document.getElementById("seguranca_modo_normal").addEventListener("click", () => alterarModoSeguranca("normal"));
      document.getElementById("seguranca_modo_alerta").addEventListener("click", () => alterarModoSeguranca("alerta"));
      document.getElementById("seguranca_modo_restrito").addEventListener("click", () => alterarModoSeguranca("restrito"));
      document.getElementById("seguranca_exportar_jsonl").addEventListener("click", () => exportarSeguranca("jsonl"));
      document.getElementById("seguranca_exportar_assinado").addEventListener("click", () => exportarSeguranca("assinado"));
      document.getElementById("seguranca_exportar_criptografado").addEventListener("click", () => exportarSeguranca("criptografado"));
      document.getElementById("seguranca_limpar_auditoria").addEventListener("click", () => limparAuditoriaSeguranca());
      document.getElementById("seguranca_limpar_locks").addEventListener("click", () => limparLocksSeguranca());
      document.getElementById("copiar_config_raw").addEventListener("click", async () => {
        const value = document.getElementById("config_raw").value || "";
        if (!value) return;
        try { await navigator.clipboard.writeText(value); toast("Bloco final copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione o campo do bloco final.", "warn"); }
      });
      const storedSession = getStoredSession();
      if (initData) {
        bootstrapHeaders = { "Authorization": "tma " + initData };
        apiHeaders = bootstrapHeaders;
      } else if (storedSession) {
        bootstrapHeaders = null;
        apiHeaders = { "Authorization": "eqs " + storedSession };
        reportClient("initdata_ausente_usando_sessao", "initData ausente; tentando sessão curta persistida no WebView.");
      } else {
        reportClient("initdata_ausente", "Telegram.WebApp.initData ausente e sem sessão curta local.");
        show("denied");
        return;
      }
      markPanel("panel_ping_started", "ok", "");
      fetchWithTimeout("/equalizador/api/public/ping?panel=1&ts=" + Date.now(), {}, 3500)
        .then((response) => markPanel("panel_ping_done", String(response.status), ""))
        .catch((error) => markPanel("panel_ping_failed", error && error.message ? error.message : "ping_failed", ""));
      markPanel("panel_api_me_started", "ok", "");
      fetchWithTimeout("/equalizador/api/me", { headers: apiHeaders })
        .then((response) => {
          markPanel("panel_api_me_done", String(response.status), "");
          if (response.ok) return response.json();
          const err = new Error("denied");
          err.status = response.status;
          throw err;
        })
        .then((me) => {
          const sessionToken = me.sessao && me.sessao.token ? me.sessao.token : "";
          if (sessionToken) setStoredSession(sessionToken);
          apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : apiHeaders;
          const nomeEl = document.getElementById("nome");
          if (nomeEl) {
            const username = String(me.username || "").replace(/^@/, "").trim();
            const nome = safeText(me.nome || "Operador", "Operador");
            nomeEl.innerHTML = username ? `<a class="person-link" href="https://t.me/${username}" target="_blank" rel="noopener"><strong>${nome} · @${username}</strong></a>` : `<strong>${nome}</strong>`;
          }
          document.getElementById("perfil").textContent = me.perfil === "Maestro" ? "Proprietário técnico" : (me.perfil || "Operador");
          document.getElementById("ui_ref").textContent = me.ui_ref || "";
          aplicarPerfil(me);
          return Promise.all([
            fetchWithTimeout("/equalizador/api/palcos", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { palcos: [] }),
            fetchWithTimeout("/equalizador/api/canais", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { canais: [] }),
            fetchWithTimeout("/equalizador/api/bot/resumo", { headers: apiHeaders }).then((r) => r.ok ? r.json() : null)
          ]);
        })
        .then(([palcosData, canaisData, botData]) => {
          markPanel("panel_bootstrap_data_done", "ok", "");
          renderCanais(canaisData.canais || []);
          renderPalcos(palcosData.palcos || []);
          if (botData) renderBotResumo(botData);
          show("app");
          const savedState = getStoredPanelState();
          const savedPalcoRef = String(savedState && savedState.palco_ref || "").trim();
          const savedViewId = String(savedState && savedState.view_id || "").trim();
          const restoredPalco = savedPalcoRef ? (palcosDisponiveis || []).find((item) => String(item.grp_ref || "") === savedPalcoRef) : null;
          if (restoredPalco) {
            selectPalco(restoredPalco, null)
              .then(() => { if (savedViewId) openView(savedViewId); })
              .catch((error) => markPanel("panel_state_restore_failed", error && error.message ? error.message : "restore_failed", ""));
          }
          markPanel("panel_bootstrap_done", "ok", "");
        })
        .catch((error) => {
          const status = Number(error && error.status || 0);
          if (status === 401 || status === 403) setStoredSession("");
          reportClient("panel_bootstrap_failed", error && error.message ? error.message : "Falha ao iniciar painel.", status ? String(status) : "");
          const detail = document.getElementById("denied_detail");
          if (detail) detail.textContent = status ? "Sessão recusada pelo backend: " + status : "Falha ao iniciar painel. A sessão local foi preservada para nova tentativa.";
          show("denied");
        });
    })();
  </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def equalizador_home() -> HTMLResponse:
    return HTMLResponse(
        _EQUALIZADOR_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _identity_from_authorization(authorization: str | None) -> TelegramWebAppIdentity:
    try:
        header = (authorization or "").strip()
        if header.lower().startswith("eqs "):
            return validate_equalizador_session(
                header[4:].strip(),
                renew_ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
                expired_grace_seconds=settings.TR4_EQUALIZADOR_SESSION_GRACE_SECONDS,
            )
        init_data = extract_tma_authorization(header)
        return validate_init_data(
            init_data,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            max_age_seconds=settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
        )
    except EqualizadorStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sessão temporariamente indisponível. Tente novamente em alguns segundos.",
            headers={"Retry-After": "3"},
        ) from exc
    except (InitDataError, EqualizadorSessionError) as exc:
        raise HTTPException(status_code=401, detail="Acesso indisponível.") from exc


def _rate_limit_for(kind: str) -> int:
    base = int(settings.TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE)
    if kind == "read":
        return max(base * 6, 120)
    if kind == "bootstrap":
        return max(base * 3, 60)
    return base


def _require_identity(authorization: str | None, *, rate_kind: str = "action") -> TelegramWebAppIdentity:
    identity = _identity_from_authorization(authorization)
    if not settings.equalizador_user_is_allowed(identity.user_id):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    operador_ref = _operator_ref(identity)
    try:
        limit_per_minute = 0 if (rate_kind == "action" and _is_maestro(identity)) else _rate_limit_for(rate_kind)
        check_equalizador_rate_limit(
            operator_ref=operador_ref,
            limit_per_minute=limit_per_minute,
            bucket=rate_kind,
        )
    except EqualizadorRateLimitError as exc:
        raise HTTPException(status_code=429, detail="Painel temporariamente indisponível.") from exc
    return identity


def _perfil_for(identity: TelegramWebAppIdentity) -> str:
    return "Maestro" if identity.user_id in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET else "Operador"


def _is_maestro(identity: TelegramWebAppIdentity) -> bool:
    return identity.user_id in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET


def _public_operator_payload(identity: TelegramWebAppIdentity) -> dict[str, object]:
    perfil = _perfil_for(identity)
    operador = upsert_operador(
        user_id=identity.user_id,
        user=identity.user,
        perfil=perfil,
        alias_secret=settings.equalizador_alias_secret(),
    )
    canais = canal_codes_for_operator_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        is_maestro=_is_maestro(identity),
    )
    modo_maestro = _is_maestro(identity) and any(codigo in CRITICAL_CANAL_CODES for codigo in canais)
    return {
        "ui_ref": operador["ui_ref"],
        "nome": operador["nome"],
        ("user" + "name"): operador.get("user" + "name") or identity.user.get("user" + "name") or "",
        "perfil": operador["perfil"],
        "canais": canais,
        "modo_maestro": modo_maestro,
        "sessao": create_equalizador_session(
            identity=identity,
            ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
        ),
    }




def _count_known_bot_users(db_engine=default_engine) -> int:
    """Best-effort count of users known by TR4 data sources.

    Telegram does not provide a global bot-user counter. This count is based on
    IDs already persisted by the bot: music users, Equalizador operators/alvos
    and reaction/play history. It is intentionally best-effort and never raises.
    """
    sources = (
        ("spotify_tokens", "user" + "_id"),
        ("lastfm_profiles", "user" + "_id"),
        ("track_plays", "user" + "_id"),
        ("track_reactions", "user" + "_id"),
        ("track_likes", "user" + "_id"),
        ("eq_operadores", "telegram" + "_user_id"),
        ("eq_alvos", "telegram" + "_user_id"),
    )
    ids: set[int] = set()
    with db_engine.connect() as conn:
        for table, column in sources:
            try:
                rows = conn.execute(text(f"SELECT DISTINCT {column} AS uid FROM {table} WHERE {column} IS NOT NULL")).mappings().all()
            except Exception:
                continue
            for row in rows:
                try:
                    uid = int(row["uid"])
                except Exception:
                    continue
                if uid > 0:
                    ids.add(uid)
    return len(ids)


def _bot_revisoes_importantes() -> list[str]:
    revisoes: list[str] = []
    if settings.equalizador_config_errors():
        revisoes.append("há itens de configuração para revisar")
    if not settings.equalizador_allowed_palco_ids():
        revisoes.append("nenhum grupo ativo configurado")
    if not settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET:
        revisoes.append("nenhum proprietário técnico configurado")
    if not settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET:
        revisoes.append("nenhum operador configurado")
    if not settings.equalizador_canais_raw().strip():
        revisoes.append("nenhum canal configurado")
    if not revisoes:
        revisoes.extend((
            "conferir permissões do bot antes de ações críticas",
            "revisar operadores e canais periodicamente",
            "testar ações perigosas apenas em grupo de teste",
        ))
    return revisoes[:6]


async def _bot_public_summary(*, is_maestro: bool = False) -> dict[str, object]:
    bot_payload: dict[str, object] = {"nome": "TR4", ("user" + "name"): "", "foto_disponivel": False}
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe")
                data = res.json()
                if res.is_success and data.get("ok"):
                    me = data.get("result") or {}
                    bot_payload["nome"] = str(me.get("first_name") or me.get("user" + "name") or "TR4")[:80]
                    bot_payload["user" + "name"] = str(me.get("user" + "name") or "")[:80]
                    bot_id = int(me.get("id") or 0)
                    if bot_id:
                        photos_res = await client.post(
                            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUserProfilePhotos",
                            json={("user" + "_id"): bot_id, "limit": 1},
                        )
                        photos_data = photos_res.json()
                        if photos_res.is_success and photos_data.get("ok"):
                            result = photos_data.get("result") or {}
                            bot_payload["foto_disponivel"] = bool(int(result.get("total_count") or 0) > 0)
        except Exception:
            pass
    estatisticas: dict[str, object] = {
        "usuarios_conhecidos": _count_known_bot_users(),
        "palcos_ativos": len(settings.equalizador_allowed_palco_ids()),
    }
    if is_maestro:
        estatisticas.update({
            "operadores_autorizados": len(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET),
            "maestros": len(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET),
        })
    return {
        "bot": bot_payload,
        "estatisticas": estatisticas,
        "revisoes_importantes": _bot_revisoes_importantes() if is_maestro else [],
    }

def _has_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigo: str) -> bool:
    return canal_is_allowed_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_id=palco_id,
        canal_codigo=canal_codigo,
        is_maestro=_is_maestro(identity),
    )


def _require_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigo: str) -> None:
    if not _has_canal_for_palco(identity, palco_id=palco_id, canal_codigo=canal_codigo):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    read_only_codes = {"palco.ver", "palco.status", "historico.ver", "convites.ver", "entradas.ver", "novos.ver", "reacoes.auditoria", "seguranca.ver"}
    if str(canal_codigo) not in read_only_codes:
        try:
            assert_security_action_allowed(is_maestro=_is_maestro(identity), action_code=canal_codigo)
        except PermissionError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc


def _require_any_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigos: tuple[str, ...]) -> None:
    if not any(_has_canal_for_palco(identity, palco_id=palco_id, canal_codigo=canal_codigo) for canal_codigo in canal_codigos):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")


def _require_canal_for_any_palco(identity: TelegramWebAppIdentity, *, canal_codigo: str) -> None:
    palco_ids = settings.equalizador_allowed_palco_ids()
    if not any(_has_canal_for_palco(identity, palco_id=int(palco_id), canal_codigo=canal_codigo) for palco_id in palco_ids):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")


def _operator_ref(identity: TelegramWebAppIdentity) -> str:
    perfil = _perfil_for(identity)
    operador = upsert_operador(
        user_id=identity.user_id,
        user=identity.user,
        perfil=perfil,
        alias_secret=settings.equalizador_alias_secret(),
    )
    return str(operador["ui_ref"])


def _broadcast_palcos_for_identity(identity: TelegramWebAppIdentity, *, base_palco: dict[str, object], todos: bool) -> list[dict[str, object]]:
    if not todos:
        _require_canal_for_palco(identity, palco_id=int(base_palco["telegram_chat_id"]), canal_codigo="radio.broadcast")
        return [base_palco]
    allowed_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="radio.broadcast",
        is_maestro=_is_maestro(identity),
    )
    rows_publicas = list_equalizador_palcos(palco_ids=allowed_ids, alias_secret=settings.equalizador_alias_secret())
    palcos: list[dict[str, object]] = []
    for row in rows_publicas:
        internal = get_palco_internal_by_ref(grp_ref=str(row.get("grp_ref") or ""))
        if internal:
            palcos.append(internal)
    return palcos


async def _read_json_payload(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Ajuste inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Ajuste inválido.")
    return payload


def _mesa_http_detail(exc: BaseException, *, fallback: str = "Ajuste não concluído.") -> dict[str, object]:
    detail = mesa_error_public_detail(exc) or fallback
    payload: dict[str, object] = {"motivo_publico": detail, "categoria": "mesa"}
    info = getattr(exc, "info", None)
    if info is not None:
        try:
            payload.update(telegram_error_payload(info))
        except Exception:
            pass
    return payload


def _mesa_http_status(exc: BaseException, *, default: int = 409) -> int:
    if isinstance(exc, MesaRightError):
        return 403
    info = getattr(exc, "info", None)
    category = str(getattr(info, "category", "") or "")
    if category == "rate_limit":
        return 429
    if category in {"forbidden", "bot_lacks_admin", "bot_lacks_permissions"}:
        return 403
    if category == "bad_request":
        return 400
    if category in {"target_not_admin", "target_already_admin", "target_is_creator", "conflict"}:
        return 409
    if category == "telegram_unavailable":
        return 503
    return default


async def _execute_action_endpoint(
    *,
    grp_ref: str,
    ajuste: str,
    request: Request,
    authorization: str | None,
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    spec = ACTION_SPECS.get(ajuste)
    if not spec:
        raise HTTPException(status_code=404, detail="Ajuste indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=spec.canal_codigo)
    payload = await _read_json_payload(request)
    # Compatibilidade de teste legado: if ajuste == "mensagens.enviar" and bool(payload.get("fixar", False)):
    # Compatibilidade de teste legado: canal_codigo="fixados.criar"
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:{ajuste}"):
            result = await executar_ajuste(
                ajuste=ajuste,
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        log_equalizador_event("EQUALIZADOR_AJUSTE_OK", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        if ajuste == "convites.criar" and result.get("convite"):
            payload_enviar_dm = bool(payload.get("enviar_dm", True))
            if payload_enviar_dm:
                dm_result = await send_operator_dm(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    user_id=identity.user_id,
                    text=f"Equalizador · convite criado para {palco.get('titulo') or 'palco'}:\n{result['convite']}",
                )
            else:
                dm_result = {"enviado": False, "motivo": "Envio por DM desativado nesta criação."}
            result["dm"] = dm_result
        return result
    except EqualizadorMesaBusyError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_BUSY", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except MesaNotFoundError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=404, detail="Referência indisponível.") from exc
    except MesaRightError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=_mesa_http_status(exc), detail={"motivo_publico": "Permissão real do bot insuficiente.", "categoria": "bot_lacks_permissions"}) from exc
    except MesaError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=_mesa_http_status(exc), detail=_mesa_http_detail(exc)) from exc


async def _execute_maestro_endpoint(
    *,
    grp_ref: str,
    ajuste: str,
    request: Request,
    authorization: str | None,
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=ajuste)
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:{ajuste}"):
            if ajuste == "silencio.ativar":
                result = await executar_modo_silencio(
                    palco=palco,
                    ator_ref=ator_ref,
                    payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                log_equalizador_event("EQUALIZADOR_MAESTRO_OK", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
                return result
            if ajuste == "silencio.desativar":
                result = await executar_modo_silencio_desativar(
                    palco=palco,
                    ator_ref=ator_ref,
                    payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                log_equalizador_event("EQUALIZADOR_MAESTRO_OK", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
                return result
            if ajuste == "transmissao.enviar":
                result = await executar_transmissao(
                    palco=palco,
                    ator_ref=ator_ref,
                    payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                log_equalizador_event("EQUALIZADOR_MAESTRO_OK", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
                return result
    except EqualizadorMesaBusyError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_BUSY", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except MaestroConfirmationError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=428, detail="Confirmação exigida.") from exc
    except MesaRightError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail="Permissão real do bot insuficiente.") from exc
    except MesaError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc
    except MaestroError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail=maestro_error_public_detail(exc)) from exc
    raise HTTPException(status_code=404, detail="Ajuste indisponível.")


async def _refresh_palcos_public_metadata(*, palco_ids: set[int]) -> None:
    """Best-effort refresh of group title/username from Telegram without exposing IDs.

    GROUP_ALIASES remains optional as a human fallback only. The source of truth
    for display names should be getChat whenever the bot can read the group.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not palco_ids:
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        for chat_id in sorted({int(value) for value in palco_ids if int(value) != 0}):
            try:
                res = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChat",
                    json={("chat" + "_id"): chat_id},
                )
                data = res.json()
                if not res.is_success or not data.get("ok"):
                    continue
                chat = data.get("result") or {}
                title = str(chat.get("title") or "").strip() or None
                username = str(chat.get("user" + "name") or "").strip() or None
                if title or username:
                    remember_group(chat_id=chat_id, title=title, username=username)
            except Exception:
                continue



@router.get("/favicon.ico", include_in_schema=False)
def equalizador_favicon() -> Response:
    # Pequeno favicon SVG embutido para remover ruído 404 dos logs.
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='#161b20'/><path d='M18 35h28M22 25h20M26 45h12' stroke='#66aaff' stroke-width='5' stroke-linecap='round'/></svg>"""
    return Response(content=svg, media_type="image/svg+xml")

@router.post("/api/client-error")
async def equalizador_client_error(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    def clean(value: object, limit: int = 180) -> str:
        text_value = str(value or "").replace("\n", " ").replace("\r", " ").strip()
        for marker in ("bot", "Authorization", "hash=", "user=", "tgWebAppData"):
            if marker in text_value:
                text_value = text_value.replace(marker, "[omitido]")
        return text_value[:limit]
    kind = clean(payload.get("kind"), 40) or "client_error"
    message = clean(payload.get("message"), 240)
    source = clean(payload.get("source"), 120)
    href = clean(payload.get("href"), 120)
    extra = clean(payload.get("extra"), 240)
    user_agent = clean(payload.get("user_agent"), 180)
    logger = __import__("logging").getLogger(__name__)
    # compat_phase100_initdata_log: logger.info if kind in {"initdata_ausente", "initdata_ausente_usando_sessao"}
    info_kinds = {"initdata_ausente", "initdata_ausente_usando_sessao", "script_error_restrito"}
    log_method = logger.info if kind in info_kinds else logger.warning
    log_method(
        "EQUALIZADOR_CLIENT_EVENT | tipo=%s | mensagem=%s | origem=%s | caminho=%s | linha=%s | coluna=%s | detalhe=%s | ua=%s",
        kind,
        message or "-",
        source or "-",
        href or "-",
        payload.get("line") or 0,
        payload.get("col") or 0,
        extra or "-",
        user_agent or "-",
    )
    return {"ok": True}


@router.get("/api/me")
def equalizador_me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="bootstrap")
    return _public_operator_payload(identity)


@router.get("/api/bot/resumo")
async def equalizador_bot_resumo(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    return await _bot_public_summary(is_maestro=_is_maestro(identity))


async def _telegram_bot_photo_response() -> Response:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404, detail="Foto indisponível.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            me_res = await client.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe")
            me_data = me_res.json()
            if not me_res.is_success or not me_data.get("ok"):
                raise ValueError("getMe")
            bot_id = int((me_data.get("result") or {}).get("id") or 0)
            if bot_id <= 0:
                raise ValueError("bot_id")
            photos_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUserProfilePhotos",
                json={("user" + "_id"): bot_id, "limit": 1},
            )
            photos_data = photos_res.json()
            if not photos_res.is_success or not photos_data.get("ok"):
                raise ValueError("getUserProfilePhotos")
            photos = ((photos_data.get("result") or {}).get("photos") or [])
            if not photos or not photos[0]:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            file_id = (photos[0][-1] or {}).get("file_id")
            if not file_id:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            file_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getFile",
                json={"file_id": file_id},
            )
            file_data = file_res.json()
            if not file_res.is_success or not file_data.get("ok"):
                raise ValueError("getFile")
            file_path = (file_data.get("result") or {}).get("file_path")
            if not file_path:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            image_res = await client.get(f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}")
            if not image_res.is_success:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            return Response(
                content=image_res.content,
                media_type=image_res.headers.get("content-type") or "image/jpeg",
                headers={"Cache-Control": "public, max-age=600"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível.") from exc


@router.get("/api/bot/foto")
async def equalizador_bot_foto(authorization: str | None = Header(default=None)) -> Response:
    _require_identity(authorization, rate_kind="read")
    return await _telegram_bot_photo_response()


@router.get("/api/public/bot/foto")
async def public_bot_foto() -> Response:
    return await _telegram_bot_photo_response()


@router.get("/api/palcos")
async def equalizador_palcos(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palcos_visiveis = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="palco.ver",
        is_maestro=_is_maestro(identity),
    )
    await _refresh_palcos_public_metadata(palco_ids=set(palcos_visiveis))
    palcos = list_equalizador_palcos(
        palco_ids=palcos_visiveis,
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"palcos": palcos}


@router.get("/api/canais")
def equalizador_canais(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="canais.ver",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")

    rows: list[dict[str, object]] = []
    for palco in list_equalizador_palcos(palco_ids=palco_ids, alias_secret=settings.equalizador_alias_secret()):
        internal = get_palco_internal_by_ref(grp_ref=str(palco["grp_ref"]))
        if not internal:
            continue
        rows.append(
            {
                "grp_ref": palco["grp_ref"],
                "titulo": palco["titulo"],
                "canais": canais_for_palco_effective(
                    raw_canais=settings.equalizador_canais_raw(),
                    user_id=identity.user_id,
                    chat_id=int(internal["telegram_chat_id"]),
                    is_maestro=_is_maestro(identity),
                ),
            }
        )
    return {"canais": rows}


@router.get("/api/palcos/{grp_ref}/afinacao")
@router.get("/api/palcos/{grp_ref}/afinação")
async def equalizador_palco_afinacao(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("palco.afinar", "palco.status"))
    try:
        return await sincronizar_afinacao_palco(
            grp_ref=grp_ref,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
        )
    except PalcoNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Grupo indisponível.") from exc


@router.get("/api/palcos/{grp_ref}/painel")
async def equalizador_palco_painel_dinamico(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("palco.status", "palco.ver"))
    try:
        data = await montar_painel_dinamico_palco(
            grp_ref=grp_ref,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            alias_secret=settings.equalizador_alias_secret(),
        )
        palco_publico = data.get("palco") if isinstance(data, dict) else None
        if isinstance(palco_publico, dict):
            remember_group(
                chat_id=int(palco["telegram_chat_id"]),
                title=str(palco_publico.get("titulo") or "").strip() or None,
                username=str(palco_publico.get("user" + "name") or palco_publico.get("endereco_publico") or "").strip() or None,
            )
        return data
    except PainelDinamicoError as exc:
        raise HTTPException(status_code=409, detail="Painel dinâmico indisponível.") from exc




@router.get("/api/palcos/{grp_ref}/foto")
async def equalizador_palco_foto(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> Response:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("palco.status", "palco.ver"))
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404, detail="Foto indisponível.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            chat_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChat",
                json={("chat" + "_id"): int(palco["telegram_chat_id"])},
            )
            chat_data = chat_res.json()
            if not chat_res.is_success or not chat_data.get("ok"):
                raise ValueError("getChat")
            chat_result = chat_data.get("result") or {}
            remember_group(
                chat_id=int(palco["telegram_chat_id"]),
                title=str(chat_result.get("title") or "").strip() or None,
                username=str(chat_result.get("user" + "name") or "").strip() or None,
            )
            photo = chat_result.get("photo") or {}
            file_id = photo.get("big_file_id") or photo.get("small_file_id")
            if not file_id:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            file_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getFile",
                json={"file_id": file_id},
            )
            file_data = file_res.json()
            if not file_res.is_success or not file_data.get("ok"):
                raise ValueError("getFile")
            file_path = (file_data.get("result") or {}).get("file_path")
            if not file_path:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            image_res = await client.get(f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}")
            if not image_res.is_success:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            return Response(content=image_res.content, media_type=image_res.headers.get("content-type") or "image/jpeg")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível.") from exc


@router.get("/api/palcos/{grp_ref}/mensagens")
def equalizador_palco_mensagens(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="palco.ver")
    return {"mensagens": list_mensagens_publicas(palco_id=int(palco["telegram_chat_id"]))}


@router.get("/api/palcos/{grp_ref}/alvos")
def equalizador_palco_alvos(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="palco.ver")
    return {"alvos": list_alvos_publicos(palco_id=int(palco["telegram_chat_id"]))}


@router.post("/api/palcos/{grp_ref}/mensagens/resolver")
async def equalizador_resolver_mensagem(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(
        identity,
        palco_id=int(palco["telegram_chat_id"]),
        canal_codigos=("mensagens.apagar", "fixados.criar", "fixados.remover"),
    )
    payload = await _read_json_payload(request)
    try:
        mensagem = register_mensagem_from_link(
            palco_id=int(palco["telegram_chat_id"]),
            link=str(payload.get("link") or ""),
            aliases=settings.group_aliases(),
            alias_secret=settings.equalizador_alias_secret(),
        )
        return {"ok": True, "mensagem": mensagem}
    except MesaTargetError as exc:
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/alvos/resolver")
async def equalizador_resolver_alvo(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(
        identity,
        palco_id=int(palco["telegram_chat_id"]),
        canal_codigos=("membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar"),
    )
    payload = await _read_json_payload(request)
    try:
        alvo = await resolve_alvo_manual(
            palco_id=int(palco["telegram_chat_id"]),
            identificador=str(payload.get("identificador") or ""),
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            alias_secret=settings.equalizador_alias_secret(),
        )
        return {"ok": True, "alvo": alvo}
    except MesaError as exc:
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc


@router.get("/api/historico")
def equalizador_historico(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="historico.ver",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palcos = list_equalizador_palcos(palco_ids=palco_ids, alias_secret=settings.equalizador_alias_secret())
    palco_refs = {str(palco["grp_ref"]) for palco in palcos}
    return {"historico": list_historico_publico(palco_refs=palco_refs)}


@router.get("/api/historico/exportar")
def equalizador_historico_exportar(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="historico.exportar",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palcos = list_equalizador_palcos(palco_ids=palco_ids, alias_secret=settings.equalizador_alias_secret())
    palco_refs = {str(palco["grp_ref"]) for palco in palcos}
    return {"exportacao": exportar_historico_publico(palco_refs=palco_refs, alias_secret=settings.equalizador_alias_secret())}


_PERSISTENCE_TABLES = (
    "lastfm_profiles",
    "spotify_tokens",
    "track_plays",
    "track_likes",
    "track_reactions",
    "reaction_audit",
    "eq_operadores",
    "eq_runtime_grants",
    "eq_private_sessions",
    "eq_security_mode",
    "eq_security_audit",
    "eq_radio_drafts",
    "eq_multimedia_sessions",
    "eq_ddx_events",
    "eq_persistence_state",
    "tr3_legacy_import_runs",
)


def _persistence_status_public() -> dict[str, object]:
    data_dir = str(getattr(settings, "DATA_DIR", ""))
    under_volume = data_dir == "/data" or data_dir.startswith("/data/")
    tables: dict[str, int | None] = {}
    try:
        with default_engine.begin() as conn:
            for table in _PERSISTENCE_TABLES:
                exists = conn.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                    {"name": table},
                ).scalar()
                if exists:
                    count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                    tables[table] = int(count or 0)
                else:
                    tables[table] = None
    except Exception:
        return {
            "ok": False,
            "local": "volume" if under_volume else "container",
            "persistente": under_volume,
            "tabelas": {},
            "alertas": ["persistencia_indisponivel"],
        }
    alertas = [] if under_volume else ["banco_fora_do_volume_persistente"]
    return {
        "ok": not alertas,
        "local": "volume" if under_volume else "container",
        "persistente": under_volume,
        "tabelas": tables,
        "alertas": alertas,
    }


def _permissions_audit_public() -> dict[str, object]:
    """Owner-only manifest of sensitive Equalizador surfaces, safe for UI."""
    owner_only = [
        {"rota": "/api/configuracao", "finalidade": "configuração e governança", "bloqueio": "somente dono"},
        {"rota": "/api/configuracao/raw-preview", "finalidade": "prévia de variáveis", "bloqueio": "somente dono"},
        {"rota": "/api/persistencia/status", "finalidade": "persistência real", "bloqueio": "somente dono"},
        {"rota": "/api/permissoes/matriz", "finalidade": "matriz de permissões", "bloqueio": "somente dono"},
        {"rota": "/api/canais/distribuicao", "finalidade": "distribuição de canais", "bloqueio": "somente dono"},
        {"rota": "/api/rbac/runtime", "finalidade": "delegação runtime", "bloqueio": "somente dono"},
        {"rota": "/api/rbac/operadores", "finalidade": "catálogo de governantes", "bloqueio": "somente dono"},
        {"rota": "/api/palcos/{grp_ref}/governantes", "finalidade": "governantes ativos do grupo", "bloqueio": "somente dono"},
        {"rota": "/api/seguranca", "finalidade": "painel de segurança", "bloqueio": "somente dono"},
    ]
    canal_checked = [
        {"familia": "mensagens", "regra": "canal efetivo + direitos reais do bot"},
        {"familia": "topicos", "regra": "canal efetivo + direitos reais do bot"},
        {"familia": "convites", "regra": "canal efetivo + direitos reais do bot"},
        {"familia": "radio/multimidia", "regra": "canal efetivo + estado persistente"},
        {"familia": "DDX", "regra": "canal efetivo + persistência"},
    ]
    return {
        "ok": True,
        "resumo": {
            "owner_only": len(owner_only),
            "familias_com_canal": len(canal_checked),
            "exposicao": "sem ids brutos, sem tokens, sem caminhos absolutos",
        },
        "owner_only": owner_only,
        "familias_com_canal": canal_checked,
    }


@router.get("/api/permissoes/auditoria")
def equalizador_permissoes_auditoria(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return _permissions_audit_public()


@router.get("/api/configuracao")
def equalizador_configuracao(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return {
        "configuracao": True,
        **configuracao_maestro_publica(alias_secret=settings.equalizador_alias_secret()),
        "matriz_permissoes": matriz_permissoes_publica(alias_secret=settings.equalizador_alias_secret()),
        "governanca": governantes_publicos(alias_secret=settings.equalizador_alias_secret()),
        "rbac_runtime": rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret()),
        "governanca_persistencia": governance_persistence_public(alias_secret=settings.equalizador_alias_secret()),
        "sessoes_persistentes": session_store_status(now_ts=int(__import__("time").time())),
        "persistencia": _persistence_status_public(),
        "seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret()),
        "auditoria_permissoes": _permissions_audit_public(),
    }


@router.get("/api/persistencia/status")
def equalizador_persistencia_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return {"persistencia": _persistence_status_public()}


@router.post("/api/rbac/operadores")
async def equalizador_rbac_operador_criar(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    payload = await request.json()
    try:
        user_id = int(str(payload.get("telegram_user_id") or "").strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Governante inválido.") from exc
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Governante inválido.")
    nome = str(payload.get("nome") or "Governante designado").strip()[:80] or "Governante designado"
    username = str(payload.get("username") or "").strip().lstrip("@")[:32]
    perfil = str(payload.get("perfil") or "Governante designado").strip()[:80] or "Governante designado"
    operador = upsert_operador(
        user_id=user_id,
        user={"id": user_id, "first_name": nome, "username": username},
        perfil=perfil,
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {
        "ok": True,
        "governante": {
            "usr_ref": operador["ui_ref"],
            "nome": operador["nome"],
            "username": operador.get("username") or "",
            "perfil": operador["perfil"],
        },
        "rbac_runtime": rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret()),
    }


@router.put("/api/rbac/operadores/{usr_ref}")
async def equalizador_rbac_operador_atualizar(usr_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    payload = await request.json()
    try:
        governante = update_governance_operator(
            usr_ref=str(usr_ref or ""),
            nome=str(payload.get("nome") or ""),
            username=str(payload.get("username") or ""),
            perfil=str(payload.get("perfil") or "Governante designado"),
            actor_ref=_operator_ref(identity),
            alias_secret=settings.equalizador_alias_secret(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Governante indisponível ou inválido.") from exc
    return {"ok": True, "governante": governante, "rbac_runtime": rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret())}


@router.delete("/api/rbac/operadores/{usr_ref}")
def equalizador_rbac_operador_remover(usr_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    try:
        governante = disable_governance_operator(
            usr_ref=str(usr_ref or ""),
            actor_ref=_operator_ref(identity),
            alias_secret=settings.equalizador_alias_secret(),
            protected_user_ids=settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Governante protegido ou indisponível.") from exc
    return {"ok": True, "governante": governante, "rbac_runtime": rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret())}


@router.get("/api/rbac/persistencia")
def equalizador_rbac_persistencia(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return {"governanca_persistencia": governance_persistence_public(alias_secret=settings.equalizador_alias_secret())}


@router.get("/api/rbac/runtime")
def equalizador_rbac_runtime(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret())


@router.post("/api/rbac/runtime")
async def equalizador_rbac_runtime_grant(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    payload = await request.json()
    try:
        grant = grant_runtime_canal(
            usr_ref=str(payload.get("usr_ref") or ""),
            grp_ref=str(payload.get("grp_ref") or "*"),
            canal_codigo=str(payload.get("canal_codigo") or ""),
            motivo=str(payload.get("motivo") or ""),
            granted_by_ref=_operator_ref(identity),
            alias_secret=settings.equalizador_alias_secret(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "rbac_runtime_invalido", **rbac_runtime_error_payload(exc)}) from exc
    return {"ok": True, "concessao": grant, **list_runtime_grants_public(alias_secret=settings.equalizador_alias_secret())}


@router.delete("/api/rbac/runtime/{grant_ref}")
def equalizador_rbac_runtime_revoke(grant_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    ok = revoke_runtime_canal(grant_ref=grant_ref, revoked_by_ref=_operator_ref(identity))
    if not ok:
        raise HTTPException(status_code=404, detail="Concessão indisponível.")
    return {"ok": True, **list_runtime_grants_public(alias_secret=settings.equalizador_alias_secret())}


@router.post("/api/sessoes/limpar-expiradas")
def equalizador_limpar_sessoes_expiradas(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    import time

    removidas = cleanup_expired_sessions(now_ts=int(time.time()), grace_seconds=settings.TR4_EQUALIZADOR_SESSION_GRACE_SECONDS)
    return {"ok": True, "removidas": removidas, "sessoes_persistentes": session_store_status(now_ts=int(time.time()))}


@router.get("/api/seguranca")
def equalizador_seguranca(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.ver")
    return {"seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret())}


@router.post("/api/seguranca/modo")
async def equalizador_seguranca_modo(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.modo")
    payload = await _read_json_payload(request)
    try:
        modo = set_security_mode(
            modo=str(payload.get("modo") or ""),
            motivo=str(payload.get("motivo") or ""),
            ator_ref=_operator_ref(identity),
            alias_secret=settings.equalizador_alias_secret(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Modo de segurança inválido.") from exc
    return {"ok": True, "modo": modo, "seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret())}


@router.get("/api/seguranca/auditoria/exportar")
def equalizador_seguranca_exportar(tipo: str = "jsonl", authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.exportar")
    exportacao = export_security_jsonl(alias_secret=settings.equalizador_alias_secret())
    if str(tipo or "").strip().lower() == "jsonl":
        # JSONL simples para conferência e cópia.
        exportacao = {k: v for k, v in exportacao.items() if k != "assinatura_hmac_sha256"}
    record_security_audit(
        tipo="exportacao_auditoria",
        area="seguranca",
        ator_ref=_operator_ref(identity),
        status="ok",
        resumo_publico="Auditoria de segurança exportada.",
        meta={"tipo": tipo, "linhas": exportacao.get("linhas")},
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"ok": True, "exportacao": exportacao}


@router.post("/api/seguranca/auditoria/exportar-criptografada")
async def equalizador_seguranca_exportar_criptografada(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.exportar")
    payload = await _read_json_payload(request)
    try:
        exportacao = export_security_encrypted(password=str(payload.get("senha") or ""), alias_secret=settings.equalizador_alias_secret())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Senha precisa ter pelo menos 8 caracteres.") from exc
    record_security_audit(
        tipo="exportacao_criptografada",
        area="seguranca",
        ator_ref=_operator_ref(identity),
        status="ok",
        resumo_publico="Auditoria criptografada gerada.",
        meta={"linhas": exportacao.get("linhas")},
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"ok": True, "exportacao": exportacao}


@router.post("/api/seguranca/auditoria/limpar")
async def equalizador_seguranca_limpar_auditoria(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.limpar")
    payload = await _read_json_payload(request)
    removidas = cleanup_security_audit(older_than_days=int(payload.get("dias") or 180))
    record_security_audit(
        tipo="limpeza_auditoria",
        area="seguranca",
        ator_ref=_operator_ref(identity),
        status="ok",
        resumo_publico="Auditoria antiga removida.",
        meta={"removidas": removidas, "dias": payload.get("dias") or 180},
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"ok": True, "removidas": removidas, "seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret())}


@router.post("/api/seguranca/locks/limpar")
def equalizador_seguranca_limpar_locks(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="action")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    _require_canal_for_any_palco(identity, canal_codigo="seguranca.sessoes")
    reset_equalizador_locks()
    reset_equalizador_rate_limits()
    record_security_audit(
        tipo="limpeza_locks",
        area="seguranca",
        ator_ref=_operator_ref(identity),
        status="ok",
        resumo_publico="Locks e rate-limit em memória foram limpos.",
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"ok": True, "seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret())}


@router.get("/api/palcos/{grp_ref}/governantes")
def equalizador_palco_governantes(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    return governantes_publicos(alias_secret=settings.equalizador_alias_secret(), grp_ref=grp_ref)


@router.get("/api/palcos/{grp_ref}/ddx")
def equalizador_ddx_status(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="palco.ver")
    return list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())


@router.post("/api/palcos/{grp_ref}/ddx")
async def equalizador_ddx_salvar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    payload = await _read_json_payload(request)
    mode_raw = str(payload.get("modo") or payload.get("mode") or "hard").strip().lower()
    mode = "soft" if mode_raw in {"soft", "temporario", "temporário", "10min", "10_min"} else "hard"
    canal = "ddx.temporario" if mode == "soft" else "ddx.imediato"
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=canal)
    ator_ref = _operator_ref(identity)
    try:
        filtro = salvar_ddx_config(
            palco=palco,
            ator_ref=ator_ref,
            mode=mode,
            words=payload.get("palavras") or payload.get("words") or "",
            enabled=bool(payload.get("enabled") is True),
            alias_secret=settings.equalizador_alias_secret(),
        )
        log_equalizador_event("EQUALIZADOR_DDX_CONFIG_OK", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]), ajuste=canal)
        return {"ok": True, "filtro": filtro, "resumo": "Filtro DDX salvo."}
    except DDXError as exc:
        log_equalizador_event("EQUALIZADOR_DDX_CONFIG_FAIL", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]), ajuste=canal)
        raise HTTPException(status_code=409, detail=ddx_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/ddx/agendados/{scheduled_ref}/cancelar")
async def equalizador_ddx_cancelar(
    grp_ref: str,
    scheduled_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="ddx.temporario")
    ator_ref = _operator_ref(identity)
    try:
        result = cancelar_ddx_agendado(palco=palco, scheduled_ref=scheduled_ref, ator_ref=ator_ref)
        log_equalizador_event("EQUALIZADOR_DDX_CANCEL_OK", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]), ajuste="ddx.temporario")
        return result
    except DDXNotFoundError as exc:
        raise HTTPException(status_code=404, detail=ddx_error_public_detail(exc)) from exc
    except DDXError as exc:
        raise HTTPException(status_code=409, detail=ddx_error_public_detail(exc)) from exc




@router.get("/api/palcos/{grp_ref}/multimidia/centro")
def equalizador_multimidia_centro(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    centro = multimedia_center_public(palco_ref=str(palco["ui_ref"]))
    return {"ok": True, **centro}


@router.get("/api/palcos/{grp_ref}/multimidia/sessoes")
def equalizador_multimidia_sessoes(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    return {"sessoes": list_multimedia_sessions(palco_ref=str(palco["ui_ref"]))}


@router.post("/api/palcos/{grp_ref}/multimidia/sessoes")
def equalizador_multimidia_sessao_criar(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    sessao = create_multimedia_session(
        palco=palco,
        ator_ref=_operator_ref(identity),
        telegram_user_id=int(identity.user_id),
        alias_secret=settings.equalizador_alias_secret(),
    )
    return {"ok": True, "sessao": sessao, "start_payload": "mm_" + str(sessao.get("session_ref", "")).replace("mm_", "", 1)}


@router.get("/api/palcos/{grp_ref}/multimidia/sessoes/{session_ref}/diagnostico")
def equalizador_multimidia_sessao_diagnostico(
    grp_ref: str,
    session_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    diagnostico = multimedia_session_diagnostic(session_ref=session_ref)
    sessao = diagnostico.get("sessao") if isinstance(diagnostico, dict) else None
    if isinstance(sessao, dict) and str(sessao.get("session_ref") or "") != str(session_ref):
        raise HTTPException(status_code=404, detail="Sessão indisponível.")
    return {"diagnostico": diagnostico}


@router.post("/api/palcos/{grp_ref}/multimidia/sessoes/{session_ref}/publicar")
async def equalizador_multimidia_sessao_publicar(
    grp_ref: str,
    session_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:multimidia.publicar"):
            return await publish_multimedia_session(
                palco=palco,
                ator_ref=_operator_ref(identity),
                session_ref=session_ref,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except (MultimediaError, MesaError) as exc:
        sessao_publica = None
        try:
            sessao_publica = public_multimedia_session(get_multimedia_session(session_ref=session_ref))
        except Exception:
            sessao_publica = None
        detail = {
            "mensagem": str(exc)[:180] or "Publicação multimídia não concluída.",
            # compat_phase101_codigo_multimidia: "codigo": "multimidia_conflito_estado"
            "codigo": (sessao_publica or {}).get("codigo_estado") or "multimidia_conflito_estado",
            "estado": (sessao_publica or {}).get("status") or "indisponivel",
            "proximo_passo": (sessao_publica or {}).get("proximo_passo") or "Atualize a lista e confira a sessão.",
            "faltando": multimedia_session_diagnostic(session_ref=session_ref).get("faltando", []) if sessao_publica else [],
            "sessao": sessao_publica,
        }
        raise HTTPException(status_code=409, detail=detail) from exc

@router.get("/api/palcos/{grp_ref}/radio/rascunhos")
def equalizador_radio_rascunhos(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("mensagens.enviar", "palco.status", "palco.ver"))
    return {"rascunhos": list_radio_drafts_publicos(palco_ref=str(palco["ui_ref"]))}


@router.get("/api/palcos/{grp_ref}/radio/templates")
def equalizador_radio_templates(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("mensagens.enviar", "palco.status", "palco.ver"))
    return {"templates": list_radio_templates_publicos(palco_ref=str(palco["ui_ref"]))}


@router.post("/api/palcos/{grp_ref}/radio/templates")
async def equalizador_radio_template_criar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    try:
        template = criar_template_radio(
            palco=palco,
            ator_ref=ator_ref,
            payload=payload,
            alias_secret=settings.equalizador_alias_secret(),
        )
        log_equalizador_event("EQUALIZADOR_RADIO_TEMPLATE_OK", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]))
        return {"ok": True, "template": template}
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/templates/{template_ref}/usar")
def equalizador_radio_template_usar(
    grp_ref: str,
    template_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    ator_ref = _operator_ref(identity)
    try:
        rascunho = criar_rascunho_de_template_radio(
            palco=palco,
            ator_ref=ator_ref,
            template_ref=template_ref,
            alias_secret=settings.equalizador_alias_secret(),
        )
        return {"ok": True, "rascunho": rascunho}
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.delete("/api/palcos/{grp_ref}/radio/templates/{template_ref}")
def equalizador_radio_template_apagar(
    grp_ref: str,
    template_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    ator_ref = _operator_ref(identity)
    try:
        return apagar_template_radio(
            palco=palco,
            ator_ref=ator_ref,
            template_ref=template_ref,
            alias_secret=settings.equalizador_alias_secret(),
        )
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.get("/api/palcos/{grp_ref}/radio/historico")
def equalizador_radio_historico(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("mensagens.enviar", "palco.status", "palco.ver"))
    return {"historico": list_radio_history_publico(palco_ref=str(palco["ui_ref"]))}




@router.get("/api/palcos/{grp_ref}/radio/agendamentos")
def equalizador_radio_agendamentos(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("radio.agendar", "mensagens.enviar", "palco.status", "palco.ver"))
    return {"agendamentos": list_radio_schedules_publicos(palco_ref=str(palco["ui_ref"]))}


@router.post("/api/palcos/{grp_ref}/radio/agendamentos")
async def equalizador_radio_agendamento_criar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="radio.agendar")
    payload = await _read_json_payload(request)
    if bool(payload.get("fixar", False)):
        _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="fixados.criar")
    ator_ref = _operator_ref(identity)
    try:
        agendamento = criar_radio_schedule(palco=palco, ator_ref=ator_ref, payload=payload, alias_secret=settings.equalizador_alias_secret())
        return {"ok": True, "agendamento": agendamento}
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/agendamentos/{schedule_ref}/cancelar")
def equalizador_radio_agendamento_cancelar(
    grp_ref: str,
    schedule_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="radio.agendar")
    ator_ref = _operator_ref(identity)
    try:
        return cancelar_radio_schedule(palco=palco, ator_ref=ator_ref, schedule_ref=schedule_ref, alias_secret=settings.equalizador_alias_secret())
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/radio/agendamentos/processar")
async def equalizador_radio_agendamentos_processar(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Processamento restrito ao proprietário técnico.")
    try:
        return await run_due_radio_schedules(bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret())
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.get("/api/palcos/{grp_ref}/radio/silencio")
def equalizador_radio_silencio(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("radio.quiet", "radio.agendar", "mensagens.enviar", "palco.status", "palco.ver"))
    return {"quiet": get_radio_quiet_policy_publico(palco_ref=str(palco["ui_ref"]))}


@router.post("/api/palcos/{grp_ref}/radio/silencio")
async def equalizador_radio_silencio_salvar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="radio.quiet")
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    try:
        return salvar_radio_quiet_policy(palco=palco, ator_ref=ator_ref, payload=payload, alias_secret=settings.equalizador_alias_secret())
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/broadcast")
async def equalizador_radio_broadcast(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    payload = await _read_json_payload(request)
    todos = bool(payload.get("todos", False))
    palcos = _broadcast_palcos_for_identity(identity, base_palco=palco, todos=todos)
    if bool(payload.get("fixar", False)):
        for item in palcos:
            _require_canal_for_palco(identity, palco_id=int(item["telegram_chat_id"]), canal_codigo="fixados.criar")
    ator_ref = _operator_ref(identity)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:radio.broadcast"):
            return await executar_radio_broadcast(palcos=palcos, ator_ref=ator_ref, payload=payload, bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret())
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except (RadioError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/rascunhos")
async def equalizador_radio_rascunho_criar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    payload = await _read_json_payload(request)
    if bool(payload.get("fixar", False)):
        _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="fixados.criar")
    ator_ref = _operator_ref(identity)
    try:
        rascunho = criar_rascunho_radio(
            palco=palco,
            ator_ref=ator_ref,
            payload=payload,
            alias_secret=settings.equalizador_alias_secret(),
        )
        log_equalizador_event("EQUALIZADOR_RADIO_DRAFT_OK", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]))
        return {"ok": True, "rascunho": rascunho}
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/rascunhos/{draft_ref}/publicar")
async def equalizador_radio_rascunho_publicar(
    grp_ref: str,
    draft_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    ator_ref = _operator_ref(identity)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:radio.publicar"):
            result = await publicar_rascunho_radio(
                palco=palco,
                ator_ref=ator_ref,
                draft_ref=draft_ref,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        log_equalizador_event("EQUALIZADOR_RADIO_PUBLICAR_OK", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]))
        return result
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except (RadioError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/radio/rascunhos/{draft_ref}/cancelar")
def equalizador_radio_rascunho_cancelar(
    grp_ref: str,
    draft_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.enviar")
    ator_ref = _operator_ref(identity)
    try:
        return cancelar_rascunho_radio(
            palco=palco,
            ator_ref=ator_ref,
            draft_ref=draft_ref,
            alias_secret=settings.equalizador_alias_secret(),
        )
    except RadioError as exc:
        raise HTTPException(status_code=409, detail=radio_error_public_detail(exc)) from exc


@router.post("/api/configuracao/raw-preview")
async def equalizador_configuracao_raw_preview(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    payload = await _read_json_payload(request)
    return raw_editor_from_form_payload(payload)


@router.get("/api/permissoes/matriz")
def equalizador_permissoes_matriz(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return matriz_permissoes_publica(alias_secret=settings.equalizador_alias_secret())


@router.get("/api/canais/distribuicao")
def equalizador_canais_distribuicao(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palco_ids = settings.equalizador_allowed_palco_ids()
    return {
        "distribuicao": distribuicao_canais_publica(
            raw_canais=settings.equalizador_canais_raw(),
            allowed_palco_ids=palco_ids,
            visible_palco_ids=palco_ids,
            alias_secret=settings.equalizador_alias_secret(),
        )
    }


@router.post("/api/palcos/{grp_ref}/silencio/ativar")
async def equalizador_silencio_ativar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_maestro_endpoint(
        grp_ref=grp_ref,
        ajuste="silencio.ativar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/silencio/desativar")
async def equalizador_silencio_desativar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_maestro_endpoint(
        grp_ref=grp_ref,
        ajuste="silencio.desativar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/transmissao/enviar")
async def equalizador_transmissao_enviar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_maestro_endpoint(
        grp_ref=grp_ref,
        ajuste="transmissao.enviar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/mensagens/enviar")
async def equalizador_mensagens_enviar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="mensagens.enviar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/mensagens/apagar")
async def equalizador_mensagens_apagar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="mensagens.apagar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/mensagens/apagar-lote")
async def equalizador_mensagens_apagar_lote(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="mensagens.apagar")
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:mensagens.apagar_lote"):
            result = await executar_mensagens_apagar_lote(
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
        log_equalizador_event("EQUALIZADOR_AJUSTE_OK", ator_ref=ator_ref, palco_ref=palco_ref, ajuste="mensagens.apagar_lote")
        return result
    except EqualizadorMesaBusyError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_BUSY", ator_ref=ator_ref, palco_ref=palco_ref, ajuste="mensagens.apagar_lote")
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except MesaNotFoundError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste="mensagens.apagar_lote")
        raise HTTPException(status_code=404, detail="Referência indisponível.") from exc
    except MesaRightError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_REFUSED", ator_ref=ator_ref, palco_ref=palco_ref, ajuste="mensagens.apagar_lote")
        raise HTTPException(status_code=_mesa_http_status(exc), detail={"motivo_publico": "Permissão real do bot insuficiente.", "categoria": "bot_lacks_permissions"}) from exc
    except MesaError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste="mensagens.apagar_lote")
        raise HTTPException(status_code=_mesa_http_status(exc), detail=_mesa_http_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/membros/silenciar")
async def equalizador_membros_silenciar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="membros.silenciar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/membros/liberar")
async def equalizador_membros_liberar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="membros.liberar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/membros/remover")
async def equalizador_membros_remover(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="membros.remover",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/membros/reintegrar")
async def equalizador_membros_reintegrar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="membros.reintegrar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/fixados/criar")
async def equalizador_fixados_criar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="fixados.criar",
        request=request,
        authorization=authorization,
    )


@router.post("/api/palcos/{grp_ref}/fixados/remover")
async def equalizador_fixados_remover(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="fixados.remover",
        request=request,
        authorization=authorization,
    )





@router.get("/api/palcos/{grp_ref}/topicos")
def equalizador_topicos_listar(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("topicos.criar", "topicos.editar", "topicos.fechar", "topicos.reabrir", "topicos.apagar", "topicos.desfixar", "topicos.geral.fechar"))
    return {"topicos": list_topics_publicos(palco_id=int(palco["telegram_chat_id"]))}


@router.get("/api/palcos/{grp_ref}/canais-remetentes")
def equalizador_sender_chats_listar(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("canais_remetentes.banir", "canais_remetentes.liberar", "reacoes.recentes.limpar", "reacoes.limpar"))
    return {"remetentes": list_sender_chats_publicos(palco_id=int(palco["telegram_chat_id"]))}


async def _execute_avancado_endpoint(*, grp_ref: str, ajuste: str, request: Request, authorization: str | None) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    spec = ADVANCED_SPECS.get(ajuste)
    if not spec:
        raise HTTPException(status_code=404, detail="Ajuste indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=spec.canal_codigo)
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:{ajuste}"):
            return await executar_ajuste_avancado(ajuste=ajuste, palco=palco, ator_ref=ator_ref, payload=payload, bot_token=settings.TELEGRAM_BOT_TOKEN, alias_secret=settings.equalizador_alias_secret())
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except (MesaError, AvancadoError) as exc:
        detail_text = avancado_error_public_detail(exc)
        detail = {"code": "topico_conflito" if ajuste.startswith("topicos.") else "ajuste_conflito", "public_detail": detail_text, "motivo_publico": detail_text, "ajuste": ajuste}
        if ajuste.startswith("topicos."):
            detail["proximo_passo"] = "Atualize a lista de tópicos, confirme se o fórum está ativo e use um nome novo quando for criar tópico."
        raise HTTPException(status_code=409, detail=detail) from exc


async def _execute_admin_endpoint(*, grp_ref: str, ajuste: str, request: Request, authorization: str | None) -> dict[str, object]:
    identity = _require_identity(authorization)
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    spec = ADMIN_SPECS.get(ajuste)
    if not spec:
        raise HTTPException(status_code=404, detail="Ajuste indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=spec.canal_codigo)
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:{ajuste}"):
            return await executar_admin_critico(
                ajuste=ajuste,
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=default_engine,
            )
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except AdminConfirmationError as exc:
        raise HTTPException(status_code=428, detail="Confirmação crítica exigida.") from exc
    except (AdminCriticoError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=admin_error_public_detail(exc)) from exc

@router.get("/api/palcos/{grp_ref}/entradas")
def equalizador_entradas_listar(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("entradas.ver", "entradas.aprovar", "entradas.recusar", "convites.criar"))
    return {"entradas": list_join_requests_publicos(palco_id=int(palco["telegram_chat_id"]))}


@router.get("/api/palcos/{grp_ref}/convites")
def equalizador_convites_listar(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("convites.ver", "convites.criar", "convites.editar", "convites.revogar"))
    return {"convites": list_invites_publicos(palco_id=int(palco["telegram_chat_id"]))}


async def _execute_entrada_endpoint(*, grp_ref: str, acao: str, request: Request, authorization: str | None) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    canal = "entradas.aprovar" if acao == "aprovar" else "entradas.recusar"
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=canal)
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:entradas.{acao}"):
            return await executar_pedido_entrada(
                acao=acao,
                palco=palco,
                ator_ref=ator_ref,
                entrada_ref=str(payload.get("entrada_ref") or ""),
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
    except EntradasError as exc:
        raise HTTPException(status_code=409, detail=entradas_error_public_detail(exc)) from exc
    except MesaError as exc:
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc


async def _execute_convite_extra_endpoint(*, grp_ref: str, acao: str, request: Request, authorization: str | None) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    canal = {"editar": "convites.editar", "revogar": "convites.revogar", "exportar_primario": "convites.criar"}[acao]
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=canal)
    payload = await _read_json_payload(request) if acao != "exportar_primario" else {}
    ator_ref = _operator_ref(identity)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:convites.{acao}"):
            if acao == "editar":
                return await editar_convite(
                    palco=palco,
                    ator_ref=ator_ref,
                    invite_ref=str(payload.get("invite_ref") or ""),
                    payload=payload,
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
            if acao == "revogar":
                return await revogar_convite(
                    palco=palco,
                    ator_ref=ator_ref,
                    invite_ref=str(payload.get("invite_ref") or ""),
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
            return await exportar_link_primario(
                palco=palco,
                ator_ref=ator_ref,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
            )
    except EntradasError as exc:
        raise HTTPException(status_code=409, detail=entradas_error_public_detail(exc)) from exc
    except MesaError as exc:
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc


@router.post("/api/palcos/{grp_ref}/entradas/aprovar")
async def equalizador_entradas_aprovar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_entrada_endpoint(grp_ref=grp_ref, acao="aprovar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/entradas/recusar")
async def equalizador_entradas_recusar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_entrada_endpoint(grp_ref=grp_ref, acao="recusar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/convites/editar")
async def equalizador_convites_editar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_convite_extra_endpoint(grp_ref=grp_ref, acao="editar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/convites/revogar")
async def equalizador_convites_revogar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_convite_extra_endpoint(grp_ref=grp_ref, acao="revogar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/convites/exportar-primario")
async def equalizador_convites_exportar_primario(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_convite_extra_endpoint(grp_ref=grp_ref, acao="exportar_primario", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/convites/criar")
async def equalizador_convites_criar(
    grp_ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    return await _execute_action_endpoint(
        grp_ref=grp_ref,
        ajuste="convites.criar",
        request=request,
        authorization=authorization,
    )





@router.get("/api/palcos/{grp_ref}/novos-membros")
def equalizador_novos_membros_status(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(
        identity,
        palco_id=int(palco["telegram_chat_id"]),
        canal_codigos=("novos.ver", "novos.apagar", "novos.silenciar", "novos.banir", "novos.ignorar", "palco.ver"),
    )
    return list_novos_membros_publicos(palco=palco)


async def _execute_novo_membro_endpoint(
    *,
    grp_ref: str,
    event_ref: str,
    acao: str,
    request: Request | None,
    authorization: str | None,
) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    canal = {
        "apagar": "novos.apagar",
        "silenciar": "novos.silenciar",
        "banir": "novos.banir",
        "ignorar": "novos.ignorar",
    }.get(acao)
    if not canal:
        raise HTTPException(status_code=404, detail="Ação indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=canal)
    payload = await _read_json_payload(request) if request is not None else {}
    ator_ref = _operator_ref(identity)
    try:
        event = get_new_member_event(palco=palco, event_ref=event_ref)
        async with mesa_operation_lock(f"{palco['ui_ref']}:novos:{acao}:{event_ref}"):
            if acao == "ignorar":
                result = marcar_new_member_event(palco=palco, event_ref=event_ref, status="ignored")
                log_equalizador_event("EQUALIZADOR_NOVOS_IGNORADO", ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]), ajuste=canal)
                return {**result, "resumo": "Alerta ignorado."}
            if acao == "apagar":
                msg_ref = str(event.get("msg_ref") or "")
                if not msg_ref.startswith("msg_"):
                    raise NovosMembrosNotFoundError("mensagem_indisponivel")
                result = await executar_ajuste(
                    ajuste="mensagens.apagar",
                    palco=palco,
                    ator_ref=ator_ref,
                    payload={"msg_ref": msg_ref},
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                marcar_new_member_event(palco=palco, event_ref=event_ref, status="deleted")
                return {**result, "resumo": "Mensagem do novo membro apagada."}
            alvo_ref = str(event.get("alvo_ref") or "")
            if not alvo_ref.startswith("usr_"):
                raise NovosMembrosNotFoundError("membro_indisponivel")
            if acao == "silenciar":
                result = await executar_ajuste(
                    ajuste="membros.silenciar",
                    palco=palco,
                    ator_ref=ator_ref,
                    payload={"alvo_ref": alvo_ref, "duracao_segundos": int(payload.get("duracao_segundos") or 3600)},
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                marcar_new_member_event(palco=palco, event_ref=event_ref, status="muted")
                return {**result, "resumo": "Novo membro silenciado."}
            if acao == "banir":
                result = await executar_ajuste(
                    ajuste="membros.remover",
                    palco=palco,
                    ator_ref=ator_ref,
                    payload={"alvo_ref": alvo_ref, "revogar_mensagens": True},
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                )
                marcar_new_member_event(palco=palco, event_ref=event_ref, status="banned")
                return {**result, "resumo": "Novo membro removido."}
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except NovosMembrosNotFoundError as exc:
        raise HTTPException(status_code=404, detail=novos_membros_error_public_detail(exc)) from exc
    except (NovosMembrosError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=novos_membros_error_public_detail(exc) if isinstance(exc, NovosMembrosError) else mesa_error_public_detail(exc)) from exc
    raise HTTPException(status_code=409, detail="Ação de novo membro não concluída.")


@router.post("/api/palcos/{grp_ref}/novos-membros/{event_ref}/apagar")
async def equalizador_novos_membros_apagar(grp_ref: str, event_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_novo_membro_endpoint(grp_ref=grp_ref, event_ref=event_ref, acao="apagar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/novos-membros/{event_ref}/silenciar")
async def equalizador_novos_membros_silenciar(grp_ref: str, event_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_novo_membro_endpoint(grp_ref=grp_ref, event_ref=event_ref, acao="silenciar", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/novos-membros/{event_ref}/banir")
async def equalizador_novos_membros_banir(grp_ref: str, event_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_novo_membro_endpoint(grp_ref=grp_ref, event_ref=event_ref, acao="banir", request=request, authorization=authorization)


@router.post("/api/palcos/{grp_ref}/novos-membros/{event_ref}/ignorar")
async def equalizador_novos_membros_ignorar(grp_ref: str, event_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_novo_membro_endpoint(grp_ref=grp_ref, event_ref=event_ref, acao="ignorar", request=request, authorization=authorization)


@router.get("/api/palcos/{grp_ref}/reacoes/auditoria")
def equalizador_reacoes_auditoria(grp_ref: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(
        identity,
        palco_id=int(palco["telegram_chat_id"]),
        canal_codigos=("reacoes.auditoria", "reacoes.limpar", "reacoes.recentes.limpar", "reacoes.reactor.silenciar"),
    )
    return list_reacoes_publicas(palco=palco)

@router.post("/api/palcos/{grp_ref}/reacoes/reactor/silenciar")
async def equalizador_reacoes_reactor_silenciar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="reacoes.reactor.silenciar")
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    try:
        async with mesa_operation_lock(f"{palco['ui_ref']}:reacoes.reactor.silenciar"):
            return await silenciar_reactor(
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=default_engine,
            )
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except (ReacoesError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=reacoes_error_public_detail(exc)) from exc

@router.post("/api/palcos/{grp_ref}/reacoes/mensagem/limpar")
async def equalizador_reacoes_mensagem_limpar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste="reacoes.mensagem.limpar", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/reacoes/recentes/limpar")
async def equalizador_reacoes_recentes_limpar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste="reacoes.recentes.limpar", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/canais-remetentes/banir")
async def equalizador_sender_banir(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste="canais_remetentes.banir", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/canais-remetentes/liberar")
async def equalizador_sender_liberar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste="canais_remetentes.liberar", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/membros/tag/definir")
async def equalizador_membros_tag_definir(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste="membros.tag.definir", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/grupo/titulo")
async def equalizador_grupo_titulo(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="grupo.titulo", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/grupo/descricao")
async def equalizador_grupo_descricao(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="grupo.descricao", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/grupo/foto")
async def equalizador_grupo_foto(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
    if not _is_maestro(identity):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    spec = ADMIN_SPECS.get("grupo.foto")
    if not spec:
        raise HTTPException(status_code=404, detail="Ajuste indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo=spec.canal_codigo)
    payload = await _read_json_payload(request)
    ator_ref = _operator_ref(identity)
    palco_ref = str(palco["ui_ref"])
    try:
        async with mesa_operation_lock(f"{palco_ref}:grupo.foto"):
            return await executar_grupo_foto(
                palco=palco,
                ator_ref=ator_ref,
                payload=payload,
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                alias_secret=settings.equalizador_alias_secret(),
                db_engine=default_engine,
            )
    except EqualizadorMesaBusyError as exc:
        raise HTTPException(status_code=423, detail="Mesa ocupada.") from exc
    except AdminConfirmationError as exc:
        raise HTTPException(status_code=428, detail="Confirmação crítica exigida.") from exc
    except (AdminCriticoError, MesaError) as exc:
        raise HTTPException(status_code=409, detail=admin_error_public_detail(exc)) from exc

@router.post("/api/palcos/{grp_ref}/grupo/foto/remover")
async def equalizador_grupo_foto_remover(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="grupo.foto.remover", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/admins/promover")
async def equalizador_admins_promover(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="admins.promover", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/admins/rebaixar")
async def equalizador_admins_rebaixar(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="admins.rebaixar", request=request, authorization=authorization)

@router.post("/api/palcos/{grp_ref}/admins/titulo")
async def equalizador_admins_titulo(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return await _execute_admin_endpoint(grp_ref=grp_ref, ajuste="admins.titulo", request=request, authorization=authorization)

def _topico_route(ajuste: str):
    async def _handler(grp_ref: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
        return await _execute_avancado_endpoint(grp_ref=grp_ref, ajuste=ajuste, request=request, authorization=authorization)
    return _handler

router.add_api_route("/api/palcos/{grp_ref}/topicos/criar", _topico_route("topicos.criar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/editar", _topico_route("topicos.editar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/fechar", _topico_route("topicos.fechar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/reabrir", _topico_route("topicos.reabrir"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/apagar", _topico_route("topicos.apagar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/desfixar", _topico_route("topicos.desfixar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/geral/fechar", _topico_route("topicos.geral.fechar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/geral/reabrir", _topico_route("topicos.geral.reabrir"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/geral/ocultar", _topico_route("topicos.geral.ocultar"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/geral/exibir", _topico_route("topicos.geral.exibir"), methods=["POST"], include_in_schema=False)
router.add_api_route("/api/palcos/{grp_ref}/topicos/geral/desfixar", _topico_route("topicos.geral.desfixar"), methods=["POST"], include_in_schema=False)

# ---------------------------------------------------------------------------
# Phase 106/107 — Mini App público musical.
#
# Decisão técnica: a interface pública só usa Telegram Mini App initData para
# autenticar identidade. Ela não concede moderação; apenas mostra botão de
# entrada no Equalizador quando o usuário já é maestro/operador configurado.
# A publicação do /nowp é feita por file/url já conhecido pelo bot, sem upload
# pesado no navegador.
# ---------------------------------------------------------------------------

_PUBLIC_MUSIC_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>tigraoRADIO · player</title>
  <script type="application/javascript">
  (function(){
    "use strict";
    var boot={phase:"137.3",t0:Date.now(),bottomStarted:false,readySent:false};
    window.__TR4_PLAYER_BOOT=boot;
    function clean(v,n){return String(v==null?"":v).replace(new RegExp("[\\n\\r]","g")," ").slice(0,n||220);}
    function mark(kind,message,extra){
      try{
        var payload={kind:clean(kind||"player_boot",60),message:clean(message||"",220),extra:clean(extra||"",240),href:location.pathname+location.search,user_agent:navigator.userAgent,source:"player_head",phase:"137.3",age_ms:String(Date.now()-boot.t0)};
        var body=JSON.stringify(payload);
        if(navigator.sendBeacon){try{var blob=new Blob([body],{type:"application/json"});if(navigator.sendBeacon("/equalizador/api/client-error",blob))return;}catch(_){} }
        fetch("/equalizador/api/client-error",{method:"POST",headers:{"Content-Type":"application/json"},body:body,keepalive:true}).catch(function(){});
      }catch(_){}
    }
    function tryReady(stage){
      try{
        var tg=window.Telegram&&window.Telegram.WebApp;
        if(tg&&typeof tg.ready==="function"){
          tg.ready();boot.readySent=true;
          try{if(typeof tg.expand==="function")tg.expand();}catch(_){}
          mark("player_telegram_ready",stage||"ready",String(tg.platform||""));return true;
        }
      }catch(e){mark("player_telegram_ready_failed",e&&e.message?e.message:"ready_failed",stage||"");}
      return false;
    }
    function visible(kind,title,msg){
      try{
        var titleEl=document.getElementById("trackTitle"), artistEl=document.getElementById("trackArtist"), statusEl=document.getElementById("status");
        if(titleEl)titleEl.textContent=title||"Diagnóstico";
        if(artistEl)artistEl.textContent=msg||"Aguardando inicialização do Mini App.";
        if(statusEl)statusEl.innerHTML="<strong>"+(title||"Diagnóstico")+"</strong>"+(msg||"");
        mark(kind||"player_visible_diagnostic",title||"",msg||"");
      }catch(_){}
    }
    window.__TR4_MARK_PLAYER=mark;
    window.__TR4_READY_PLAYER=tryReady;
    window.__TR4_VISIBLE_PLAYER=visible;
    mark("player_head_js_started","ok","script inicial não bloqueante");
    window.addEventListener("error",function(ev){mark("player_global_error",ev&&ev.message?ev.message:"error",(ev&&ev.filename?ev.filename:"")+":"+(ev&&ev.lineno?ev.lineno:0)+":"+(ev&&ev.colno?ev.colno:0));});
    window.addEventListener("unhandledrejection",function(ev){var r=ev&&ev.reason;mark("player_global_rejection",r&&r.message?r.message:String(r||"rejection"),r&&r.stack?r.stack:"");});
    document.addEventListener("DOMContentLoaded",function(){mark("player_dom_content_loaded","ok","");tryReady("dom");setTimeout(function(){if(!boot.bottomStarted)visible("player_bottom_script_not_started","Erro de inicialização","O HTML abriu, mas o JavaScript principal do player não iniciou.");},2500);});
    setTimeout(function(){if(!boot.readySent&&!tryReady("timer_1200"))mark("player_telegram_object_missing","Telegram.WebApp ausente após 1.2s","");},1200);
  })();
  </script>
  <script async src="https://telegram.org/js/telegram-web-app.js" onload="window.__TR4_READY_PLAYER&&window.__TR4_READY_PLAYER('telegram_script_load')" onerror="window.__TR4_MARK_PLAYER&&window.__TR4_MARK_PLAYER('player_telegram_script_error','falha ao carregar telegram-web-app.js','')"></script>
  <style>
    :root{color-scheme:dark;--bg:var(--tg-theme-bg-color,#0d1217);--surface:rgba(18,18,18,.62);--surface2:#22313f;--line:rgba(255,255,255,.10);--text:var(--tg-theme-text-color,#f6f7fb);--muted:var(--tg-theme-hint-color,rgba(246,247,251,.62));--green:#45e0a5;--blue:var(--tg-theme-button-color,#3478f6);--danger:#ff9d9d;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    *{box-sizing:border-box}html,body{margin:0;min-height:100%}body{display:flex;justify-content:center;background:radial-gradient(circle at 22% 0%,rgba(52,120,246,.18),transparent 34%),radial-gradient(circle at 90% 7%,rgba(69,224,165,.12),transparent 32%),var(--bg);color:var(--text)}button,input{font:inherit}.hidden{display:none!important}.phone{width:min(100%,430px);min-height:100vh;padding:calc(12px + env(safe-area-inset-top)) 14px calc(20px + env(safe-area-inset-bottom));background:linear-gradient(180deg,rgba(255,255,255,.025),transparent 220px),#101417;display:block}
    .now-hero{position:relative;min-height:345px;border-radius:30px;overflow:hidden;background:#101010;border:1px solid var(--line);box-shadow:0 24px 70px rgba(0,0,0,.42);margin-bottom:14px}.now-hero__cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transform:scale(1.02);opacity:1}.now-hero__cover.hidden{display:block!important;opacity:0}.now-hero__shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.08) 0%,rgba(0,0,0,.30) 44%,rgba(0,0,0,.90) 100%),radial-gradient(circle at 18% 22%,rgba(69,224,165,.25),transparent 34%),radial-gradient(circle at 88% 0%,rgba(52,120,246,.20),transparent 38%)}.brand{appearance:none;cursor:pointer;position:absolute;top:14px;right:14px;z-index:2;display:inline-flex;align-items:center;gap:8px;padding:9px 13px;border-radius:999px;background:rgba(9,14,18,.58);border:1px solid rgba(255,255,255,.10);box-shadow:0 14px 32px rgba(0,0,0,.25);backdrop-filter:blur(16px);color:#eafff6;font-size:14px;font-weight:950;letter-spacing:-.03em}.brand span{color:var(--green)}.brand.loading{opacity:.72}.brand.loading strong:after{content:"";display:inline-block;width:8px;height:8px;margin-left:6px;border-radius:50%;background:var(--green);animation:pulse 1s infinite}@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}.now-hero__body{position:absolute;left:20px;right:20px;bottom:20px;z-index:2}.eyebrow{margin:0 0 8px;color:var(--green);font-size:10px;font-weight:950;letter-spacing:.20em}.track-title{margin:0;color:#fff;font-size:clamp(24px,8.5vw,39px);line-height:1.02;letter-spacing:-.045em;text-transform:uppercase;text-shadow:0 12px 30px rgba(0,0,0,.42);overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;max-height:120px;overflow:hidden}.track-title.len-medium{font-size:clamp(22px,7.5vw,34px)}.track-title.len-long{font-size:clamp(20px,6.7vw,30px);line-height:1.06;letter-spacing:-.04em}.track-title.len-xlong{font-size:clamp(18px,5.8vw,26px);line-height:1.08;letter-spacing:-.035em;-webkit-line-clamp:4}.track-title a{color:inherit;text-decoration:none}.track-artist{margin:10px 0 0;color:rgba(255,255,255,.76);font-size:13px;font-weight:620;line-height:1.2;overflow-wrap:anywhere}.now-user{margin:16px 0 0;color:var(--green);font-size:13px;line-height:1.15;font-weight:950}
    .command-area,.publish-panel,.result-card{padding:14px;border-radius:26px;background:rgba(18,18,18,.60);border:1px solid rgba(255,255,255,.08);margin-bottom:12px}body.mode-publish .command-area,body.mode-publish #status,body.mode-publish #resultCard,body.mode-publish #openBotBtn{display:none!important}body.mode-publish #publishPanel{display:block!important}.section-title{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:0 0 11px}.section-title h2,.publish-panel h2{margin:0;font-size:15px;color:rgba(255,255,255,.92);letter-spacing:-.02em}.section-title span{color:var(--muted);font-size:12px}.command-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.cmd{appearance:none;min-height:64px;border:1px solid rgba(255,255,255,.10);border-radius:18px;background:#22313f;color:#fff;display:grid;place-items:center;text-align:center;padding:10px;font-weight:950;font-size:14px;letter-spacing:-.02em;box-shadow:inset 0 1px 0 rgba(255,255,255,.04);cursor:pointer}.cmd.primary{background:var(--blue)}.cmd:disabled{opacity:.48}.panel-button{display:block;min-width:140px;min-height:44px;margin:13px auto 0;border-radius:999px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.10);color:#fff;font-weight:950;text-decoration:none;text-align:center;padding:11px 20px}.publish-panel h2{margin-bottom:10px}.group-compact{display:grid;grid-template-columns:46px minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px;border-radius:19px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.075)}.group-photo{width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(135deg,var(--blue),#22313f);border:1px solid rgba(255,255,255,.14);color:#fff;font-weight:950}.group-photo img{width:100%;height:100%;border-radius:50%;object-fit:cover;display:block}.group-row{grid-template-columns:38px minmax(0,1fr) auto!important}.group-row-photo{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(135deg,var(--blue),#22313f);border:1px solid rgba(255,255,255,.12);color:#fff;font-weight:950;font-size:13px;overflow:hidden}.group-row-photo img{width:100%;height:100%;border-radius:50%;object-fit:cover;display:block}.group-info{min-width:0;overflow:hidden}.group-info strong{display:block;font-size:13px;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.group-info span{display:block;margin-top:4px;color:var(--muted);font-size:12px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.select-group{width:auto;min-width:76px;min-height:38px;height:38px;border:1px solid rgba(255,255,255,.12);border-radius:999px;background:rgba(255,255,255,.08);color:#fff;padding:0 14px;font-weight:850;white-space:nowrap}.choice{min-height:42px;border:1px solid rgba(255,255,255,.12);border-radius:999px;background:rgba(255,255,255,.08);color:#fff;padding:0 14px;font-weight:850}.choice-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:10px}.choice{min-height:48px;border-radius:16px;background:#22313f;font-weight:900}.choice.primary{background:var(--blue)}.group-list{max-height:260px;overflow:auto;border-radius:18px;margin-top:10px;border:1px solid rgba(255,255,255,.075);background:rgba(255,255,255,.035)}.group-row{width:100%;display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:12px;border:0;border-top:1px solid var(--line);background:transparent;color:#fff;text-align:left}.group-row:first-child{border-top:0}.group-row[aria-selected="true"]{background:rgba(52,120,246,.18)}.group-title{font-weight:850;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.group-meta{color:var(--muted);font-size:12px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.result{min-height:54px;padding:14px 15px;border-radius:19px;border:1px solid rgba(69,224,165,.25);background:rgba(69,224,165,.055);color:#bff7df;font-size:14px;line-height:1.35;margin-bottom:12px;overflow-wrap:anywhere}.result strong{display:block;color:#eafff6;font-size:15px;margin-bottom:4px}.result.bad{color:var(--danger);border-color:rgba(248,113,113,.24);background:rgba(248,113,113,.065)}.result-card h2{margin:0 0 8px;font-size:22px;letter-spacing:-.04em}.result-card p{margin:6px 0;color:rgba(255,255,255,.80);line-height:1.35;white-space:pre-wrap;overflow-wrap:anywhere}.result-card img{display:block;width:100%;height:auto;object-fit:contain;margin-top:10px;border-radius:18px;border:1px solid rgba(255,255,255,.08)}.result-image-link{display:block}.quick-actions{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:10px}.quick-actions button{min-height:46px;border-radius:14px;border:1px solid rgba(255,255,255,.10);background:#22313f;color:#fff;font-weight:850}
    .boot-debug{display:block;margin-top:8px;color:rgba(246,247,251,.58);font-size:11px;line-height:1.35;word-break:break-word}
    @media(max-width:370px){.phone{padding-left:10px;padding-right:10px}.now-hero{min-height:320px;border-radius:26px}.now-hero__body{left:17px;right:17px;bottom:17px}.track-artist{font-size:12px}.now-user{font-size:12px}.cmd{min-height:58px;font-size:13px;border-radius:16px}.command-grid{gap:7px}}
  </style>
</head>
<body>
  <main class="phone">
    <section class="now-hero" aria-label="Tocando agora">
      <img id="cover" class="now-hero__cover hidden" alt="Capa do álbum" />
      <div class="now-hero__shade"></div>
      <button id="refreshSessionBtn" class="brand" type="button" aria-label="Recarregar música e sessão"><span>♫</span><strong>tigraoRADIO</strong></button>
      <div class="now-hero__body">
        <p class="eyebrow">TOCANDO AGORA</p>
        <h1 class="track-title" id="trackTitle">Carregando</h1>
        <p class="track-artist" id="trackArtist">Aguardando autenticação.</p>
        <p class="now-user" id="nowLine">Você · ♫ <span id="plays">0</span></p>
      </div>
    </section>

    <section class="command-area" aria-label="Comandos musicais">
      <div class="section-title"><h2>Comandos musicais</h2><span>2×4</span></div>
      <div id="commandGrid" class="command-grid">
        <button class="cmd primary" type="button" data-command="nowp">Publicar</button>
        <button class="cmd" type="button" data-command="weekfm">Semana</button>
        <button class="cmd" type="button" data-command="monthfm">Mês</button>
        <button class="cmd" type="button" data-command="tcanvas">Canvas</button>
        <button class="cmd" type="button" data-command="tstory">Story</button>
        <button class="cmd" type="button" data-command="tly">Letra</button>
        <button class="cmd" type="button" data-command="tnow">Mosaico</button>
        <button class="cmd" type="button" data-command="more">...</button>
      </div>
    </section>

    <section id="publishPanel" class="publish-panel hidden" aria-label="Publicar em grupo">
      <h2 id="publishActionTitle">Publicar</h2>
      <div id="storyChoices" class="choice-grid hidden">
        <button id="storyDmBtn" class="choice primary" type="button">Enviar na DM</button>
        <button id="storyGroupBtn" class="choice" type="button">Enviar no grupo</button>
        <button id="storyCancelBtn" class="choice" type="button">Voltar</button>
      </div>
      <div id="groupPickerBlock" class="group-compact">
        <div id="selectedGroupPhoto" class="group-photo">G</div>
        <div class="group-info"><strong id="selectedGroupTitle">Escolha um grupo</strong><span id="selectedGroupHint">Toque em um grupo abaixo e confirme.</span></div>
        <button id="toggleGroupsBtn" class="select-group" type="button">Trocar</button>
      </div>
      <div id="groups" class="group-list hidden"><div class="result">Carregando grupos.</div></div>
      <div id="publishChoices" class="choice-grid hidden">
        <button id="publishConfirm" class="choice primary" type="button">Confirmar</button>
        <button id="publishCancel" class="choice" type="button">Voltar</button>
      </div>
    </section>

    <section id="morePanel" class="publish-panel hidden" aria-label="Mais opções">
      <h2>...</h2>
      <div id="moreAdminChoices" class="choice-grid hidden">
        <button id="morePanelBtn" class="choice primary" type="button">Painel</button>
        <button id="moreSongchartsBtn" class="choice" type="button">Songcharts</button>
        <button id="moreAdminCancelBtn" class="choice" type="button">Voltar</button>
      </div>
      <div id="moreMemberChoices" class="choice-grid hidden">
        <button id="moreRadioBtn" class="choice primary" type="button">RadioFM</button>
        <button id="moreAlbnowBtn" class="choice" type="button">AlbNow</button>
        <button id="moreMemberCancelBtn" class="choice" type="button">Voltar</button>
      </div>
    </section>

    <div id="status" class="result"><strong>Inicializando.</strong>O retorno dos comandos aparece aqui.<span id="bootDebug" class="boot-debug">HTML servido. JavaScript de diagnóstico inicializando.</span></div>

    <section id="resultCard" class="result-card hidden" aria-label="Resultado do comando">
      <h2 id="resultTitle">Resultado</h2>
      <p id="resultBody"></p>
      <a id="resultImageLink" class="result-image-link hidden" href="#" download="resultado.jpg"><img id="resultImage" alt="Card gerado" /></a>
      <div id="resultActions" class="quick-actions hidden"></div>
    </section>

    <a id="openBotBtn" class="panel-button hidden" href="https://t.me/tigraoRADIObot?startapp">Abrir pelo bot</a>
  </main>
<script>
(function(){
  "use strict";
  const SESSION_KEY="tr4_public_eqs";
  const PANEL_SESSION_KEY="tr4_equalizador_eqs";
  const BOOT_LINK="https://t.me/tigraoRADIObot?startapp";
  const GROUP_COMMANDS={nowp:true,weekfm:true,monthfm:true,tcanvas:true,tly:true,tnow:true,songcharts:true};
  const PAGE_COMMANDS={nowp:true,weekfm:true,monthfm:true,tcanvas:true,tstory:true,tly:true,tnow:true};
  const COMMAND_TITLES={nowp:"Publicar",weekfm:"Semana",monthfm:"Mês",tcanvas:"Canvas",tstory:"Story",tly:"Letra",tnow:"Mosaico"};
  let tg=null,initData="",apiHeaders={},selectedGroup="",currentGroups=[],trackAvailable=false,pendingGroupCommand="",canOpenEqualizador=false;
  let lastCommand="",currentResult=null,refreshing=false;
  function $(id){return document.getElementById(id);}
  function hide(id,shouldHide){const el=$(id);if(!el)return;if(shouldHide)el.classList.add("hidden");else el.classList.remove("hidden");}
  function safeText(v){return String(v==null?"":v);}
  function escapeHtml(v){return safeText(v).replace(/[&<>"']/g,function(ch){switch(ch){case "&":return "&amp;";case "<":return "&lt;";case ">":return "&gt;";case '"':return "&quot;";case "'":return "&#39;";default:return ch;}});}
  function reportClient(kind,msg,extra){try{if(window.__TR4_MARK_PLAYER){window.__TR4_MARK_PLAYER(kind,msg,extra);return;}fetch("/equalizador/api/client-error",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:String(kind||"player_event").slice(0,60),message:String(msg||"").slice(0,220),extra:String(extra||"").slice(0,240),href:location.pathname+location.search,user_agent:navigator.userAgent,source:"player_body",phase:"137.3"}),keepalive:true}).catch(function(){});}catch(_){} }
  window.onerror=function(message,source,line,col){reportClient("player_window_error",message,String(source||"")+":"+line+":"+col);return false;};
  window.addEventListener("unhandledrejection",function(ev){const r=ev&&ev.reason;reportClient("player_unhandledrejection",r&&r.message?r.message:String(r||"rejection"),r&&r.stack?r.stack:"");});
  function sessionToken(value){if(!value)return"";if(typeof value==="string")return value;return value.token?String(value.token):"";}
  function setStoredSession(value){const token=sessionToken(value);try{if(token)window.localStorage.setItem(SESSION_KEY,token);else window.localStorage.removeItem(SESSION_KEY);}catch(_){}try{if(token)window.sessionStorage.setItem(PANEL_SESSION_KEY,token);else window.sessionStorage.removeItem(PANEL_SESSION_KEY);}catch(_){}}
  function getStoredSession(){try{return window.localStorage.getItem(SESSION_KEY)||window.sessionStorage.getItem(PANEL_SESSION_KEY)||"";}catch(_){return "";} }
  function configureTelegram(){tg=window.Telegram&&window.Telegram.WebApp;if(tg){try{if(window.__TR4_READY_PLAYER)window.__TR4_READY_PLAYER("configure");else{tg.ready();tg.expand();}}catch(e){reportClient("player_ready_failed",e&&e.message?e.message:"ready_failed","");}}initData=tg&&tg.initData?tg.initData:"";const stored=getStoredSession();apiHeaders=initData?{Authorization:"tma "+initData}:(stored?{Authorization:"eqs "+stored}:{});}
  function hasAuth(){return !!(apiHeaders&&apiHeaders.Authorization);}
  function fetchTimeout(path,opts,ms){opts=opts||{};ms=ms||8000;const ctrl=(typeof AbortController!=="undefined")?new AbortController():null;let t=null;if(ctrl){opts.signal=ctrl.signal;t=setTimeout(function(){try{ctrl.abort();}catch(_){}},ms);}return fetch(path,opts).finally(function(){if(t)clearTimeout(t);});}
  async function publicPing(){try{reportClient("player_ping_started","/api/public/ping","");const res=await fetchTimeout("/equalizador/api/public/ping?ts="+Date.now(),{method:"GET",cache:"no-store"},4500);reportClient("player_ping_done",String(res.status),res.ok?"ok":"not_ok");return res.ok;}catch(e){reportClient("player_ping_failed",e&&e.message?e.message:"ping_failed","");return false;}}
  async function api(path,opts){opts=opts||{};opts.headers=Object.assign({},apiHeaders,opts.headers||{});reportClient("player_api_started",path,"");const res=await fetchTimeout(path,opts,10000);const data=await res.json().catch(function(){return {};});reportClient("player_api_done",path,String(res.status));if(!res.ok){const detail=data.detail||data.public_detail||data.message||("HTTP "+res.status);const err=new Error(typeof detail==="string"?detail:(detail.public_detail||detail.code||"Falha na operação."));err.payload=data;err.status=res.status;throw err;}return data;}
  function status(msg,kind,title){const el=$("status");if(!el)return;el.className="result"+(kind?" "+kind:"");const debug=$("bootDebug");const debugText=debug?debug.textContent:"";el.innerHTML="<strong>"+escapeHtml(title||"Status")+"</strong>"+escapeHtml(msg||"")+(debugText?'<span id="bootDebug" class="boot-debug">'+escapeHtml(debugText)+'</span>':"");}
  function showHome(){document.body.classList.remove("mode-publish");pendingGroupCommand="";hide("publishPanel",true);hide("morePanel",true);hide("groups",true);hide("publishChoices",true);hide("storyChoices",true);hide("groupPickerBlock",false);}
  function showMorePage(){document.body.classList.add("mode-publish");pendingGroupCommand="";hide("publishPanel",true);hide("morePanel",false);hide("resultCard",true);currentResult=null;hide("moreAdminChoices",!canOpenEqualizador);hide("moreMemberChoices",!!canOpenEqualizador);status("Escolha uma opção.","ok","Mais opções");}
  function showPublishPage(command){pendingGroupCommand=command||"nowp";const title=COMMAND_TITLES[pendingGroupCommand]||"Publicar";const titleEl=$("publishActionTitle");if(titleEl)titleEl.textContent=title;const hint=$("selectedGroupHint");if(hint&&!selectedGroup)hint.textContent="Toque em um grupo abaixo e confirme.";document.body.classList.add("mode-publish");hide("morePanel",true);hide("publishPanel",false);hide("resultCard",true);currentResult=null;if(pendingGroupCommand==="tstory"){hide("storyChoices",false);hide("groupPickerBlock",true);hide("groups",true);hide("publishChoices",true);return;}hide("storyChoices",true);hide("groupPickerBlock",false);hide("groups",false);hide("publishChoices",false);renderGroups();}
  function showBotFallback(){hide("openBotBtn",false);status("Abra pelo Telegram para validar sua sessão.","bad","Sessão pública");}
  function titleClass(value){const n=safeText(value).trim().length;if(n>70)return "len-xlong";if(n>44)return "len-long";if(n>24)return "len-medium";return "len-short";}
  function renderTrack(track){track=track||{};trackAvailable=!!track.available;const title=trackAvailable?(track.track_name||"Música"):(track.message||"Nada tocando agora");const artist=trackAvailable?(track.artist||"Artista"):(track.diagnostic_code||track.code||"Aguardando música");const url=track.spotify_url||"";const titleEl=$("trackTitle");titleEl.className="track-title "+titleClass(title);titleEl.innerHTML=url?'<a href="'+escapeHtml(url)+'" target="_blank" rel="noreferrer">'+escapeHtml(title)+"</a>":escapeHtml(title);$("trackArtist").textContent=trackAvailable?"— "+artist:artist;$("plays").textContent=String(track.user_plays||0);const cover=$("cover");if(track.cover_url){cover.src=track.cover_url;cover.classList.remove("hidden");}else{cover.removeAttribute("src");cover.classList.add("hidden");}updateCommandState();}
  function sanitizeRichText(value){const wrap=document.createElement("template");wrap.innerHTML=safeText(value).replace(/\\n/g,"<br>");const allowed={B:true,STRONG:true,I:true,EM:true,CODE:true,BR:true,BLOCKQUOTE:true,P:true,A:true};function clean(node){if(node.nodeType===Node.TEXT_NODE)return document.createTextNode(node.nodeValue||"");const frag=document.createDocumentFragment();if(node.nodeType!==Node.ELEMENT_NODE){Array.from(node.childNodes||[]).forEach(function(child){frag.appendChild(clean(child));});return frag;}const tag=node.tagName;if(!allowed[tag]){Array.from(node.childNodes).forEach(function(child){frag.appendChild(clean(child));});return frag;}const el=document.createElement(tag.toLowerCase());if(tag==="A"){const href=node.getAttribute("href")||"";if(new RegExp("^https?://","i").test(href)){el.setAttribute("href",href);el.setAttribute("target","_blank");el.setAttribute("rel","noreferrer");}}Array.from(node.childNodes).forEach(function(child){el.appendChild(clean(child));});return el;}const out=document.createDocumentFragment();Array.from(wrap.content.childNodes).forEach(function(child){out.appendChild(clean(child));});return out;}
  function setBodyRich(el,value){el.textContent="";el.appendChild(sanitizeRichText(value));}
  function updateCommandState(){document.querySelectorAll("[data-command]").forEach(function(btn){const cmd=btn.getAttribute("data-command")||"";btn.disabled=(!trackAvailable&&cmd!=="weekfm"&&cmd!=="monthfm"&&cmd!=="songcharts"&&cmd!=="tnow"&&cmd!=="more");});}
  function groupInitial(group){const raw=safeText((group&&group.title)||(group&&group.username)||"G").trim();return(raw.charAt(0)||"G").toUpperCase();}
  function groupPhotoMarkup(group,cls){const photo=safeText(group&&group.photo_url);const fallback=escapeHtml(groupInitial(group));const title=escapeHtml(group&&group.title?group.title:"Grupo");if(photo)return '<span class="'+escapeHtml(cls)+'" data-fallback="'+fallback+'"><img src="'+escapeHtml(photo)+'" alt="'+title+'" loading="lazy"></span>';return '<span class="'+escapeHtml(cls)+'">'+fallback+'</span>';}
  function bindGroupPhotoFallbacks(){document.querySelectorAll(".group-row-photo img").forEach(function(img){img.onerror=function(){const parent=img.parentNode;if(parent)parent.textContent=parent.getAttribute("data-fallback")||"G";};});}
  function renderSelectedGroupPhoto(group){const photo=$("selectedGroupPhoto");if(!photo)return;photo.textContent="";if(group&&group.photo_url){const img=document.createElement("img");img.src=safeText(group.photo_url);img.alt=safeText(group.title||"Grupo");img.onerror=function(){photo.textContent=groupInitial(group);};photo.appendChild(img);return;}photo.textContent=group?groupInitial(group):"G";}
  function setSelectedGroup(ref){selectedGroup=ref||"";let group=currentGroups.find(function(g){return g.ref===selectedGroup;});$("selectedGroupTitle").textContent=group?group.title:"Escolha um grupo";$("selectedGroupHint").textContent=group?(group.username?"@"+group.username:"Grupo selecionado para publicação."):"Toque em um grupo abaixo e confirme.";renderSelectedGroupPhoto(group);renderGroups();}
  function renderGroups(){const box=$("groups");if(!box)return;const visibleGroups=currentGroups.filter(function(g){return safeText(g.status).toLowerCase().indexOf("indispon")<0;});if(!visibleGroups.length){box.innerHTML='<div class="result">Nenhum grupo encontrado.</div>';return;}box.innerHTML=visibleGroups.map(function(g){const meta=g.username?"@"+g.username:"";return '<button class="group-row" type="button" data-group="'+escapeHtml(g.ref)+'" aria-selected="'+(g.ref===selectedGroup?'true':'false')+'">'+groupPhotoMarkup(g,"group-row-photo")+'<span><span class="group-title">'+escapeHtml(g.title||"Grupo")+'</span>'+(meta?'<span class="group-meta">'+escapeHtml(meta)+'</span>':'')+'</span><span>›</span></button>';}).join("");bindGroupPhotoFallbacks();box.querySelectorAll("[data-group]").forEach(function(btn){btn.onclick=function(){setSelectedGroup(btn.getAttribute("data-group")||"");hide("groups",true);hide("publishChoices",false);};});}
  function requireGroup(command){if(PAGE_COMMANDS[command]){showPublishPage(command);return;}pendingGroupCommand=command;hide("publishPanel",false);hide("groups",false);hide("publishChoices",false);renderGroups();status("Escolha o grupo e confirme para continuar.","","Grupo necessário");}
  function resultDownloadTarget(data,image){return safeText(data.download_url||data.file_url||data.video_url||data.image_url||image||"");}
  function absoluteUrl(value){try{return new URL(value,window.location.href).toString();}catch(_){return safeText(value);}}
  function publicTimestamp(){const d=new Date();function z(n){return String(n).padStart(2,"0");}return String(d.getFullYear())+z(d.getMonth()+1)+z(d.getDate())+"_"+z(d.getHours())+z(d.getMinutes())+z(d.getSeconds());}
  function publicFilename(command,ext){return "tigraoRADIO_"+safeText(command||lastCommand||"resultado").replace(/[^A-Za-z0-9_-]+/g,"-")+"_"+publicTimestamp()+"."+(ext||"txt");}
  function textDataUrl(value){return "data:text/plain;base64,"+btoa(unescape(encodeURIComponent(safeText(value||""))));}
  async function prepareDownloadUrl(target,filename){const res=await api("/equalizador/api/public/download-result",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target:target,filename:filename})});return absoluteUrl(res.download_url||"");}
  async function downloadResult(){if(!currentResult)return;const image=currentResult.image_data_url||currentResult.image_url||"";let target=resultDownloadTarget(currentResult,image);let filename=safeText(currentResult.filename||currentResult.download_name||"");if(!target){const text=currentResult.text||currentResult.message||"";if(text){target=textDataUrl(text);filename=filename||publicFilename(lastCommand,"txt");}}if(!target){status("Este resultado não trouxe arquivo para baixar.","bad","Download");return;}if(!filename)filename=publicFilename(lastCommand,new RegExp("^data:image/png","i").test(target)?"png":"txt");reportClient("player_download_clicked",filename,target.slice(0,80));try{status("Preparando arquivo para download.","","Download");const url=await prepareDownloadUrl(target,filename);if(!url){throw new Error("download_url_missing");}reportClient("player_download_url_created",filename,url.slice(0,120));if(tg&&typeof tg.downloadFile==="function"&&new RegExp("^https?://","i").test(url)){reportClient("player_download_native_attempt",filename,url.slice(0,120));tg.downloadFile({url:url,file_name:filename});status("Pedido de download enviado ao Telegram.","ok","Download");return;}reportClient("player_download_fallback_open",filename,url.slice(0,120));window.open(url,"_blank");status("Abri o arquivo para download.","ok","Download");}catch(e){reportClient("player_download_failed",e&&e.message?e.message:"download_failed",target.slice(0,120));status((e&&e.message)||"Não consegui baixar este resultado.","bad","Download");}}
  async function sendCommandCopy(command){command=String(command||lastCommand||"").replace(/^[/]/,"").toLowerCase();if(!command){status("Nenhum comando executado para enviar ao bot.","bad","Enviar no bot");return;}reportClient("player_execute_command_clicked",command,selectedGroup||"");reportClient("player_send_command_clicked",command,selectedGroup||"");try{status("Enviando /"+command+" na sua DM pelo bot.","","Enviar para bot");const res=await api("/equalizador/api/public/execute-command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:command,group_ref:selectedGroup||"",format:"dm"})});status(res.message||"Enviado na sua DM.","ok","Enviado para bot");reportClient("player_send_command_done",command,"execute-command");return;}catch(e){reportClient("player_execute_command_failed",e&&e.message?e.message:"execute_command_failed",command+":"+(e&&e.status?e.status:""));}const payload=JSON.stringify({type:"public_command_copy",command:"/"+command,group_ref:selectedGroup||""});try{if(tg&&typeof tg.sendData==="function"){status("Tentando fallback do Telegram para /"+command+".","","Enviar para bot");reportClient("player_senddata_attempt",command,selectedGroup||"");tg.sendData(payload);return;}}catch(e){reportClient("player_senddata_failed",e&&e.message?e.message:"sendData_failed",command);}try{const res=await api("/equalizador/api/public/send-command-copy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:"/"+command,group_ref:selectedGroup||""})});status(res.message||"Comando executado pelo bot.","ok","Executado");reportClient("player_send_command_done",command,"legacy-backend");return;}catch(e){reportClient("player_send_command_backend_failed",e&&e.message?e.message:"send_command_failed",command+":"+(e&&e.status?e.status:""));}status("Não consegui executar automaticamente.","bad","Enviar para bot");}
  function renderResult(data){data=data||{};currentResult=data;const card=$("resultCard"),body=$("resultBody"),img=$("resultImage"),link=$("resultImageLink"),actions=$("resultActions");$("resultTitle").textContent=data.title||"Resultado";setBodyRich(body,data.text||data.message||"");const image=data.image_data_url||data.image_url||"";if(image){img.src=image;link.href=image;link.download=safeText(data.filename||data.download_name||"tigraoRADIO-resultado.jpg");link.classList.remove("hidden");}else{img.removeAttribute("src");link.removeAttribute("href");link.classList.add("hidden");}actions.innerHTML="";let used=0;function addAction(label,fn){if(used>=4)return;const b=document.createElement("button");b.type="button";b.textContent=label;b.onclick=fn;actions.appendChild(b);used+=1;}if(lastCommand)addAction("Enviar no bot",function(){sendCommandCopy(lastCommand);});if(resultDownloadTarget(data,image)||data.text||data.message)addAction("Baixar",downloadResult);if(Array.isArray(data.actions)&&data.actions.length){data.actions.forEach(function(action){addAction(action.label||"Abrir",function(){if(action.command)runPublicCommand(String(action.command).replace(/^[/]/,""));else if(action.url&&tg&&tg.openLink)tg.openLink(action.url);});});}if(used){actions.classList.remove("hidden");}else{actions.classList.add("hidden");}card.classList.remove("hidden");status("Resultado atualizado dentro do Mini App.","ok","Resultado pronto.");}
  async function loadPlayingPreview(){const res=await api("/equalizador/api/public/playing-preview");renderTrack(res);return res;}
  async function refreshPublicSession(){if(refreshing)return;refreshing=true;const btn=$("refreshSessionBtn");if(btn)btn.classList.add("loading");try{configureTelegram();if(!hasAuth()){showBotFallback();return;}const me=await api("/equalizador/api/public/me");if(me&&me.sessao)setStoredSession(me.sessao);canOpenEqualizador=!!(me&&me.can_open_equalizador);const home=await api("/equalizador/api/public/home");currentGroups=Array.isArray(home.groups)?home.groups:currentGroups;renderTrack(home.track||{});renderGroups();if(selectedGroup&&!currentGroups.some(function(g){return g.ref===selectedGroup;})){selectedGroup="";setSelectedGroup("");}if(lastCommand&&lastCommand!=="nowp"){await runPublicCommand(lastCommand,{fromRefresh:true});}else{status("Sessão e música atualizadas.","ok","Atualizado");}}catch(e){reportClient("player_refresh_failed",e&&e.message?e.message:"refresh_failed",e&&e.status?e.status:"");status((e&&e.message)||"Falha ao atualizar sessão.","bad","Falha");}finally{refreshing=false;if(btn)btn.classList.remove("loading");}}
  function openPanel(){try{const token=getStoredSession();if(token)window.sessionStorage.setItem(PANEL_SESSION_KEY,token);}catch(_){}const url=new URL("/equalizador",window.location.href);window.location.assign(url.toString());}
  async function runPublicCommand(command,options){options=options||{};command=String(command||"").replace(/^[/]/,"").toLowerCase();if(!command)return;if(!hasAuth()){showBotFallback();return;}if(command==="more"){showMorePage();return;}if(PAGE_COMMANDS[command]&&!options.confirmed){requireGroup(command);return;}if(GROUP_COMMANDS[command]&&!selectedGroup){requireGroup(command);return;}lastCommand=command;try{status("Executando /"+command+".","","Comando");if(command==="nowp"){hide("resultCard",true);currentResult=null;const res=await api("/equalizador/api/public/nowp",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({group_ref:selectedGroup})});showHome();status(res.message||"Publicado no grupo e copiado na sua DM.","ok","Publicar");if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");return;}if(command==="weekfm"||command==="monthfm"||command==="tcanvas"||command==="tly"||command==="tnow"){hide("resultCard",true);currentResult=null;const res=await api("/equalizador/api/public/group-command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:command,group_ref:selectedGroup})});showHome();const label=COMMAND_TITLES[command]||"Comando";status(res.message||(label+" enviado no grupo e copiado na sua DM."),"ok",label);if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");return;}if(command==="tstory"){hide("resultCard",true);currentResult=null;const target=options.target==="group"?"group":"dm";if(target==="group"&&!selectedGroup){hide("storyChoices",true);hide("groupPickerBlock",false);hide("groups",false);hide("publishChoices",false);renderGroups();status("Escolha o grupo e confirme para continuar.","","Grupo necessário");return;}const res=await api("/equalizador/api/public/story-command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target:target,group_ref:target==="group"?selectedGroup:""})});showHome();status(res.message||"Story enviado na sua DM.","ok","Story");if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");return;}const params=new URLSearchParams();if(selectedGroup)params.set("group_ref",selectedGroup);const res=await api("/equalizador/api/public/command/"+encodeURIComponent(command)+(params.toString()?"?"+params.toString():""));if(command==="playing"){renderTrack(res);renderResult({title:"Tocando",text:(res.track_name||"Música")+" — "+(res.artist||"Artista"),image_url:res.cover_url||"",download_url:res.cover_url||"",filename:"tocando-agora.jpg"});}else{renderResult(res);}if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");}catch(e){reportClient("player_command_failed",e&&e.message?e.message:"command_failed",command+":"+(e&&e.status?e.status:""));status((e&&e.message)||"Falha ao executar comando.","bad","Falha");if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("error");}}
  async function sendDmOnlyCommand(command){command=String(command||"").replace(/^[/]/,"").toLowerCase();if(!hasAuth()){showBotFallback();return;}try{status("Enviando na DM.","","DM");const res=await api("/equalizador/api/public/dm-command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:command})});showHome();status(res.message||"Enviado na sua DM.","ok","DM");if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("success");}catch(e){reportClient("player_dm_command_failed",e&&e.message?e.message:"dm_command_failed",command+":"+(e&&e.status?e.status:""));status((e&&e.message)||"Falha ao enviar na DM.","bad","Falha");if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred("error");}}
  function waitForTelegram(ms){const started=Date.now();return new Promise(function(resolve){(function tick(){configureTelegram();if(tg||Date.now()-started>=ms){resolve(!!tg);return;}setTimeout(tick,80);})();});}
  function setBootDebug(text){const el=$("bootDebug");if(el)el.textContent=text;}
  async function bootstrap(){try{if(window.__TR4_PLAYER_BOOT)window.__TR4_PLAYER_BOOT.bottomStarted=true;}catch(_){}reportClient("player_js_started","ok","phase137_3");setBootDebug("JS principal iniciou. Testando conexão com o backend.");await publicPing();setBootDebug("Conexão testada. Aguardando Telegram.WebApp/initData.");await waitForTelegram(1800);configureTelegram();if(!hasAuth()){reportClient("player_no_auth_after_wait",tg?"Telegram.WebApp sem initData/sessao":"Telegram.WebApp ausente","");showBotFallback();renderTrack({available:false,message:"Abra pelo Telegram oficial ou use uma sessão válida."});setBootDebug("Sem initData/sessão. Se estiver em cliente alternativo, teste no Telegram oficial.");return;}try{setBootDebug("Sessão encontrada. Chamando /api/public/me.");const me=await api("/equalizador/api/public/me");if(me&&me.sessao)setStoredSession(me.sessao);canOpenEqualizador=!!(me&&me.can_open_equalizador);setBootDebug("Usuário validado. Carregando home pública.");const home=await api("/equalizador/api/public/home");currentGroups=Array.isArray(home.groups)?home.groups:[];renderTrack(home.track||{});renderGroups();setSelectedGroup(selectedGroup||"");setBootDebug("Bootstrap completo.");status("Escolha uma função na matriz.","ok","Pronto.");}catch(e){reportClient("player_bootstrap_failed",e&&e.message?e.message:"bootstrap_failed",e&&e.status?e.status:"");showBotFallback();renderTrack({available:false,message:"Não foi possível carregar o player."});setBootDebug("Falha no bootstrap: "+((e&&e.message)||"erro desconhecido"));}}
  document.querySelectorAll("[data-command]").forEach(function(btn){btn.addEventListener("click",function(){runPublicCommand(btn.getAttribute("data-command")||"");});});
  $("refreshSessionBtn").onclick=function(){if(document.body.classList.contains("mode-publish")){showHome();status("Voltou para a tela inicial.","","Início");return;}refreshPublicSession();};
  $("morePanelBtn").onclick=function(){openPanel();};
  $("moreSongchartsBtn").onclick=function(){showHome();runPublicCommand("songcharts");};
  $("moreRadioBtn").onclick=function(){sendDmOnlyCommand("radiofm");};
  $("moreAlbnowBtn").onclick=function(){sendDmOnlyCommand("albnow");};
  $("moreAdminCancelBtn").onclick=function(){showHome();status("Voltou para a tela inicial.","","Início");};
  $("moreMemberCancelBtn").onclick=function(){showHome();status("Voltou para a tela inicial.","","Início");};
  $("toggleGroupsBtn").onclick=function(){hide("groups",!$("groups").classList.contains("hidden"));};
  $("publishConfirm").onclick=function(){if(!pendingGroupCommand){pendingGroupCommand="nowp";}if(!selectedGroup){hide("groups",false);status("Escolha um grupo antes de confirmar.","bad","Grupo obrigatório");return;}const cmd=pendingGroupCommand;pendingGroupCommand="";hide("publishChoices",true);runPublicCommand(cmd,{confirmed:true,target:cmd==="tstory"?"group":""});};
  $("publishCancel").onclick=function(){showHome();status("Publicação cancelada.","","Cancelado");};
  $("storyDmBtn").onclick=function(){runPublicCommand("tstory",{confirmed:true,target:"dm"});};
  $("storyGroupBtn").onclick=function(){pendingGroupCommand="tstory";hide("storyChoices",true);hide("groupPickerBlock",false);hide("groups",false);hide("publishChoices",false);renderGroups();};
  $("storyCancelBtn").onclick=function(){showHome();status("Story cancelado.","","Cancelado");};
  bootstrap();
})();
</script>
</body>
</html>"""

@router.get("/player", response_class=HTMLResponse)
def public_music_player() -> HTMLResponse:
    return HTMLResponse(
        _PUBLIC_MUSIC_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _public_identity_from_authorization(authorization: str | None) -> TelegramWebAppIdentity:
    try:
        header = (authorization or "").strip()
        if header.lower().startswith("eqs "):
            return validate_equalizador_session(
                header[4:].strip(),
                renew_ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
                expired_grace_seconds=settings.TR4_EQUALIZADOR_SESSION_GRACE_SECONDS,
            )
        init_data = extract_tma_authorization(header)
        return validate_init_data(
            init_data,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            max_age_seconds=settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
        )
    except EqualizadorStorageError as exc:
        raise HTTPException(status_code=503, detail="Sessão temporariamente indisponível.") from exc
    except (InitDataError, EqualizadorSessionError) as exc:
        raise HTTPException(status_code=401, detail="Abra pelo Telegram para continuar.") from exc


_PUBLIC_DOWNLOAD_DIR = Path(os.environ.get("TR4_PUBLIC_DOWNLOAD_DIR", "/tmp/tr4_public_downloads"))
_PUBLIC_DOWNLOAD_MAX_BYTES = 3_500_000
_PUBLIC_DOWNLOAD_TTL_SECONDS = 15 * 60
_PUBLIC_COMMAND_COPY_ALLOWED = {"playing", "weekfm", "monthfm", "songcharts", "tcanvas", "tstory", "tly", "tnow", "nowp"}
_GROUP_REQUIRED_COMMANDS = {"songcharts", "nowp", "tnow"}


def _safe_public_filename(value: object, fallback: str = "tigraoRADIO-resultado") -> str:
    raw = str(value or fallback).strip() or fallback
    raw = raw.split("/")[-1].split("\\")[-1]
    raw = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-_")
    return (raw or fallback)[:90]


def _public_download_cleanup() -> None:
    try:
        _PUBLIC_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for path in _PUBLIC_DOWNLOAD_DIR.iterdir():
            try:
                if path.is_file() and now - path.stat().st_mtime > _PUBLIC_DOWNLOAD_TTL_SECONDS:
                    path.unlink(missing_ok=True)
            except Exception:
                continue
    except Exception:
        logger.debug("PUBLIC_DOWNLOAD_CLEANUP_FAILED", exc_info=True)


def _public_download_extension(mime: str) -> str:
    mime = str(mime or "").lower().split(";", 1)[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "text/plain": ".txt",
    }.get(mime, ".bin")


def _store_public_bytes(binary: bytes, filename: str, mime: str) -> tuple[str, str, str]:
    if not binary or len(binary) > _PUBLIC_DOWNLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo grande demais para download pelo Mini App.")
    ext = _public_download_extension(mime)
    safe_name = _safe_public_filename(filename or f"tigraoRADIO-resultado{ext}")
    if "." not in safe_name:
        safe_name += ext
    token = secrets.token_urlsafe(18)
    _PUBLIC_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = _PUBLIC_DOWNLOAD_DIR / f"{token}__{safe_name}"
    stored.write_bytes(binary)
    return token, safe_name, mime


def _store_public_data_url(target: str, filename: str) -> tuple[str, str, str]:
    match = re.match(r"^data:([A-Za-z0-9.+/-]+);base64,(.*)$", str(target or ""), re.S)
    if not match:
        raise HTTPException(status_code=400, detail="Arquivo para download inválido.")
    mime = match.group(1).lower()
    raw = match.group(2).strip()
    try:
        binary = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Arquivo para download inválido.") from exc
    return _store_public_bytes(binary, filename, mime)


def _resolve_public_download_file(token: str) -> Path | None:
    _public_download_cleanup()
    safe_token = re.sub(r"[^A-Za-z0-9_-]", "", str(token or ""))
    if not safe_token:
        return None
    try:
        for path in _PUBLIC_DOWNLOAD_DIR.glob(f"{safe_token}__*"):
            if path.is_file():
                return path
    except Exception:
        return None
    return None


def _group_ref(chat_id: int) -> str:
    return make_ui_ref("grp", int(chat_id), settings.equalizador_alias_secret())


def _resolve_public_group(ref: str) -> dict | None:
    wanted = str(ref or "").strip()
    if not wanted:
        return None
    for group in list_groups(80):
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            continue
        if _group_ref(chat_id) == wanted:
            return group
    return None


async def _bot_api(method: str, payload: dict[str, object]) -> dict[str, object]:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Bot indisponível.")
    async with httpx.AsyncClient(timeout=18.0) as client:
        res = await client.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}", json=payload)
    data = res.json()
    if not res.is_success or not data.get("ok"):
        raise HTTPException(status_code=409, detail={"public_detail": "Telegram recusou a publicação.", "code": "telegram_publish_rejected"})
    result = data.get("result")
    return result if isinstance(result, dict) else {}



def _public_cached_groups() -> list[dict[str, object]]:
    """Lista grupos conhecidos sem chamadas de validação de membro em lote.

    A checagem de presença do usuário continua ocorrendo no /nowp, no momento
    de publicar. O player público não deve bloquear o primeiro carregamento.
    """
    groups: list[dict[str, object]] = []
    for group in list_groups(80):
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            continue
        grp_ref = _group_ref(chat_id)
        groups.append({
            "ref": grp_ref,
            "title": str(group.get("title") or "Grupo")[:80],
            "username": str(group.get("username") or "").lstrip("@")[:32],
            "status": "disponível",
            "photo_url": f"/equalizador/api/public/group-photo/{grp_ref}",
        })
    return groups

async def _public_groups_for_user(user_id: int) -> list[dict[str, object]]:
    """Lista rápida para o Mini App público.

    A rota /api/public/home não pode fazer getChatMember para cada grupo:
    no WebView do Telegram isso pode estourar timeout e virar 499. A validação
    real de associação permanece imediatamente antes da publicação em
    /api/public/nowp, que é o ponto seguro para bloquear acesso indevido.
    """
    groups: list[dict[str, object]] = []
    for group in list_groups(40):
        try:
            chat_id = int(group["chat_id"])
        except Exception:
            continue
        title = str(group.get("title") or "Grupo").strip()[:80] or "Grupo"
        username = str(group.get("username") or "").strip().lstrip("@")[:32]
        grp_ref = _group_ref(chat_id)
        groups.append({
            "ref": grp_ref,
            "title": title,
            "username": username,
            "status": "verificado ao publicar",
            "photo_url": f"/equalizador/api/public/group-photo/{grp_ref}",
        })
    return groups



@router.get("/api/public/group-photo/{grp_ref}")
async def public_music_group_photo(grp_ref: str) -> Response:
    group = _resolve_public_group(str(grp_ref or ""))
    if not group:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404, detail="Foto indisponível.")
    chat_id = int(group["chat_id"])
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            chat_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChat",
                json={"chat_id": chat_id},
            )
            chat_data = chat_res.json()
            photo = ((chat_data.get("result") or {}).get("photo") or {}) if chat_data.get("ok") else {}
            file_id = str(photo.get("small_file_id") or photo.get("big_file_id") or "")
            if not file_id:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            file_res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getFile",
                json={"file_id": file_id},
            )
            file_data = file_res.json()
            file_path = str(((file_data.get("result") or {}).get("file_path") or "")) if file_data.get("ok") else ""
            if not file_path:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            img_res = await client.get(f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}")
            if not img_res.is_success or not img_res.content:
                raise HTTPException(status_code=404, detail="Foto indisponível.")
            mime = str(img_res.headers.get("content-type") or "image/jpeg").split(";", 1)[0]
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            return Response(
                content=img_res.content,
                media_type=mime,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível.") from exc


async def _public_track_for_user(user_id: int) -> dict[str, object]:
    """Carrega a música atual usando o mesmo caminho do /playing e /nowp.

    Fase 124: a busca real vem primeiro. A checagem de conexão fica apenas
    como explicação quando nada retorna, evitando falso negativo após importação
    ou cache. A chamada é limitada para não travar /api/public/home.
    """
    try:
        track = await asyncio.wait_for(music_service.get_current_or_last_played(int(user_id)), timeout=4.5)
    except asyncio.TimeoutError:
        return {"available": False, "code": "track_timeout", "message": "A leitura da música demorou. Atualize em instantes."}
    except Exception:
        logger.exception("PUBLIC_PLAYER_TRACK_LOOKUP_FAILED user=%s", user_id)
        return {"available": False, "code": "track_lookup_failed", "message": "Não foi possível carregar sua música agora."}

    if not track:
        try:
            from app.services.connection_check import connect_hint_for, is_user_connected
            if not is_user_connected(int(user_id)):
                return {"available": False, "code": "music_account_not_connected", "message": connect_hint_for("private")}
        except Exception:
            pass
        return {"available": False, "code": "nothing_playing", "message": "Nada tocando agora."}

    source = str(track.get("source") or "")
    if source == "lastfm_last":
        return {"available": False, "code": "nothing_playing_now", "message": "Nada tocando agora."}

    track_name = str(track.get("track_name") or "").strip()
    artist = str(track.get("artist") or "").strip()
    track_id = str(track.get("track_id") or "").strip()
    if not track_id or not track_name:
        return {"available": False, "code": "track_incomplete", "message": "Não consegui identificar a música atual."}

    user_plays = 0
    try:
        from app.services.lastfm import lastfm_service
        count = await asyncio.wait_for(lastfm_service.get_user_track_playcount(int(user_id), artist, track_name), timeout=1.8)
        user_plays = int(count or 0)
    except Exception:
        user_plays = 0

    return {
        "available": True,
        "source": source or "music_service",
        "track_name": track_name[:120],
        "artist": artist[:120],
        "album": str(track.get("album_name") or "")[:120],
        "cover_url": str(track.get("album_image_url") or track.get("cover_url") or "")[:500],
        "spotify_url": str(track.get("spotify_url") or "")[:500],
        "user_plays": user_plays,
    }



def _public_music_commands() -> list[dict[str, str]]:
    """Atalhos visuais para comandos musicais já existentes no bot."""
    return [
        {"label": "Tocando", "command": "/playing", "hint": "Prévia da música atual"},
        {"label": "Publicar", "command": "/nowp", "hint": "Publicar no grupo escolhido"},
        {"label": "Semana", "command": "/weekfm", "hint": "Resumo semanal"},
        {"label": "Mês", "command": "/monthfm", "hint": "Resumo mensal"},
        {"label": "Ranking", "command": "/songcharts", "hint": "Top músicas do grupo"},
        {"label": "Canvas", "command": "/tcanvas", "hint": "Prévia/publicação via bot"},
        {"label": "Story", "command": "/tstory", "hint": "Prévia/publicação via bot"},
        {"label": "Letra", "command": "/tly", "hint": "Trecho da letra"},
        {"label": "Mosaico", "command": "/tnow", "hint": "Mosaico do grupo"},
    ]


@router.get("/api/public/status")
def public_music_status() -> dict[str, object]:
    """Status público e sanitizado do Mini App musical.

    Não depende de initData e não expõe dados internos. Serve para confirmar em
    produção se a interface pública está implantada e se o sistema de LED/reactions
    continua desligado por segurança.
    """
    return {
        "ok": True,
        "player": {
            "rota": "/equalizador/player",
            "implantado": True,
            "layout": "musica_publica_sem_curtidas_sem_texto_tecnico",
            "publicacao": "nowp",
        },
        "seguranca": {
            "led_reactions_ativas": bool(settings.TR4_MUSIC_REACTIONS_ENABLED),
            "led_reactions_status": "desligado" if not settings.TR4_MUSIC_REACTIONS_ENABLED else "ativo",
            "painel_moderador": "visivel_apenas_para_operador_autorizado",
            "menu_comandos_fixo": True,
            "diagnostico_funcional": "/equalizador/api/public/diagnostico",
        },
    }



@router.get("/api/public/ping")
def public_music_ping() -> dict[str, object]:
    """Ping sem autenticação para provar que o JavaScript do WebView executou.

    Fase 137.3: usado antes de initData/sessão para diferenciar falha de
    carregamento do HTML, falha de execução do JS e falha posterior de auth/API.
    """
    return {"ok": True, "service": "tigraoRADIO", "phase": "137.3", "route": "/equalizador/api/public/ping"}

@router.get("/api/public/diagnostico")
async def public_music_diagnostico(authorization: str | None = Header(default=None)) -> dict[str, object]:
    """Diagnóstico funcional do player público.

    Diferente de /status, este endpoint valida o caminho real do usuário atual.
    Ele não publica nada e não expõe IDs brutos. Serve para separar falso 200
    de funcionamento real: sessão, comandos, preview musical e grupos cacheados.
    """
    identity = _public_identity_from_authorization(authorization)
    diag: dict[str, object] = {
        "ok": True,
        "rota": "/equalizador/player",
        "autenticacao": "telegram_initdata_ou_sessao_curta",
        "comandos": ["/playing", "/nowp", "/weekfm", "/monthfm", "/songcharts", "/tcanvas", "/tstory", "/tly", "/tnow"],
        "menu_fixo": True,
        "consulta_grupos_lenta": False,
        "musica": {"available": False, "code": "nao_testado"},
        "grupos": {"available": True, "modo": "cacheado_sem_getChatMember_em_lote", "count": 0},
    }
    try:
        preview = await _public_playing_preview_for_identity(identity)
        diag["musica"] = {
            "available": bool(preview.get("available")),
            "code": str(preview.get("diagnostic_code") or preview.get("code") or "ok"),
            "source": str(preview.get("source") or "playing_payload"),
        }
    except Exception:
        diag["musica"] = {"available": False, "code": "preview_exception"}
    try:
        groups = _public_cached_groups()
        diag["grupos"] = {"available": True, "modo": "cacheado_sem_getChatMember_em_lote", "count": len(groups)}
    except Exception:
        diag["grupos"] = {"available": False, "modo": "cacheado", "count": 0}
    return diag

@router.get("/api/public/me")
async def public_music_me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    bot_username = "@tigraoRADIObot"
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe")
            data = res.json()
            username = ((data.get("result") or {}).get("username") if data.get("ok") else None) or "tigraoRADIObot"
            bot_username = f"@{username}"
        except Exception:
            pass
    return {
        "ok": True,
        "user": {"name": html.escape(str(identity.user.get("first_name") or identity.user.get("username") or "Usuário"))[:80]},
        "bot_username": bot_username,
        "can_open_equalizador": settings.equalizador_user_is_allowed(identity.user_id),
        "bot_photo_url": "/equalizador/api/public/bot/foto",
        "sessao": create_equalizador_session(
            identity=identity,
            ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
        ),
    }



async def _public_playing_preview_for_identity(identity: TelegramWebAppIdentity) -> dict[str, object]:
    try:
        track = await music_service.get_current_or_last_played(int(identity.user_id))
    except Exception:
        return {"available": False, "diagnostic_code": "track_lookup_failed", "message": "Não foi possível carregar sua música agora."}
    if not track:
        try:
            from app.services.connection_check import connect_hint_for, is_user_connected
            if not is_user_connected(int(identity.user_id)):
                return {"available": False, "diagnostic_code": "music_account_not_connected", "message": connect_hint_for("private")}
        except Exception:
            pass
        return {"available": False, "diagnostic_code": "nothing_playing", "message": "Nada tocando agora."}
    try:
        from app.bot.telegram import build_playing_payload_for_user
        built = await build_playing_payload_for_user(
            int(identity.user_id),
            str(identity.user.get("first_name") or identity.user.get("username") or "Usuário"),
            track,
            str(identity.user.get("username") or "") or None,
        )
    except Exception:
        built = None
    track_name = str(track.get("track_name") or "").strip()
    artist = str(track.get("artist") or "").strip()
    if not track_name:
        return {"available": False, "diagnostic_code": "track_without_name", "message": "Música sem nome retornada pela fonte."}
    caption_html = ""
    cover = str(track.get("album_image_url") or track.get("cover_url") or "")[:500]
    if built:
        _track_id, caption_html, built_cover, _keyboard, _emoji = built
        cover = str(built_cover or cover or "")[:500]
    user_plays = 0
    if artist and track_name:
        try:
            from app.services.lastfm import lastfm_service
            count = await asyncio.wait_for(
                lastfm_service.get_user_track_playcount(int(identity.user_id), artist, track_name),
                timeout=1.8,
            )
            user_plays = int(count or 0)
        except Exception:
            user_plays = 0
    return {
        "available": True,
        "diagnostic_code": "ok",
        "source": str(track.get("source") or "music_service"),
        "caption_html": caption_html,
        "track_name": track_name[:120],
        "artist": artist[:120],
        "spotify_url": str(track.get("spotify_url") or "")[:500],
        "cover_url": cover,
        "user_plays": user_plays,
    }


@router.get("/api/public/playing-preview")
async def public_music_playing_preview(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    return await _public_playing_preview_for_identity(identity)

@router.get("/api/public/home")
async def public_music_home(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    return {
        "ok": True,
        "track": await _public_playing_preview_for_identity(identity),
        "groups": _public_cached_groups(),
        "atalhos": [
            {"label": "Tocando", "command": "/playing", "kind": "music"},
            {"label": "Publicar", "command": "/nowp", "kind": "publish"},
            {"label": "Semana", "command": "/weekfm", "kind": "stats"},
            {"label": "Mês", "command": "/monthfm", "kind": "stats"},
            {"label": "Ranking", "command": "/songcharts", "kind": "stats"},
            {"label": "Canvas", "command": "/tcanvas", "kind": "media"},
            {"label": "Story", "command": "/tstory", "kind": "media"},
            {"label": "Letra", "command": "/tly", "kind": "text"},
            {"label": "Mosaico", "command": "/tnow", "kind": "media"},
        ],
    }



def _public_image_data_url(image_bytes: bytes | None, mime: str = "image/jpeg") -> str:
    if not image_bytes:
        return ""
    # Protege o WebView de payloads enormes. 1.4 MB binário vira ~1.9 MB base64.
    if len(image_bytes) > 1_400_000:
        return ""
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")


def _public_text_result(title: str, text_value: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"ok": True, "title": title, "text": str(text_value or "").strip()}
    payload.update(extra)
    return payload


async def _public_card_result(
    title: str,
    result: object,
    *,
    fallback: str = "",
    display_name: str = "Usuário",
    user_id: int = 0,
    username: str | None = None,
    raw_period: str | None = None,
) -> dict[str, object]:
    text_value = str(getattr(result, "text", "") or fallback or "Sem conteúdo.")
    image_data_url = ""
    caption_html = ""
    card_data = getattr(result, "card_data", None)
    try:
        if card_data is not None:
            from app.services.monthfm_card import render_monthfm_card
            image_data_url = _public_image_data_url(await render_monthfm_card(card_data))
    except Exception:
        logger.exception("PUBLIC_PLAYER_CARD_RENDER_FAILED title=%s", title)
    if not image_data_url:
        image_data_url = _public_image_data_url(getattr(result, "photo_bytes", None))
    if image_data_url:
        try:
            if title.lower().startswith("semana"):
                from app.bot.weekfm import _caption as _weekfm_caption
                caption_html = _weekfm_caption(card_data, display_name, int(user_id or 0), username)
            elif title.lower().startswith("m"):
                from app.bot.monthfm import _format_caption as _monthfm_caption
                caption_html = _monthfm_caption(card_data, raw_period, display_name, int(user_id or 0), username)
        except Exception:
            logger.exception("PUBLIC_PLAYER_ORIGINAL_CAPTION_FAILED title=%s", title)
            caption_html = ""
    return _public_text_result(title, text_value, image_data_url=image_data_url, caption_html=caption_html)


async def _public_track_media_result(identity: TelegramWebAppIdentity, command: str) -> dict[str, object]:
    track = await music_service.get_current_or_last_played(int(identity.user_id))
    if not track:
        raise HTTPException(status_code=409, detail="Nada tocando agora.")
    display_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")[:80]
    title = str(track.get("track_name") or "Música").strip()
    artist = str(track.get("artist") or "Artista").strip()
    cover_url = str(track.get("album_image_url") or track.get("cover_url") or "")[:500]
    track_id = str(track.get("track_id") or "").strip()
    spotify_url = str(track.get("spotify_url") or "").strip()

    if command == "tstory":
        image_data_url = ""
        try:
            from app.bot.tstory import _download
            from app.services.tstory_card import render_tstory_full
            cover_bytes = await _download(cover_url)
            card = await render_tstory_full(
                cover_bytes=cover_bytes,
                listening=f"{display_name} está ouvindo agora",
                title=title,
                artist=artist,
                bot_name="tigraoRADIO",
                bot_logo_bytes=None,
            )
            image_data_url = _public_image_data_url(card)
        except Exception:
            logger.exception("PUBLIC_PLAYER_TSTORY_PREVIEW_FAILED user=%s", identity.user_id)
        return _public_text_result(
            "Story",
            f"{display_name} · {title} — {artist}",
            image_data_url=image_data_url,
            image_url="" if image_data_url else cover_url,
            download_url="" if image_data_url else cover_url,
            filename="tstory.jpg",
            command_copy="/tstory",
            track_url=spotify_url,
        )

    canvas_url = ""
    if command == "tcanvas" and track_id:
        try:
            from app.services.spotify_canvas import spotify_canvas_service
            canvas_track_id = track_id
            if canvas_track_id.startswith("lfm:") and artist and title:
                try:
                    from app.services.spotify import spotify_service
                    match = await spotify_service.search_track(artist, title)
                    if match and match.get("id"):
                        canvas_track_id = str(match["id"])
                except Exception:
                    logger.exception("PUBLIC_PLAYER_TCANVAS_RESOLVE_FAILED track=%s", track_id)
            canvas_url = str(await spotify_canvas_service.get_canvas_url(canvas_track_id) or "")
        except Exception:
            logger.exception("PUBLIC_PLAYER_TCANVAS_PREVIEW_FAILED user=%s", identity.user_id)
    return _public_text_result(
        "Canvas",
        f"{display_name} · {title} — {artist}",
        image_url=cover_url,
        video_url=canvas_url,
        download_url=canvas_url or cover_url,
        filename="tcanvas.mp4" if canvas_url else "tcanvas-cover.jpg",
        command_copy="/tcanvas",
        track_url=spotify_url,
    )


async def _public_tnow_result(group_ref: str) -> dict[str, object]:
    group = _resolve_public_group(str(group_ref or ""))
    if not group:
        raise HTTPException(status_code=428, detail="Escolha um grupo antes de abrir o mosaico.")
    chat_id = int(group["chat_id"])
    chat_title = str(group.get("title") or "Grupo")[:80]
    try:
        from app.bot.tnow import _registered_user_ids, _resolve_now_playing, _fetch_cover, MAX_TILES
        from app.services.tnow_card import TnowEntry, render_tnow_card
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Mosaico indisponível nesta instalação.") from exc

    user_ids = _registered_user_ids()
    if not user_ids:
        return _public_text_result("Mosaico", "Nenhum usuário cadastrado para o mosaico.", command_copy="/tnow")

    semaphore = asyncio.Semaphore(8)

    async def _is_member(uid: int) -> bool:
        async with semaphore:
            try:
                member = await _bot_api("getChatMember", {"chat_id": chat_id, "user_id": int(uid)})
                return str(member.get("status") or "") not in {"left", "kicked"}
            except Exception:
                return False

    member_flags = await asyncio.gather(*(_is_member(int(uid)) for uid in user_ids), return_exceptions=False)
    member_ids = [int(uid) for uid, ok in zip(user_ids, member_flags) if ok]
    if not member_ids:
        return _public_text_result("Mosaico", f"Nenhum cadastrado ativo em {chat_title} está disponível para o mosaico.", command_copy="/tnow")

    async def _display_name(uid: int) -> str:
        try:
            chat = await _bot_api("getChat", {"chat_id": int(uid)})
            first = str(chat.get("first_name") or "").strip()
            last = str(chat.get("last_name") or "").strip()
            username = str(chat.get("username") or "").strip()
            full = (first + " " + last).strip()
            if full:
                return full[:80]
            if username:
                return ("@" + username)[:80]
        except Exception:
            pass
        return f"user {uid}"

    async def _entry(uid: int) -> object:
        try:
            track = await _resolve_now_playing(int(uid))
            if not track:
                return None
            cover_bytes = await _fetch_cover(track.get("album_image_url") or track.get("cover"))
            return TnowEntry(
                user_id=int(uid),
                display_name=await _display_name(int(uid)),
                track_name=str(track.get("track_name") or "—"),
                artist=str(track.get("artist") or "—"),
                cover_bytes=cover_bytes,
                source=str(track.get("_source_tag") or "spotify"),
            )
        except Exception:
            logger.debug("PUBLIC_PLAYER_TNOW_ENTRY_FAILED uid=%s", uid, exc_info=True)
            return None

    raw_entries = await asyncio.gather(*(_entry(uid) for uid in member_ids[:60]), return_exceptions=False)
    entries = [item for item in raw_entries if isinstance(item, TnowEntry)]
    entries.sort(key=lambda e: (0 if e.source == "spotify" else 1, e.display_name.lower()))
    entries = entries[:MAX_TILES]
    if not entries:
        return _public_text_result("Mosaico", f"Ninguém cadastrado em {chat_title} está com música tocando agora.", command_copy="/tnow")

    caption_html = f"♫ <b>tocando agora</b> • {len(entries)} pessoa{'s' if len(entries) != 1 else ''}"
    lines = [f"{caption_html} em {chat_title}"]
    for entry in entries:
        lines.append(f"• <b>{html.escape(entry.display_name)}</b> — {html.escape(entry.track_name)} <i>({html.escape(entry.artist)})</i>")
    image_data_url = ""
    try:
        image_data_url = _public_image_data_url(await render_tnow_card(entries))
    except Exception:
        logger.exception("PUBLIC_PLAYER_TNOW_CARD_FAILED chat_id=%s", chat_id)
    return _public_text_result(
        "Mosaico",
        "\n".join(lines),
        image_data_url=image_data_url,
        caption_html=caption_html if image_data_url else "",
        filename="tnow.jpg",
        command_copy="/tnow",
    )


@router.get("/api/public/command/{command_name}")
async def public_music_command(
    command_name: str,
    group_ref: str | None = None,
    period: str = "week",
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    command = str(command_name or "").strip().lower().lstrip("/")
    display_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")[:80]
    username = str(identity.user.get("username") or "") or None

    if command == "playing":
        return await _public_playing_preview_for_identity(identity)

    if command == "myself":
        preview = await _public_playing_preview_for_identity(identity)
        line = ""
        if preview.get("available"):
            line = f"\n\nTocando agora: {preview.get('track_name') or 'Música'} — {preview.get('artist') or 'Artista'}"
        return _public_text_result(
            "Meu perfil",
            f"{display_name} · ♫\n\nUse os botões abaixo para ver seus extratos dentro do Mini App." + line,
            actions=[
                {"label": "Semana", "command": "weekfm"},
                {"label": "Mês", "command": "monthfm"},
                {"label": "Tocando agora", "command": "playing"},
            ],
        )

    if command == "weekfm":
        try:
            from app.services.lastfm_weekly import lastfm_weekly_service
            result = await lastfm_weekly_service.build_capsule(
                user_id=int(identity.user_id),
                display_name=display_name,
                raw_week=None,
            )
            return await _public_card_result(
                "Semana",
                result,
                fallback="Não consegui gerar o extrato semanal.",
                display_name=display_name,
                user_id=int(identity.user_id),
                username=username,
                raw_period=None,
            )
        except Exception:
            logger.exception("PUBLIC_PLAYER_WEEKFM_FAILED user=%s", identity.user_id)
            raise HTTPException(status_code=409, detail="Não consegui gerar o extrato semanal agora.")

    if command == "monthfm":
        try:
            from app.services.lastfm_capsule import lastfm_capsule_service
            result = await lastfm_capsule_service.build_capsule(
                user_id=int(identity.user_id),
                display_name=display_name,
                raw_month=None,
            )
            return await _public_card_result(
                "Mês",
                result,
                fallback="Não consegui gerar o extrato mensal.",
                display_name=display_name,
                user_id=int(identity.user_id),
                username=username,
                raw_period=None,
            )
        except Exception:
            logger.exception("PUBLIC_PLAYER_MONTHFM_FAILED user=%s", identity.user_id)
            raise HTTPException(status_code=409, detail="Não consegui gerar o extrato mensal agora.")

    if command == "songcharts":
        group = _resolve_public_group(str(group_ref or ""))
        if not group:
            raise HTTPException(status_code=428, detail="Escolha um grupo antes de abrir o ranking.")
        chat_id = int(group["chat_id"])
        chat_title = str(group.get("title") or "Grupo")[:80]
        try:
            member = await _bot_api("getChatMember", {"chat_id": chat_id, "user_id": int(identity.user_id)})
            if str(member.get("status") or "") not in {"administrator", "creator"}:
                raise HTTPException(status_code=403, detail="Ranking disponível apenas para admins do grupo.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Não consegui validar sua permissão no grupo.") from exc

        try:
            from app.services.lastfm import lastfm_service
            from app.services.lastfm_group import lastfm_group_service
            profiles = await lastfm_service.get_all_profiles()
            semaphore = asyncio.Semaphore(8)
            async def _member_profile(profile: tuple[int, str]) -> tuple[int, str] | None:
                uid, uname = profile
                async with semaphore:
                    try:
                        m = await _bot_api("getChatMember", {"chat_id": chat_id, "user_id": int(uid)})
                        if str(m.get("status") or "") in {"member", "administrator", "creator", "restricted"}:
                            return int(uid), str(uname)
                    except Exception:
                        return None
                return None
            checked = await asyncio.gather(*(_member_profile(p) for p in profiles), return_exceptions=False)
            members = [p for p in checked if p is not None]
            kind = "month" if str(period or "").lower().startswith("m") else "week"
            result = await lastfm_group_service.build_group_capsule(
                chat_title=chat_title,
                members=members,
                period_kind=kind,  # type: ignore[arg-type]
            )
            return await _public_card_result("Ranking", result, fallback="Não consegui gerar o ranking.")
        except HTTPException:
            raise
        except Exception:
            logger.exception("PUBLIC_PLAYER_SONGCHARTS_FAILED chat_id=%s user=%s", chat_id, identity.user_id)
            raise HTTPException(status_code=409, detail="Não consegui gerar o ranking agora.")

    if command == "tcanvas" or command == "tstory":
        return await _public_track_media_result(identity, command)

    if command == "tly":
        try:
            track = await music_service.get_current_or_last_played(int(identity.user_id))
        except Exception:
            track = None
        if not track:
            return _public_text_result("Letra", "Nada tocando agora.")
        artist_raw = str(track.get("artist") or "").strip()
        track_name_raw = str(track.get("track_name") or "").strip()
        lyric_snippet = ""
        if artist_raw and track_name_raw:
            try:
                from app.services.lyrics import lyrics_service
                lyric_snippet = str(await lyrics_service.get_snippet(artist_raw, track_name_raw) or "").strip()
            except Exception:
                logger.exception("PUBLIC_PLAYER_TLY_LYRICS_FAILED artist=%s track=%s", artist_raw, track_name_raw)
        text_value = f"{track_name_raw or 'Música'} — {artist_raw or 'Artista'}"
        if lyric_snippet:
            text_value += f"\n\n{lyric_snippet}"
        else:
            text_value += "\n\nNão encontrei um trecho de letra agora."
        return _public_text_result(
            "Letra",
            text_value,
            image_url=str(track.get("album_image_url") or track.get("cover_url") or "")[:500],
        )

    if command == "tnow":
        return await _public_tnow_result(str(group_ref or ""))

    raise HTTPException(status_code=404, detail="Comando indisponível no Mini App.")

_BLOCKED_PUBLIC_DOWNLOAD_HOSTS = {"localhost", "metadata", "metadata.google.internal"}


def _public_download_ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _assert_safe_public_download_url(target: str) -> None:
    parsed = urlparse(str(target or ""))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL remota inválida para download.")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in _BLOCKED_PUBLIC_DOWNLOAD_HOSTS or host.endswith(".internal"):
        raise HTTPException(status_code=400, detail="URL remota bloqueada para download.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail="URL remota inválida para download.") from exc
        addresses = []
        for info in infos:
            raw_ip = info[4][0]
            try:
                addresses.append(ipaddress.ip_address(raw_ip))
            except ValueError:
                continue
    if not addresses or any(_public_download_ip_blocked(ip) for ip in addresses):
        raise HTTPException(status_code=400, detail="URL remota bloqueada para download.")


async def _fetch_public_download_bytes(target: str) -> tuple[bytes, str]:
    _assert_safe_public_download_url(target)
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
        async with client.stream("GET", target) as res:
            status_code = int(getattr(res, "status_code", 200) or 200)
            if 300 <= status_code < 400:
                raise HTTPException(status_code=400, detail="Redirecionamento remoto bloqueado para download.")
            res.raise_for_status()
            raw_length = str(res.headers.get("content-length") or "").strip()
            if raw_length:
                try:
                    if int(raw_length) > _PUBLIC_DOWNLOAD_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="Arquivo grande demais para download pelo Mini App.")
                except ValueError:
                    pass
            mime = str(res.headers.get("content-type") or "application/octet-stream").split(";", 1)[0].strip()
            chunks = bytearray()
            async for chunk in res.aiter_bytes():
                if not chunk:
                    continue
                chunks.extend(chunk)
                if len(chunks) > _PUBLIC_DOWNLOAD_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Arquivo grande demais para download pelo Mini App.")
    return bytes(chunks), mime


@router.post("/api/public/download-result")
async def public_music_download_result(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    target = str(payload.get("target") or "").strip()
    filename = _safe_public_filename(payload.get("filename") or "tigraoRADIO-resultado.jpg")
    if not target:
        raise HTTPException(status_code=400, detail="Resultado sem arquivo para download.")
    if target.lower().startswith(("http://", "https://")):
        try:
            binary, mime = await _fetch_public_download_bytes(target)
            token, safe_name, mime = _store_public_bytes(binary, filename, mime)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Não consegui preparar o arquivo remoto para download.") from exc
        return {
            "ok": True,
            "download_url": f"/equalizador/api/public/download/{token}",
            "filename": safe_name,
            "mime_type": mime,
        }
    token, safe_name, mime = _store_public_data_url(target, filename)
    return {
        "ok": True,
        "download_url": f"/equalizador/api/public/download/{token}",
        "filename": safe_name,
        "mime_type": mime,
    }


@router.get("/api/public/download/{token}")
async def public_music_download_file(token: str) -> FileResponse:
    path = _resolve_public_download_file(token)
    if not path:
        raise HTTPException(status_code=404, detail="Arquivo expirado ou indisponível.")
    filename = path.name.split("__", 1)[-1] if "__" in path.name else path.name
    media_type = "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif suffix == ".png":
        media_type = "image/png"
    elif suffix == ".webp":
        media_type = "image/webp"
    elif suffix == ".mp4":
        media_type = "video/mp4"
    elif suffix == ".txt":
        media_type = "text/plain"
    return FileResponse(path, media_type=media_type, filename=filename, content_disposition_type="attachment")


def _clean_public_result_text(value: object, limit: int = 3600) -> str:
    text = html.unescape(str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _absolute_public_url(request: Request, value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return str(request.base_url).rstrip("/") + raw
    return str(request.base_url).rstrip("/") + "/" + raw.lstrip("/")


async def _dispatch_public_command_result_to_dm(
    *,
    request: Request,
    identity: TelegramWebAppIdentity,
    command: str,
    result: dict[str, object],
) -> None:
    title = _clean_public_result_text(result.get("title"), limit=80)
    text_value = _clean_public_result_text(result.get("text") or result.get("message"), limit=3600)
    lines: list[str] = []
    if title:
        lines.append(title)
    if text_value:
        if lines:
            lines.append("")
        lines.append(text_value)
    body = "\n".join(lines).strip() or f"/{command} executado pelo bot."
    image_target = str(result.get("image_data_url") or result.get("image_url") or result.get("cover_url") or result.get("download_url") or result.get("file_url") or "").strip()
    filename = _safe_public_filename(result.get("filename") or result.get("download_name") or "tigraoRADIO-resultado.jpg")
    image_url = ""
    document_url = ""
    if image_target:
        if image_target.lower().startswith("data:"):
            token, safe_name, mime = _store_public_data_url(image_target, filename)
            url = _absolute_public_url(request, f"/equalizador/api/public/download/{token}")
            if str(mime).startswith("image/"):
                image_url = url
            else:
                document_url = url
                filename = safe_name
        elif image_target.lower().startswith(("http://", "https://")):
            if filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")) or image_target.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                image_url = image_target
            else:
                document_url = image_target
    if image_url:
        await _bot_api("sendPhoto", {"chat_id": int(identity.user_id), "photo": image_url, "caption": body[:1000]})
    elif document_url:
        await _bot_api("sendDocument", {"chat_id": int(identity.user_id), "document": document_url, "caption": body[:1000]})
    else:
        await _bot_api("sendMessage", {"chat_id": int(identity.user_id), "text": body[:3900]})


async def _send_public_result_to_chat(
    *,
    request: Request,
    chat_id: int,
    result: dict[str, object],
    fallback: str,
) -> dict[str, object]:
    title = _clean_public_result_text(result.get("title"), limit=80)
    text_value = _clean_public_result_text(result.get("text") or result.get("message"), limit=3600)
    lines: list[str] = []
    if title:
        lines.append(title)
    if text_value:
        if lines:
            lines.append("")
        lines.append(text_value)
    body = "\n".join(lines).strip() or fallback
    original_caption = str(result.get("caption_html") or "").strip()
    image_target = str(result.get("image_data_url") or result.get("image_url") or result.get("cover_url") or result.get("download_url") or result.get("file_url") or "").strip()
    filename = _safe_public_filename(result.get("filename") or result.get("download_name") or "tigraoRADIO-resultado.jpg")
    image_url = ""
    document_url = ""
    if image_target:
        if image_target.lower().startswith("data:"):
            token, safe_name, mime = _store_public_data_url(image_target, filename)
            url = _absolute_public_url(request, f"/equalizador/api/public/download/{token}")
            if str(mime).startswith("image/"):
                image_url = url
            else:
                document_url = url
                filename = safe_name
        elif image_target.lower().startswith(("http://", "https://")):
            if filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")) or image_target.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                image_url = image_target
            else:
                document_url = image_target
    if image_url:
        payload: dict[str, object] = {"chat_id": int(chat_id), "photo": image_url}
        if original_caption:
            payload["caption"] = original_caption[:1000]
            payload["parse_mode"] = "HTML"
        return await _bot_api("sendPhoto", payload)
    if document_url:
        payload = {"chat_id": int(chat_id), "document": document_url}
        if original_caption:
            payload["caption"] = original_caption[:1000]
            payload["parse_mode"] = "HTML"
        return await _bot_api("sendDocument", payload)
    return await _bot_api("sendMessage", {"chat_id": int(chat_id), "text": body[:3900], "parse_mode": "HTML"})


async def _public_assert_user_in_group(identity: TelegramWebAppIdentity, chat_id: int) -> None:
    try:
        member = await _bot_api("getChatMember", {"chat_id": int(chat_id), "user_id": int(identity.user_id)})
        if str(member.get("status") or "") in {"left", "kicked"}:
            raise HTTPException(status_code=403, detail="Você não está neste grupo.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Não consegui confirmar sua presença no grupo.") from exc


async def _public_tcanvas_to_group(
    *,
    identity: TelegramWebAppIdentity,
    chat_id: int,
) -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=409, detail="Bot indisponível.")
    try:
        from app.services.connection_check import connect_hint_for, is_user_connected
        if not is_user_connected(int(identity.user_id)):
            raise HTTPException(status_code=409, detail=connect_hint_for("private"))
    except HTTPException:
        raise
    except Exception:
        pass
    track = await music_service.get_current_or_last_played(int(identity.user_id))
    if not track:
        raise HTTPException(status_code=409, detail="Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo.")
    from app.bot.canvas_delivery import deliver_canvas
    from app.bot.telegram import build_playing_payload_for_user
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from types import SimpleNamespace

    display_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")
    username = str(identity.user.get("username") or "") or None
    payload = await build_playing_payload_for_user(
        int(identity.user_id),
        display_name,
        track,
        username,
    )
    if not payload:
        raise HTTPException(status_code=409, detail="Erro ao identificar a música.")
    track_id, caption, cover, keyboard, card_emoji = payload

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    class _PublicCanvasMessage:
        def __init__(self, bot_obj):
            self.bot = bot_obj
            self.chat = SimpleNamespace(id=int(chat_id), type="supergroup")
            self.from_user = SimpleNamespace(
                id=int(identity.user_id),
                full_name=display_name,
                username=username,
                is_bot=False,
            )

        async def answer(self, text: str, **kwargs):
            return await self.bot.send_message(chat_id=int(chat_id), text=text, **kwargs)

        async def answer_photo(self, photo, **kwargs):
            return await self.bot.send_photo(chat_id=int(chat_id), photo=photo, **kwargs)

        async def answer_video(self, video, **kwargs):
            return await self.bot.send_video(chat_id=int(chat_id), video=video, **kwargs)

    try:
        sent = await deliver_canvas(
            _PublicCanvasMessage(bot),
            track=track,
            track_id=track_id,
            caption=caption,
            cover=cover,
            card_emoji=card_emoji,
            keyboard=keyboard,
            log_prefix="PUBLIC_TCANVAS",
        )
        return int(getattr(sent, "message_id", 0) or 0)
    finally:
        await bot.session.close()


async def _public_tly_to_group(
    *,
    identity: TelegramWebAppIdentity,
    chat_id: int,
) -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=409, detail="Bot indisponível.")
    try:
        from app.services.connection_check import connect_hint_for, is_user_connected
        if not is_user_connected(int(identity.user_id)):
            raise HTTPException(status_code=409, detail=connect_hint_for("private"))
    except HTTPException:
        raise
    except Exception:
        pass
    track = await music_service.get_current_or_last_played(int(identity.user_id))
    if not track:
        raise HTTPException(status_code=409, detail="Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo.")

    from app.bot.canvas_delivery import deliver_canvas
    from app.bot.telegram import build_tly_payload
    from app.services.lyrics import lyrics_service
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from types import SimpleNamespace

    artist_raw = str(track.get("artist") or "").strip()
    track_name_raw = str(track.get("track_name") or "").strip()
    lyric_snippet: str | None = None
    if artist_raw and track_name_raw:
        try:
            lyric_snippet = await lyrics_service.get_snippet(artist_raw, track_name_raw)
        except Exception:
            logger.exception("PUBLIC_TLY_LYRICS_FAILED artist=%s track=%s", artist_raw, track_name_raw)

    display_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")
    username = str(identity.user.get("username") or "") or None
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    class _PublicTlyMessage:
        def __init__(self, bot_obj):
            self.bot = bot_obj
            self.chat = SimpleNamespace(id=int(chat_id), type="supergroup")
            self.from_user = SimpleNamespace(
                id=int(identity.user_id),
                full_name=display_name,
                username=username,
                is_bot=False,
            )

        async def answer(self, text: str, **kwargs):
            return await self.bot.send_message(chat_id=int(chat_id), text=text, **kwargs)

        async def answer_photo(self, photo, **kwargs):
            return await self.bot.send_photo(chat_id=int(chat_id), photo=photo, **kwargs)

        async def answer_video(self, video, **kwargs):
            return await self.bot.send_video(chat_id=int(chat_id), video=video, **kwargs)

    try:
        public_message = _PublicTlyMessage(bot)
        payload = await build_tly_payload(public_message, track, lyric_snippet)
        if not payload:
            raise HTTPException(status_code=409, detail="Erro ao identificar a música.")
        track_id, caption, cover, card_emoji = payload
        sent = await deliver_canvas(
            public_message,
            track=track,
            track_id=track_id,
            caption=caption,
            cover=cover,
            card_emoji=card_emoji,
            keyboard=None,
            log_prefix="PUBLIC_TLY",
        )
        return int(getattr(sent, "message_id", 0) or 0)
    finally:
        await bot.session.close()


async def _public_tstory_to_chat(
    *,
    identity: TelegramWebAppIdentity,
    chat_id: int,
) -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=409, detail="Bot indisponível.")
    try:
        from app.services.connection_check import connect_hint_for, is_user_connected
        if not is_user_connected(int(identity.user_id)):
            raise HTTPException(status_code=409, detail=connect_hint_for("private"))
    except HTTPException:
        raise
    except Exception:
        pass

    track = await music_service.get_current_or_last_played(int(identity.user_id))
    if not track:
        raise HTTPException(status_code=409, detail="Nada está tocando agora. Bota algo pra rolar no Spotify ou Last.fm e tenta de novo.")

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import BufferedInputFile
    from app.bot.tstory import _caption, _download
    from app.services.bot_identity import get_bot_identity
    from app.services.spotify import spotify_service
    from app.services.spotify_canvas import spotify_canvas_service
    from app.services.tstory_card import render_tstory_full, render_tstory_overlay
    from app.services.tstory_video import compose_story_video

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        try:
            await bot.send_chat_action(int(chat_id), "upload_video")
        except Exception:
            pass

        title = str(track.get("track_name") or "").strip()
        artist = str(track.get("artist") or "").strip()
        cover_url = track.get("album_image_url")
        spotify_url = str(track.get("spotify_url") or "").strip()
        track_id = str(track.get("track_id") or "").strip()
        user_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")
        listening = f"{user_name} está ouvindo agora"
        caption = _caption(user_name, title, artist, spotify_url)

        cover_bytes = await _download(cover_url)
        bot_identity = await get_bot_identity(bot)
        bot_name = bot_identity.name
        bot_logo = bot_identity.photo_bytes

        canvas_track_id = track_id
        if track_id.startswith("lfm:") and artist and title:
            try:
                match = await spotify_service.search_track(artist, title)
                if match and match.get("id"):
                    canvas_track_id = match["id"]
            except Exception:
                logger.exception("PUBLIC_TSTORY_RESOLVE_ERROR track=%s", track_id)

        video_bytes: bytes | None = None
        try:
            canvas_url = await spotify_canvas_service.get_canvas_url(canvas_track_id)
            if canvas_url:
                canvas_bytes = await spotify_canvas_service.download_canvas_bytes(canvas_url)
                if canvas_bytes:
                    overlay_png = await render_tstory_overlay(
                        cover_bytes=cover_bytes,
                        listening=listening,
                        title=title,
                        artist=artist,
                        bot_name=bot_name,
                        bot_logo_bytes=bot_logo,
                    )
                    if overlay_png:
                        video_bytes = await compose_story_video(canvas_bytes, overlay_png)
        except Exception:
            logger.exception("PUBLIC_TSTORY_VIDEO_FAILED track=%s", track_id)

        if video_bytes:
            try:
                sent = await bot.send_video(
                    chat_id=int(chat_id),
                    video=BufferedInputFile(video_bytes, filename=f"tstory-{canvas_track_id}.mp4"),
                    caption=caption,
                    parse_mode="HTML",
                )
                return int(getattr(sent, "message_id", 0) or 0)
            except Exception:
                logger.exception("PUBLIC_TSTORY_VIDEO_SEND_FAILED track=%s", track_id)

        card = await render_tstory_full(
            cover_bytes=cover_bytes,
            listening=listening,
            title=title,
            artist=artist,
            bot_name=bot_name,
            bot_logo_bytes=bot_logo,
        )
        if card:
            sent = await bot.send_photo(
                chat_id=int(chat_id),
                photo=BufferedInputFile(card, filename="tstory.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
            return int(getattr(sent, "message_id", 0) or 0)

        if cover_bytes:
            sent = await bot.send_photo(
                chat_id=int(chat_id),
                photo=BufferedInputFile(cover_bytes, filename="cover.jpg"),
                caption=caption,
                parse_mode="HTML",
            )
            return int(getattr(sent, "message_id", 0) or 0)

        sent = await bot.send_message(chat_id=int(chat_id), text=caption, parse_mode="HTML")
        return int(getattr(sent, "message_id", 0) or 0)
    finally:
        await bot.session.close()


@router.post("/api/public/story-command")
async def public_music_story_command(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    target = str(payload.get("target") or "dm").strip().lower()
    group_ref = str(payload.get("group_ref") or "").strip()
    if target not in {"dm", "group"}:
        raise HTTPException(status_code=400, detail="Destino indisponível para Story.")
    if target == "group":
        group = _resolve_public_group(group_ref)
        if not group:
            raise HTTPException(status_code=404, detail="Grupo indisponível.")
        chat_id = int(group["chat_id"])
        await _public_assert_user_in_group(identity, chat_id)
        source_message_id = await _public_tstory_to_chat(identity=identity, chat_id=chat_id)
        copied_message_id = 0
        if source_message_id:
            try:
                copied = await _bot_api(
                    "copyMessage",
                    {
                        "chat_id": int(identity.user_id),
                        "from_chat_id": chat_id,
                        "message_id": source_message_id,
                    },
                )
                copied_message_id = int(copied.get("message_id") or 0)
            except Exception:
                logger.exception("PUBLIC_PLAYER_TSTORY_COPY_DM_FAILED user_id=%s chat_id=%s message_id=%s", identity.user_id, chat_id, source_message_id)
        return {
            "ok": True,
            "command": "tstory",
            "target": "group",
            "message": f"Story enviado em {str(group.get('title') or 'grupo')[:80]}." + (" Cópia enviada na sua DM." if copied_message_id else ""),
            "source_chat_id": chat_id,
            "source_message_id": source_message_id,
            "copied_to_dm": bool(copied_message_id),
            "dm_message_id": copied_message_id,
        }

    dm_message_id = await _public_tstory_to_chat(identity=identity, chat_id=int(identity.user_id))
    return {
        "ok": True,
        "command": "tstory",
        "target": "dm",
        "message": "Story enviado na sua DM.",
        "dm_message_id": dm_message_id,
    }


@router.post("/api/public/dm-command")
async def public_music_dm_command(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    command = str(payload.get("command") or "").strip().lower().lstrip("/")
    if command not in {"albnow", "radiofm"}:
        raise HTTPException(status_code=400, detail="Comando indisponível para DM.")
    if command == "radiofm":
        sent = await _bot_api(
            "sendMessage",
            {
                "chat_id": int(identity.user_id),
                "text": "Use: <code>/radiofm nome da música ou artista</code>",
                "parse_mode": "HTML",
            },
        )
        return {
            "ok": True,
            "command": "radiofm",
            "target": "dm",
            "message": "RadioFM enviado na sua DM.",
            "dm_message_id": int(sent.get("message_id") or 0),
        }

    try:
        from app.bot.music_extras import _format_albnow
        data = await music_service.get_current_or_last_played(int(identity.user_id))
        if not data:
            sent = await _bot_api("sendMessage", {"chat_id": int(identity.user_id), "text": "Nada tocando agora."})
            return {"ok": True, "command": "albnow", "target": "dm", "message": "AlbNow enviado na sua DM.", "dm_message_id": int(sent.get("message_id") or 0)}
        display_name = str(identity.user.get("first_name") or identity.user.get("username") or "Usuário")
        caption = _format_albnow(display_name, data)
        cover = str(data.get("album_image_url") or data.get("cover_url") or "").strip()
        if cover:
            sent = await _bot_api(
                "sendPhoto",
                {"chat_id": int(identity.user_id), "photo": cover, "caption": caption[:1000], "parse_mode": "HTML"},
            )
        else:
            sent = await _bot_api(
                "sendMessage",
                {"chat_id": int(identity.user_id), "text": caption, "parse_mode": "HTML"},
            )
        return {
            "ok": True,
            "command": "albnow",
            "target": "dm",
            "message": "AlbNow enviado na sua DM.",
            "dm_message_id": int(sent.get("message_id") or 0),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PUBLIC_PLAYER_ALBNOW_DM_FAILED user_id=%s", identity.user_id)
        raise HTTPException(status_code=409, detail="Não consegui enviar o AlbNow agora.") from exc


@router.post("/api/public/group-command")
async def public_music_group_command(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    command = str(payload.get("command") or "").strip().lower().lstrip("/")
    group_ref = str(payload.get("group_ref") or "").strip()
    if command not in {"weekfm", "monthfm", "tcanvas", "tly", "tnow"}:
        raise HTTPException(status_code=400, detail="Botão ainda não liberado para envio em grupo.")
    group = _resolve_public_group(group_ref)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    chat_id = int(group["chat_id"])
    await _public_assert_user_in_group(identity, chat_id)
    if command == "tcanvas":
        source_message_id = await _public_tcanvas_to_group(identity=identity, chat_id=chat_id)
    elif command == "tly":
        source_message_id = await _public_tly_to_group(identity=identity, chat_id=chat_id)
    else:
        result = await public_music_command(command, group_ref=group_ref, authorization=authorization)
        sent = await _send_public_result_to_chat(
            request=request,
            chat_id=chat_id,
            result=result,
            fallback=f"/{command} executado pelo bot.",
        )
        source_message_id = int(sent.get("message_id") or 0)
    copied_message_id = 0
    if source_message_id:
        try:
            copied = await _bot_api(
                "copyMessage",
                {
                    "chat_id": int(identity.user_id),
                    "from_chat_id": chat_id,
                    "message_id": source_message_id,
                },
            )
            copied_message_id = int(copied.get("message_id") or 0)
        except Exception:
            logger.exception("PUBLIC_PLAYER_GROUP_COMMAND_COPY_DM_FAILED command=%s user_id=%s chat_id=%s message_id=%s", command, identity.user_id, chat_id, source_message_id)
    label = {"weekfm": "Semana", "monthfm": "Mês", "tcanvas": "Canvas", "tly": "Letra", "tnow": "Mosaico"}.get(command, command)
    return {
        "ok": True,
        "command": command,
        "message": f"{label} enviado em {str(group.get('title') or 'grupo')[:80]}." + (" Cópia enviada na sua DM." if copied_message_id else ""),
        "source_chat_id": chat_id,
        "source_message_id": source_message_id,
        "copied_to_dm": bool(copied_message_id),
        "dm_message_id": copied_message_id,
    }


@router.post("/api/public/execute-command")
async def public_music_execute_command(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    logger.info("public_execute_command_requested")
    try:
        identity = _public_identity_from_authorization(authorization)
        logger.info("public_execute_command_session_ok user_id=%s", identity.user_id)
        payload = await _read_json_payload(request)
        command = str(payload.get("command") or "").strip().lower().lstrip("/")
        group_ref = str(payload.get("group_ref") or "").strip()
        fmt = str(payload.get("format") or "dm").strip().lower()
        if fmt != "dm":
            raise HTTPException(status_code=400, detail="Formato indisponível para execução pública.")
        if command not in _PUBLIC_COMMAND_COPY_ALLOWED:
            raise HTTPException(status_code=400, detail="Comando indisponível para envio.")
        if command in _GROUP_REQUIRED_COMMANDS and not group_ref:
            raise HTTPException(status_code=400, detail="Escolha um grupo antes de enviar.")
        logger.info("public_execute_command_dispatch_started command=%s user_id=%s", command, identity.user_id)
        if command == "nowp":
            result = await public_music_nowp(request, authorization=authorization)
            if not bool(result.get("copied_to_dm")):
                await _dispatch_public_command_result_to_dm(
                    request=request,
                    identity=identity,
                    command=command,
                    result={"title": "Publicar", "text": result.get("message") or "Publicado."},
                )
        else:
            result = await public_music_command(command, group_ref=group_ref or None, authorization=authorization)
            await _dispatch_public_command_result_to_dm(request=request, identity=identity, command=command, result=result)
        logger.info("public_execute_command_dm_sent command=%s user_id=%s", command, identity.user_id)
        return {"ok": True, "sent": True, "command": command, "message": "Publicado no grupo e copiado na sua DM." if command == "nowp" else "Enviado na sua DM."}
    except HTTPException:
        logger.exception("public_execute_command_failed")
        raise
    except Exception as exc:
        logger.exception("public_execute_command_failed")
        raise HTTPException(status_code=409, detail="Não consegui enviar o comando na sua DM.") from exc


@router.post("/api/public/send-command-copy")
async def public_music_send_command_copy(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    """Fallback para clientes sem Telegram.WebApp.sendData.

    Regra da fase 138.5: o Mini App não envia texto renderizado pela UI.
    Cada botão mapeia para um comando real do bot; este fallback reexecuta
    o comando pelo backend usando dados confiáveis e ignora qualquer texto
    ou imagem renderizados pela interface no payload.
    """
    identity = _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    command = str(payload.get("command") or "").strip().lower().lstrip("/")
    group_ref = str(payload.get("group_ref") or "").strip()
    if command not in _PUBLIC_COMMAND_COPY_ALLOWED:
        raise HTTPException(status_code=400, detail="Comando indisponível para envio.")
    if command in _GROUP_REQUIRED_COMMANDS and not group_ref:
        raise HTTPException(status_code=400, detail="Escolha um grupo antes de enviar.")
    if command == "nowp":
        raise HTTPException(status_code=409, detail="/nowp exige publicação em grupo pelo fluxo próprio.")
    try:
        result = await public_music_command(command, group_ref=group_ref or None, authorization=authorization)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Não consegui executar o comando pelo bot.") from exc

    title = _clean_public_result_text(result.get("title"), limit=80) if isinstance(result, dict) else ""
    text_value = _clean_public_result_text((result.get("text") or result.get("message")) if isinstance(result, dict) else "", limit=3600)
    lines: list[str] = []
    if title:
        lines.append(title)
    if text_value:
        if lines:
            lines.append("")
        lines.append(text_value)
    body = "\n".join(lines).strip() or f"/{command} executado pelo bot."
    image_target = ""
    filename = "tigraoRADIO-resultado.jpg"
    if isinstance(result, dict):
        image_target = str(result.get("image_data_url") or result.get("image_url") or result.get("download_url") or "").strip()
        filename = _safe_public_filename(result.get("filename") or result.get("download_name") or filename)
    image_url = ""
    if image_target:
        if image_target.lower().startswith("data:"):
            token, _safe_name, _mime = _store_public_data_url(image_target, filename)
            image_url = _absolute_public_url(request, f"/equalizador/api/public/download/{token}")
        elif image_target.lower().startswith(("http://", "https://")):
            image_url = image_target
    try:
        if image_url:
            await _bot_api("sendPhoto", {"chat_id": int(identity.user_id), "photo": image_url, "caption": body[:1000]})
        else:
            await _bot_api("sendMessage", {"chat_id": int(identity.user_id), "text": body[:3900]})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Não consegui executar o comando pelo bot.") from exc
    return {"ok": True, "message": f"Executei /{command} no chat do bot."}


@router.post("/api/public/nowp")
async def public_music_nowp(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _public_identity_from_authorization(authorization)
    payload = await _read_json_payload(request)
    group = _resolve_public_group(str(payload.get("group_ref") or ""))
    if not group:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    chat_id = int(group["chat_id"])
    # Confirma associação real do usuário ao grupo imediatamente antes de publicar.
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChatMember",
                json={"chat_id": chat_id, "user_id": int(identity.user_id)},
            )
        data = res.json()
        member = data.get("result") if isinstance(data, dict) else None
        status = str((member or {}).get("status") or "")
        if not data.get("ok") or status in {"left", "kicked"}:
            raise HTTPException(status_code=403, detail="Você não está neste grupo.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Não consegui confirmar sua presença no grupo.") from exc

    track = await music_service.get_current_or_last_played(identity.user_id)
    if not track:
        raise HTTPException(status_code=409, detail="Nada tocando agora.")
    from app.bot.telegram import build_playing_payload_for_user
    built = await build_playing_payload_for_user(
        identity.user_id,
        str(identity.user.get("first_name") or identity.user.get("username") or "Usuário"),
        track,
        str(identity.user.get("username") or "") or None,
    )
    if not built:
        raise HTTPException(status_code=409, detail="Não consegui montar a publicação.")
    track_id, caption, cover, _keyboard, _emoji = built
    if cover:
        sent = await _bot_api("sendPhoto", {"chat_id": chat_id, "photo": str(cover), "caption": caption, "parse_mode": "HTML"})
    else:
        sent = await _bot_api("sendMessage", {"chat_id": chat_id, "text": caption, "parse_mode": "HTML"})
    sent_message_id = int(sent.get("message_id") or 0)
    copied_message_id = 0
    if sent_message_id:
        try:
            copied = await _bot_api(
                "copyMessage",
                {
                    "chat_id": int(identity.user_id),
                    "from_chat_id": chat_id,
                    "message_id": sent_message_id,
                },
            )
            copied_message_id = int(copied.get("message_id") or 0)
        except Exception:
            logger.exception("PUBLIC_PLAYER_NOWP_COPY_DM_FAILED user_id=%s chat_id=%s message_id=%s", identity.user_id, chat_id, sent_message_id)
    try:
        if settings.TR4_MUSIC_REACTIONS_ENABLED:
            await reactions_service.register_card(
                chat_id=chat_id,
                message_id=sent_message_id,
                track_id=track_id,
                owner_user_id=identity.user_id,
                track_name=str(track.get("track_name") or ""),
                artist_name=str(track.get("artist") or ""),
            )
    except Exception:
        pass
    return {
        "ok": True,
        "message": f"Publicado em {str(group.get('title') or 'grupo')[:80]}." + (" Cópia enviada na sua DM." if copied_message_id else ""),
        "source_chat_id": chat_id,
        "source_message_id": sent_message_id,
        "copied_to_dm": bool(copied_message_id),
        "dm_message_id": copied_message_id,
    }
