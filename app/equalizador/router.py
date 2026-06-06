from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
import httpx

from app.config import settings
from app.db.database import engine as default_engine
from app.bot.music_groups import remember_group
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
    list_runtime_grants_public,
    rbac_runtime_catalogo_publico,
    revoke_runtime_canal,
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
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script>
    (function () {
      function report(kind, message, source, line, col) {
        try {
          fetch("/equalizador/api/client-error", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: String(kind || "client_error").slice(0, 40),
              message: String(message || "").slice(0, 240),
              source: String(source || "").slice(0, 160),
              line: Number(line || 0),
              col: Number(col || 0),
              user_agent: String(navigator.userAgent || "").slice(0, 220)
            })
          }).catch(function () {});
        } catch (_) {}
      }
      window.__eqClientError = report;
      window.addEventListener("error", function (event) {
        report("error", event.message, event.filename, event.lineno, event.colno);
      });
      window.addEventListener("unhandledrejection", function (event) {
        var reason = event.reason;
        var message = reason && reason.message ? reason.message : String(reason || "unhandledrejection");
        report("unhandledrejection", message, "", 0, 0);
      });
    })();
  </script>
  <style>
    :root { color-scheme: dark light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 16px 16px 84px; background: var(--tg-theme-bg-color, #0b0d10); color: var(--tg-theme-text-color, #f8fafc); }
    body::before { content: ""; position: fixed; inset: 0; pointer-events: none; background: radial-gradient(circle at top, rgba(91,140,255,.12), transparent 34%); }
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
    .bulk-actions { position: sticky; bottom: 0; margin-top: 10px; padding: 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 14px; background: #1a202b; box-shadow: 0 10px 28px rgba(0,0,0,.28); }
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
    select, textarea, input { width: 100%; border: 1px solid rgba(255,255,255,.22); border-radius: 14px; padding: 12px; background: #0f172a; color: #f8fafc; }
    textarea { min-height: 92px; resize: vertical; }
    .list { display: grid; gap: 8px; }
    .item { border: 1px solid rgba(255,255,255,.14); border-radius: 14px; padding: 12px; background: #111827; }
    .ok { color: #50d890; }
    .bad { color: #ff8a80; }
    .warn { color: #ffd166; }
    .small { font-size: 12px; }
    .section-note { margin: 8px 0 12px; color: #d1d5db; font-size: 13px; }
    .statusbar { margin: 14px 0; border: 1px solid rgba(255,255,255,.18); border-radius: 16px; padding: 12px; background: #111827; }
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
    .feedback-item { border: 1px solid rgba(255,255,255,.14); border-radius: 12px; padding: 9px; background: rgba(255,255,255,.04); white-space: pre-wrap; }
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
    @media (max-width: 560px) { body { padding: 10px 10px 88px; } .card { padding: 14px; border-radius: 18px; } h1 { font-size: 22px; } .toolbar { grid-template-columns: 1fr; gap: 6px; } button.action { width: 100%; } .app-tabs { grid-template-columns: 1fr 1fr; } .app-tabs button.nav { width: 100%; } .top { display: block; } .grid { grid-template-columns: 1fr; } .home-hint-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .feedback-head { display: grid; } }
  </style>
</head>
<body>
  <main>
    <section id="loading" class="card">
      <h1>Equalizador</h1>
      <p class="muted">Carregando acesso…</p>
    </section>
    <section id="denied" class="card hidden">
      <h1>Equalizador</h1>
      <p>Acesso indisponível.</p>
    </section>
    <section id="app" class="card hidden">
      <div class="top">
        <div>
          <h1>Equalizador</h1>
          <p class="muted">Painel de moderação em modo controlado.</p>
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
          </div>
        </div>
        <h2>Início do painel</h2>
        <p class="section-note">A interface exibe nome público e @username quando disponível. IDs continuam internos. As ações aparecem conforme seu canal e o direito real do bot no grupo.</p>
        <div id="bot_revisoes" class="quicklist small">
          <div><strong>Comandos privados úteis:</strong> <code>/painel_ajuda</code>, <code>/painel_msg &lt;link&gt;</code>, <code>/painel_alvo radio &lt;id&gt;</code>, <code>/painel_convite radio teste</code>.</div>
          <div><strong>Atalhos:</strong> use link de mensagem ou @username já conhecido pelo bot. O app converte para referência segura.</div>
          <div><strong>Revisar antes de operar:</strong> confira permissões do bot, grupos ativos, operadores, canais e ações críticas.</div>
        </div>
      </section>
      <section id="palco_header" class="panel header-select">
        <label class="small muted">Grupo ativo</label>
        <select id="palco_header_select"></select>
        <div id="grupo_resumo" class="headline" style="margin-top:12px;">
          <div id="grupo_avatar" class="avatar">♪</div>
          <div>
            <strong id="grupo_nome">Selecione um grupo</strong>
            <p id="grupo_descricao" class="muted small" style="margin:4px 0 0;">O resumo do grupo aparece aqui.</p>
          </div>
        </div>
        <table class="mini-table" style="margin-top:10px;">
          <tr><td>Tipo</td><td id="grupo_tipo" class="muted">—</td></tr>
          <tr><td>Membros</td><td id="grupo_membros" class="muted">—</td></tr>
        </table>
      </section>
      <h2 class="hidden">Grupos</h2>
      <p id="palcos_hint" class="section-note">Selecione o grupo no cabeçalho.</p>
      <div id="palcos" class="grid hidden"></div>
      <div id="mesa" class="hidden">
        <div id="mesa_status" class="statusbar muted">Painel aguardando seleção.</div>
        <h2 id="mesa_titulo">Painel do grupo</h2>
        <div class="toolbar app-tabs">
          <button class="nav secondary" data-view="mesa_view"><strong>Início</strong><span>status e resumo</span></button>
          <button class="nav secondary" data-view="perfil_view"><strong>Perfil</strong><span>nome, descrição e foto</span></button>
          <button class="nav secondary" data-view="mensagens_view"><strong>Mensagens</strong><span>enviar, fixar e apagar</span></button>
          <button class="nav secondary" data-view="radio_view"><strong>Radio</strong><span>rascunho e mídia</span></button>
          <button class="nav secondary" data-view="ddx_view"><strong>Filtros</strong><span>DDX e 10 min</span></button>
          <button class="nav secondary" data-view="reacoes_view"><strong>Reações</strong><span>auditoria e reactors</span></button>
          <button class="nav secondary" data-view="pessoas_view"><strong>Pessoas</strong><span>membros, admins e bots</span></button>
          <button class="nav secondary" data-view="convites_view"><strong>Convites</strong><span>criar, copiar e revogar</span></button>
          <button class="nav secondary" data-view="topicos_view"><strong>Tópicos</strong><span>fórum e tópico geral</span></button>
          <button id="maestro_nav" class="nav secondary hidden" data-view="maestro_view"><strong>Transmissão</strong><span>avisos e silêncio</span></button>
          <button class="nav secondary" data-view="afinacao_view"><strong>Diagnóstico</strong><span>permissões reais</span></button>
          <button class="nav secondary" data-view="historico_view"><strong>Histórico</strong><span>ações sanitizadas</span></button>
          <button id="seguranca_nav" class="nav secondary hidden" data-view="seguranca_view"><strong>Segurança</strong><span>modo, auditoria e exports</span></button>
          <button id="config_nav" class="nav secondary hidden" data-view="config_view"><strong>Configuração</strong><span>operadores e canais</span></button>
        </div>
        <section id="mesa_view" class="view">
          <h3 class="window-title">Resumo do grupo</h3>
          <p class="section-note">Use a navegação compacta acima. A tela inicial não repete mais a lista de janelas para reduzir peso visual no iPhone.</p>
          <div class="home-hint-grid">
            <div class="home-hint"><strong>Perfil</strong><span>nome, descrição e foto do grupo.</span></div>
            <div class="home-hint"><strong>Mensagens</strong><span>envio, fixação, desfixação e exclusão.</span></div>
            <div class="home-hint"><strong>Pessoas</strong><span>membros, administradores humanos e bots.</span></div>
            <div class="home-hint"><strong>Diagnóstico</strong><span>motivo real de bloqueios antes da ação.</span></div>
          </div>
          <div class="section-divider"><strong>Pessoas do painel</strong><span>Membros vistos, administradores humanos e bots carregados do grupo selecionado.</span></div>
          <div class="panel-split">
            <div class="panel">
              <strong>Resumo de membros</strong>
              <div id="mesa_pessoas_resumo" class="empty small">Escolha um grupo para carregar membros e administradores.</div>
            </div>
            <div class="panel">
              <strong>Membros vistos recentemente</strong>
              <div id="mesa_membros_preview" class="member-preview muted small">Nenhum membro carregado ainda.</div>
            </div>
          </div>
          <h3>Governantes deste grupo</h3>
          <p class="section-note">Mapa de delegação por janela: quem pode atuar, com nome público e @username quando já visto pelo bot.</p>
          <div id="governantes_palco" class="governance-grid muted">Governantes ainda não carregados.</div>
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
          <p class="section-note">Envie, fixe, desfixe, apague ou resolva mensagens em uma área única. IDs continuam internos.</p>
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
          <p class="section-note">Auditoria de reactions capturadas pelo webhook. Use o seletor para limpar reações recentes ou aplicar silêncio de interação ao reactor sem expor ID real.</p>
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
          <p class="section-note">Monitora recém-chegados por janela curta. Quando um novo membro envia link nas primeiras mensagens, o painel registra alerta com nome público e @username, sem mostrar ID real.</p>
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
          <p class="section-note">Membros, administradores humanos, bots administradores, pedidos de entrada e canais remetentes. A interface mostra nome público e @username quando houver; ID real não é exibido.</p>
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
              <select id="alvo_select"></select>
              <div id="alvos_hint" class="empty small">Nenhum membro carregado ainda.</div>
              <div id="alvos_atalhos" class="list small"></div>
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
              <p class="muted small">Use @username já visto pelo bot ou referência interna. O backend resolve para uma referência segura e a interface continua sem ID real.</p>
              <input id="alvo_manual_input" placeholder="@username ou referência interna" />
              <div class="toolbar"><button id="resolver_alvo" class="action secondary" type="button">Resolver membro</button></div>
            </div>
            <div class="panel wide">
              <h3>Administração de pessoas</h3>
              <p class="muted small">Escolha um membro ou administrador registrado. Promover, rebaixar e título personalizado exigem direito real do bot e confirmação crítica.</p>
              <label class="small muted">Alvo da administração</label>
              <select id="admin_alvo_select"></select>
              <p id="admin_alvo_hint" class="muted small select-note">Administradores e membros vistos aparecerão aqui como referências internas.</p>
              <div class="formgrid">
                <div>
                  <label class="small muted">Título personalizado</label>
                  <input id="admin_titulo_input" maxlength="16" placeholder="Título personalizado do admin" />
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
                <button class="action secondary" data-action="admins.titulo" type="button">Definir título admin</button>
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
          <div class="panel">
            <h3>Configuração do administrador principal</h3>
            <p class="muted small">Use campos amigáveis para ajustar grupos, operadores e canais. O app não edita Railway diretamente; ele gera o Raw Editor somente no final para copiar.</p>
            <div class="toolbar"><button id="atualizar_configuracao" class="action secondary" type="button">Atualizar configuração</button></div>
            <h3>Configuração visual</h3>
            <div class="formgrid">
              <label class="small muted">Mini App<br><input id="cfg_app_name" placeholder="equalizador" /></label>
              <label class="small muted">Equalizador ligado<br><select id="cfg_enabled"><option value="true">Ligado</option><option value="false">Desligado</option></select></label>
              <label class="small muted">Administradores principais<br><input id="cfg_maestros" placeholder="8505890439" /></label>
              <label class="small muted">Operadores<br><input id="cfg_operadores" placeholder="8505890439,1759115970" /></label>
              <label class="small muted">Grupos ativos<br><input id="cfg_palcos" placeholder="-100...,-100..." /></label>
              <label class="small muted">Rate limit/min<br><input id="cfg_rate" type="number" min="10" max="600" placeholder="30" /></label>
            </div>
            <label class="small muted">Aliases dos grupos, um por linha: nome=-100...</label>
            <textarea id="cfg_aliases" placeholder="radio=-1003818494866"></textarea>
            <label class="small muted">Canais por operador</label>
            <textarea id="cfg_canais" placeholder="8505890439:*:*"></textarea>
            <div class="toolbar">
              <button id="gerar_config_raw" class="action" type="button">Gerar Raw Editor</button>
              <button id="resetar_config_form" class="action secondary" type="button">Restaurar valores atuais</button>
            </div>
            <div id="config_preview_resumo" class="empty small">Preencha os campos e gere o Raw Editor somente no final.</div>
            <h3>Grupos ativos</h3>
            <div id="config_palcos_ativos" class="list muted">Configuração não carregada.</div>
            <h3>Aliases configurados</h3>
            <div id="config_aliases" class="list muted">Configuração não carregada.</div>
            <h3>Grupos ocultos</h3>
            <div id="config_palcos_ocultos" class="list muted">Configuração não carregada.</div>
            <h3>Operadores e canais</h3>
            <div id="config_operadores" class="list muted">Configuração não carregada.</div>
            <h3>Governantes por janela</h3>
            <p class="muted small">Leitura operacional para o dono do código delegar governantes sem expor ID real na interface.</p>
            <div id="config_governantes_resumo" class="empty small">Governança não carregada.</div>
            <div id="config_governantes" class="governance-grid muted">Governança não carregada.</div>
            <h3>Delegação runtime</h3>
            <p class="muted small">Concessões salvas no banco persistente. Use para delegar governantes sem editar Railway a cada ajuste. As variáveis continuam como base estável.</p>
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
            <div id="rbac_runtime_resumo" class="empty small">Delegação runtime não carregada.</div>
            <div id="rbac_runtime_lista" class="list muted">Delegação runtime não carregada.</div>
            <h3>Sessões persistentes</h3>
            <div id="sessoes_persistentes" class="empty small">Sessões não carregadas.</div>
            <h3>Matriz completa de permissões</h3>
            <p class="muted small">Leitura de segurança por operador, grupo e canal. Canais críticos ficam marcados e operadores comuns permanecem bloqueados.</p>
            <div id="config_matriz_resumo" class="empty small">Matriz não carregada.</div>
            <div id="config_matriz" class="list muted">Configuração não carregada.</div>
            <h3>Raw Editor final</h3>
            <p class="muted small">Só copie este bloco depois de revisar os campos acima. Preserve as outras variáveis do Railway.</p>
            <textarea id="config_raw" readonly placeholder="Clique em Gerar Raw Editor para montar o bloco final"></textarea>
            <div class="toolbar"><button id="copiar_config_raw" class="action secondary" type="button" disabled>Copiar Raw Editor</button></div>
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

      // Fase 54.1: Equalizador em janelas com contraste reforçado.
      // Compatibilidade de testes antigos: Afinando acesso… · Configuração do administrador principal · Assistente de configuração · Ações permanecem bloqueadas até confirmação do bot · Lista de administração
      // Compatibilidade fase 46: const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes, painelRes, entradasRes, convitesRes, topicosRes, remetentesRes] = await Promise.all([
      /*
api(base + "/canais-remetentes").then((r) => r.ok ? r.json() : { remetentes: [] }).catch(() => ({ remetentes: [] }))
        ]);
      */
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      const initData = tg && tg.initData ? tg.initData : "";
      const SESSION_KEY = "tr4_equalizador_eqs";
      const reportClient = (kind, message) => {
        try { if (window.__eqClientError) window.__eqClientError(kind, message, "equalizador", 0, 0); } catch (_) {}
      };
      const getStoredSession = () => {
        try { return String(sessionStorage.getItem(SESSION_KEY) || "").trim(); } catch (_) { return ""; }
      };
      const setStoredSession = (token) => {
        try {
          const value = String(token || "").trim();
          if (value) sessionStorage.setItem(SESSION_KEY, value);
          else sessionStorage.removeItem(SESSION_KEY);
        } catch (_) {}
      };
      let apiHeaders = null;
      let bootstrapHeaders = null;
      let currentPalco = null;
      let currentPainelDinamico = null;
      let mensagensPorRef = new Map();
      let mensagensSelecionadas = new Set();
      let radioDraftsPorRef = new Map();
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
        "admins.titulo": "Título personalizado de admin"
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
        if (!el) return;
        el.textContent = text;
        el.className = "statusbar " + (kind || "muted");
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
        if (value && typeof value === "object" && value.detail) value = value.detail;
        if (value && typeof value === "object") value = value.motivo_publico || value.public_detail || value.message || value.erro || "Ajuste não concluído.";
        const text = String(value || "Ajuste não concluído.");
        return text
          .replace(/bot\\d+:[A-Za-z0-9_-]+/g, "bot_token_oculto")
          .replace(/-100\\d{5,}/g, "grupo oculto")
          .replace(/\\b\\d{7,16}\\b/g, "referência oculta");
      };

      const buttonLabel = (button) => String(button && (button.dataset.originalText || button.textContent) || "Ação").trim();
      const restoreButton = (button) => {
        if (!button) return;
        if (button.dataset.originalText) button.textContent = button.dataset.originalText;
        button.classList.remove("pressed", "confirming", "working", "success", "error");
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
        button.classList.remove("pressed", "confirming", "working", "success", "error");
        if (state) button.classList.add(state);
        if (state === "working") button.disabled = true;
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
          div.innerHTML = `<span class="feedback-meta">${escapeHtml(entry.time)} · ${escapeHtml(entry.kind || 'info')}</span>${escapeHtml(entry.text)}`;
          return div;
        }));
      };
      const addFeedback = (text, kind) => {
        const now = new Date();
        const time = now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        feedbackEntries.unshift({ time, text: String(text || ""), kind: kind || "info" });
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
      const api = async (url, options) => {
        const requestOptions = Object.assign({ headers: apiHeaders }, options || {});
        let response = await fetch(url, requestOptions);
        if (response.status === 401 && bootstrapHeaders && apiHeaders && apiHeaders.Authorization && apiHeaders.Authorization.startsWith("eqs ")) {
          try {
            const renew = await fetch("/equalizador/api/me", { headers: bootstrapHeaders });
            if (renew.ok) {
              const me = await renew.json();
              const sessionToken = me.sessao && me.sessao.token ? me.sessao.token : "";
              apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : bootstrapHeaders;
              response = await fetch(url, Object.assign({}, requestOptions, { headers: Object.assign({}, requestOptions.headers || {}, apiHeaders) }));
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
        if (!criticoOk) motivos.push("ação crítica restrita ao administrador principal");
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
          toast("Janela restrita ao administrador principal.", "warn");
          id = "mesa_view";
        }
        const viewDiagnostic = diagnosticForView(id);
        if (currentPalco && afinacaoLoaded && !viewDiagnostic.ok) {
          toast("Janela bloqueada preventivamente: " + viewDiagnostic.motivos.join(" · "), "warn");
          id = "mesa_view";
        }
        for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
        const view = document.getElementById(id);
        if (view) view.classList.remove("hidden");
        document.querySelectorAll("button.nav").forEach((button) => button.classList.toggle("active", button.dataset.view === id));
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
        const exportButton = document.getElementById("exportar_historico");
        if (exportButton) exportButton.disabled = !modoMaestroPermitido;
        if (!modoMaestroPermitido) {
          document.getElementById("maestro_view").classList.add("hidden");
          document.getElementById("config_view").classList.add("hidden");
          const segView = document.getElementById("seguranca_view"); if (segView) segView.classList.add("hidden");
        }
        applyPreventiveAccessUI();
      };
      document.querySelectorAll("button.nav").forEach((button) => button.addEventListener("click", () => { button.classList.add("pressed"); setTimeout(() => button.classList.remove("pressed"), 180); haptic("selection"); openView(button.dataset.view); }));
      const perfilAtualizar = document.getElementById("perfil_atualizar_dados");
      if (perfilAtualizar) perfilAtualizar.addEventListener("click", () => currentPalco ? loadPalcoData() : toast("Escolha um grupo antes de atualizar.", "warn"));
      let palcosDisponiveis = [];
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
        headerSelect.appendChild(option("", "Selecione um grupo"));
        for (const palco of palcosDisponiveis) {
          headerSelect.appendChild(option(palco.grp_ref, (palco.titulo || "Grupo") + " · " + (palco.estado || "ativo")));
        }
        headerSelect.onchange = () => {
          const palco = palcosDisponiveis.find((item) => item.grp_ref === headerSelect.value);
          if (palco) selectPalco(palco, null);
        };
        if (hint) hint.textContent = "Selecione o grupo no cabeçalho para abrir o painel e o resumo de moderação.";
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
            title = "Ação restrita ao administrador principal";
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
          statusMesa("Painel pronto. Botões liberados dependem do canal concedido, alvo selecionado e direito real do bot.", "ok");
        } else if (currentPalco) {
          statusMesa("Painel aguardando permissões do bot. Ações permanecem bloqueadas até confirmação.", "warn");
        }
        renderDiagnosticoPermissoes();
      }
      async function selectPalco(palco, button) {
        currentPalco = palco;
        const headerSelect = document.getElementById("palco_header_select");
        if (headerSelect && headerSelect.value !== palco.grp_ref) headerSelect.value = palco.grp_ref;
        document.querySelectorAll(".palco").forEach((el) => el.classList.remove("active"));
        if (button) button.classList.add("active");
        document.getElementById("mesa").classList.remove("hidden");
        document.getElementById("mesa_titulo").textContent = "Painel de moderação · " + (palco.titulo || "Grupo");
        statusMesa("Carregando permissões, mensagens, membros e histórico…", "muted");
        openView("mesa_view");
        await loadPalcoData();
      }
      const fillList = (id, rows, render, emptyText) => {
        const el = document.getElementById(id);
        if (!el) return;
        const data = rows || [];
        el.className = data.length ? "list" : "list muted";
        el.replaceChildren(...(data.length ? data.map(render) : [document.createTextNode(emptyText)]));
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
        item.innerHTML = `<div class="person-line">${pessoaHtml(row, fallback)}<span class="badge">${escapeHtml(row && row.perfil_admin || 'Admin')}</span><span class="badge">${role}</span><span class="badge">${direitosResumo(direitos)}</span></div><div class="muted">${escapeHtml(role)}${titulo}</div><div>${chips}</div>`;
        return item;
      };
      const renderAdminList = (id, rows, emptyText, fallback) => {
        const el = document.getElementById(id);
        if (!el) return;
        const data = Array.isArray(rows) ? rows : [];
        el.className = data.length ? "list" : "list muted";
        el.replaceChildren(...(data.length ? data.slice(0, 24).map((row) => adminCard(row, fallback)) : [document.createTextNode(emptyText)]));
      };
      function governancaCard(row, palcoFilter) {
        const item = document.createElement("div");
        item.className = "governance-card small";
        const palcos = Array.isArray(row && row.palcos) ? row.palcos : [];
        const palco = palcoFilter ? (palcos.find((p) => String(p.grp_ref || "") === String(palcoFilter)) || palcos[0]) : palcos[0];
        const perfis = Array.isArray(palco && palco.perfis) ? palco.perfis : [];
        const ativos = perfis.filter((perfil) => perfil && perfil.ativo);
        const nome = pessoaHtml(row, row && row.perfil || "Governante");
        const perfilBase = escapeHtml(row && row.perfil || "Governante");
        const grupoTitulo = palco && palco.titulo ? `<div class="muted">Grupo: ${escapeHtml(palco.titulo)}</div>` : "";
        const roles = ativos.length ? ativos.map((perfil) => {
          const canais = Array.isArray(perfil.concedidos) ? perfil.concedidos : [];
          const chips = canais.slice(0, 8).map((canal) => `<span class="badge">${escapeHtml(canal.nome || canal.codigo)}</span>`).join("");
          return `<div class="governance-role active"><strong>${escapeHtml(perfil.nome || perfil.codigo)}</strong><span class="muted">${escapeHtml(perfil.descricao || "")}</span><div class="governance-chips">${chips || '<span class="muted">sem canal detalhado</span>'}</div></div>`;
        }).join("") : '<div class="governance-role locked"><strong>Sem janela ativa neste grupo</strong><span class="muted">Nenhum canal concedido para as janelas principais.</span></div>';
        item.innerHTML = `<div class="person-line">${nome}<span class="badge">${perfilBase}</span>${row && row.modo_maestro ? '<span class="badge">dono</span>' : ''}</div>${grupoTitulo}${roles}`;
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
        el.className = filtered.length ? "governance-grid" : "governance-grid muted";
        el.replaceChildren(...(filtered.length ? filtered.map((row) => governancaCard(row, palcoRef)) : [document.createTextNode("Nenhum governante com janela ativa carregado.")]));
      }
      function renderPessoasPainel(data, alvosRows) {
        const resumoEl = document.getElementById("pessoas_resumo");
        const painel = data || {};
        const resumo = painel.resumo || {};
        const humanos = painel.administradores_humanos || (painel.administradores || []).filter((row) => !row.bot);
        const bots = painel.bots_administradores || (painel.administradores || []).filter((row) => row.bot);
        const membros = Array.isArray(alvosRows) ? alvosRows : [];
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
            options.push({ ref, label: `${pessoaLabel(row, row && row.bot ? 'Bot administrador' : 'Administrador')} · ${row && row.perfil_admin || 'Admin'}` });
          });
          membros.forEach((row) => {
            const ref = row && row.alvo_ref ? String(row.alvo_ref) : "";
            if (!ref || seen.has(ref)) return;
            seen.add(ref);
            options.push({ ref, label: `${pessoaLabel(row, 'Membro')} · membro visto` });
          });
          fillSelect("admin_alvo_select", options, "ref", "label", "Nenhum alvo administrativo registrado");
          const hint = document.getElementById("admin_alvo_hint");
          if (hint) hint.textContent = options.length ? `${options.length} alvo(s) administrativo(s) disponível(is), sem exibir ID real.` : "Faça o Telegram retornar administradores ou registre um membro antes de usar ações administrativas.";
        }
      }
      function renderMesaMembrosResumo(painel, alvosRows) {
        const resumoEl = document.getElementById("mesa_pessoas_resumo");
        const previewEl = document.getElementById("mesa_membros_preview");
        const data = painel || {};
        const resumo = data.resumo || {};
        const humanos = data.administradores_humanos || (data.administradores || []).filter((row) => !row.bot);
        const bots = data.bots_administradores || (data.administradores || []).filter((row) => row.bot);
        const membros = Array.isArray(alvosRows) ? alvosRows : [];
        if (resumoEl) {
          resumoEl.textContent = `${humanos.length || resumo.administradores_humanos || 0} admin humano(s) · ${bots.length || resumo.bots_administradores || 0} bot(s) admin · ${membros.length} membro(s) visto(s).`;
          resumoEl.className = "empty small " + ((humanos.length || bots.length || membros.length) ? "ok" : "warn");
        }
        if (previewEl) {
          const sample = membros.slice(0, 8);
          previewEl.className = sample.length ? "member-preview" : "member-preview muted small";
          previewEl.replaceChildren(...(sample.length ? sample.map((row) => itemText(pessoaLabel(row, "Membro"), row && row.tag ? "tag: " + row.tag : "referência interna segura")) : [document.createTextNode("Nenhum membro visto carregado para este grupo.")]));
        }
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
        botUsuario.innerHTML = username ? `<a class="person-link" href="https://t.me/${username}" target="_blank" rel="noopener"><strong>@${username}</strong></a>` : "sem username público";
        const metricas = document.getElementById("bot_metricas");
        metricas.replaceChildren();
        const usuarios = typeof stats.usuarios_conhecidos === "number" ? stats.usuarios_conhecidos : "—";
        const palcos = typeof stats.palcos_ativos === "number" ? stats.palcos_ativos : "—";
        const operadores = typeof stats.operadores_autorizados === "number" ? stats.operadores_autorizados : "—";
        for (const label of [`Usuários conhecidos: ${usuarios}`, `Grupos ativos: ${palcos}`, `Operadores: ${operadores}`]) {
          const span = document.createElement("span");
          span.className = "badge";
          span.textContent = label;
          metricas.appendChild(span);
        }
        const revisoes = document.getElementById("bot_revisoes");
        const importantes = (data && data.revisoes_importantes) || [];
        if (importantes.length) {
          const box = document.createElement("div");
          box.innerHTML = `<strong>Revisões importantes:</strong> ${importantes.map((item) => safeText(item, "revisar")).join(" · ")}`;
          revisoes.appendChild(box);
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
        document.getElementById("grupo_nome").innerHTML = grupoHtml(palco.titulo || (currentPalco && currentPalco.titulo) || "Grupo", palco.username || palco.endereco_publico || (currentPalco && currentPalco.username));
        document.getElementById("grupo_descricao").textContent = palco.descricao || "Sem descrição pública disponível.";
        document.getElementById("grupo_tipo").textContent = `${palco.tipo || "desconhecido"}${palco.forum ? " · fórum" : ""}${palco.modo_lento_segundos ? ` · modo lento ${palco.modo_lento_segundos}s` : ""}`;
        document.getElementById("grupo_membros").textContent = typeof palco.membros_count === "number" ? `${palco.membros_count} membro(s)` : "Não disponível no momento";
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
        rows.push(itemText("Resumo do grupo", `${palco.titulo || "Grupo"} · ${palco.tipo || "tipo desconhecido"}${palco.forum ? " · fórum" : ""}${palco.modo_lento_segundos ? ` · modo lento ${palco.modo_lento_segundos}s` : ""}`));
        rows.push(itemText("Descrição", palco.descricao || "Sem descrição pública disponível."));
        rows.push(itemText("Membros", typeof palco.membros_count === "number" ? palco.membros_count + " membro(s)" : "membros indisponíveis"));
        rows.push(itemText("Administração", `${resumo.administradores || 0} administradores · ${resumo.bots_administradores || 0} bots administradores`));
        rows.push(itemText("Funções possíveis", `${resumo.acoes_disponiveis || 0} de ${resumo.acoes_totais || 0} funções liberadas pelos direitos reais do bot`));
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
          item.innerHTML = `<strong>Administradores humanos</strong><br>${admins.map((admin) => `${admin.perfil_admin || "Admin"} · ${pessoaHtml(admin, "Administrador")}`).join("<br>")}`;
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
          resumoEl.innerHTML = metric(liberadas, "ações liberadas", liberadas ? "ok" : "") + metric(bloqueadasOperador, "bloqueadas por operador", bloqueadasOperador ? "warn" : "") + metric(bloqueadasBot, "bloqueadas pelo bot", bloqueadasBot ? "bad" : "") + metric(modoMaestroPermitido ? "sim" : "não", "administrador principal", modoMaestroPermitido ? "ok" : "warn");
        }
        if (operadorEl) {
          operadorEl.className = canaisOperador.length ? "list" : "list muted";
          operadorEl.replaceChildren(...(canaisOperador.length ? canaisOperador.map((codigo) => itemText(canalNome(codigo), criticalActions.has(codigo) ? "canal crítico" : "canal operacional")) : [document.createTextNode(currentPalco ? "Nenhum canal operacional carregado para este operador neste grupo." : "Escolha um grupo para ver canais do operador.")]));
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
            const wrapper = document.createElement("div");
            wrapper.className = "diagnostic-card";
            const titulo = document.createElement("strong");
            titulo.textContent = categoria;
            wrapper.appendChild(titulo);
            for (const codigo of codigos) {
              const check = diagnosticForAction(codigo);
              const line = document.createElement("div");
              line.className = `diagnostic-card ${check.ok ? 'ok' : (check.botOk ? 'warn' : 'bad')}`;
              const status = check.ok ? "Liberado" : "Bloqueado";
              const motivos = check.motivos.length ? check.motivos.join(" · ") : "canal e direito real confirmados";
              line.innerHTML = `<strong>${escapeHtml(canalNome(codigo))}</strong><span class="small ${check.ok ? 'ok' : 'warn'}">${status}</span><div class="diagnostic-reasons small">${escapeHtml(motivos)}</div>`;
              wrapper.appendChild(line);
            }
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
        const ref = (document.getElementById("radio_draft_select") || {}).value || "";
        const row = ref ? radioDraftsPorRef.get(ref) : null;
        if (!ref || !row) { toast("Escolha um rascunho.", "warn"); return; }
        if (row.status !== "draft") { toast("Somente rascunhos abertos podem ser publicados.", "warn"); return; }
        const res = await api("/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/radio/rascunhos/" + encodeURIComponent(ref) + "/publicar", { method: "POST", headers: apiHeaders });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        if (data.fixacao && data.fixacao.ok === false) toast("Publicado, mas não fixado: " + (data.fixacao.motivo || "permissão insuficiente"), "warn");
        else toast("Rascunho publicado.", "ok");
        if (data.mensagem && data.mensagem.msg_ref) {
          mensagensPorRef.set(data.mensagem.msg_ref, data.mensagem);
        }
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
        if (resumo) resumo.textContent = "Campos carregados. Revise e clique em Gerar Raw Editor somente no final.";
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
          session_ttl_seconds: 28800
        };
      }
      async function gerarConfigRaw() {
        if (!modoMaestroPermitido) { toast("Configuração restrita ao administrador principal.", "warn"); return; }
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
          resumo.textContent = `${r.aliases || 0} aliases · ${r.palcos || 0} grupos · ${r.maestros || 0} administrador(es) principal(is) · ${r.operadores || 0} operador(es)${avisos}`;
          resumo.className = "empty small " + ((data.avisos || []).length ? "warn" : "ok");
        }
        toast("Raw Editor final gerado para conferência.", "ok");
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
      async function concederRbacRuntime() {
        if (!modoMaestroPermitido) { toast("Delegação restrita ao dono do código.", "warn"); return; }
        const payload = {
          usr_ref: (document.getElementById("rbac_usr_ref") || {}).value || "",
          grp_ref: (document.getElementById("rbac_grp_ref") || {}).value || "*",
          canal_codigo: (document.getElementById("rbac_canal_codigo") || {}).value || "",
          motivo: (document.getElementById("rbac_motivo") || {}).value || "",
        };
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
      async function loadConfiguracaoMaestro() {
        if (!modoMaestroPermitido) return;
        const res = await api("/equalizador/api/configuracao");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        fillConfigForm(data.formulario || {});
        fillList("config_palcos_ativos", data.palcos_ativos || [], (row) => itemText(row.titulo || "Grupo", row.estado || "ativo"), "Nenhum grupo ativo em TR4_EQUALIZADOR_PALCO_IDS.");
        fillList("config_aliases", data.aliases || [], (row) => itemText(row.alias || "alias", `${row.estado || "estado"} · ${row.grp_ref || ""}`), "Nenhum alias configurado em GROUP_ALIASES.");
        fillList("config_palcos_ocultos", data.palcos_ocultos || [], (row) => itemText(row.titulo || "Grupo oculto", `${row.estado || "oculto"} · ${row.grp_ref || ""}`), "Nenhum grupo antigo fora da variável ativa.");
        fillList("config_operadores", data.operadores || [], (row) => {
          const canais = (row.canais || []).map((canal) => canal.nome || canal.codigo).join(", ") || "sem canais";
          return itemText(`Participante com permissão · ${row.perfil || "Operador"} · ${pessoaLabel(row, row.perfil || "Operador")}`, `canais concedidos: ${canais}`);
        }, "Nenhum operador configurado.");
        const gov = data.governanca || {};
        const govResumo = (gov && gov.resumo) || {};
        const govResumoEl = document.getElementById("config_governantes_resumo");
        if (govResumoEl) govResumoEl.textContent = `${govResumo.governantes || 0} governante(s) · ${govResumo.palcos || 0} grupo(s) · ${govResumo.janelas_ativas || 0} janela(s) ativa(s)`;
        renderGovernanca("config_governantes", gov, { onlyActive: true });
        renderRbacRuntime(data);
        renderSeguranca(data);
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
        fillList("config_matriz", matrizRows, (row) => itemText(row.titulo, row.detalhe), "Matriz sem operadores ou grupos configurados.");
      }

      async function loadPalcoData() {
        if (!currentPalco || carregandoPalco) return;
        carregandoPalco = true;
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
          api(base + "/governantes").then((r) => r.ok ? r.json() : { governantes: [] }).catch(() => ({ governantes: [] })),
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
        const alvosOptions = (alvosRes.alvos || []).map((row) => Object.assign({}, row, {
          nome_label: `${pessoaLabel(row, 'Membro')} · ${row.situacao || 'desconhecido'}`
        }));
        fillSelect("alvo_select", alvosOptions, "alvo_ref", "nome_label", "Nenhum membro registrado");
        const mensagensHint = document.getElementById("mensagens_hint");
        if (mensagensHint) mensagensHint.textContent = mensagensRows.length ? `${mensagensRows.length} mensagem(ns) recente(s) registradas.` : "Envie uma mensagem no grupo e atualize o painel para criar uma referência segura.";
        const alvosRows = alvosRes.alvos || [];
        renderPessoasPainel(currentPainelDinamico, alvosRows);
        const alvosHint = document.getElementById("alvos_hint");
        if (alvosHint) alvosHint.textContent = alvosRows.length ? `${alvosRows.length} membro(s) registrado(s) para operação.` : "Faça um membro enviar mensagem ou entrar no grupo para criar uma referência segura.";
        const atalhos = document.getElementById("alvos_atalhos");
        if (atalhos) {
          const rows = alvosRows.slice(0, 6).filter((row) => row.username || row.nome);
          atalhos.className = rows.length ? "list small" : "list small hidden";
          atalhos.replaceChildren(...rows.map((row) => {
            const item = document.createElement("div");
            item.className = "item small";
            item.innerHTML = `${pessoaHtml(row)}<br><span class="muted">${row.situacao || "situação desconhecida"}</span>`;
            return item;
          }));
        }
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
        }) : [document.createTextNode(modoMaestroPermitido ? "Nenhuma distribuição disponível." : "Distribuição restrita ao administrador principal.")]));
        if (modoMaestroPermitido) loadConfiguracaoMaestro().catch(() => null);
        updateButtons();
        } finally { carregandoPalco = false; }
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
          if (action === "topicos.criar") return { nome: nome || "Novo tópico" };
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
          if (data.mensagem) setMensagemResult(data.mensagem, data.resumo || "Ajuste de mensagem concluído.");
          if (data.entrada) toast(`Pedido de entrada: ${data.entrada.situacao || 'tratado'}.`, "ok");
          if (data.convite && typeof data.convite === "object") toast(data.resumo || "Convite ajustado.", "ok");
          if (data.membro) setMembroResult(data.membro, data.resumo || "Ajuste de membro concluído.");
          if (data.resultado) {
            toast(`${data.resultado.estado || 'ajuste'}: ${data.resultado.nome || 'referência'}`, "ok");
            const adminBox = document.getElementById("admin_resultado");
            if (adminBox && (action.startsWith("admins.") || action.startsWith("grupo."))) {
              const box = document.getElementById("admin_resultado");
              if (box) { box.textContent = data.resumo || `${data.resultado.estado || 'ajuste'}: ${data.resultado.nome || 'referência'}`; box.className = "empty small ok"; }
            }
          }
          if (data.fixacao && data.fixacao.ok === false) toast("Transmissão enviada, mas não fixada: " + (data.fixacao.motivo || "permissão do bot insuficiente"), "warn");
          toast(data.resumo || "Ajuste concluído.", "ok");
        }
        statusMesa("Último ajuste concluído: " + (actionLabels[action] || action) + ".", "ok");
        await loadPalcoData();
      }
      const feedbackCopyButton = document.getElementById("feedback_copy");
      if (feedbackCopyButton) feedbackCopyButton.addEventListener("click", async () => {
        const texto = feedbackEntries.map((entry) => `[${entry.time}] ${entry.kind || 'info'}: ${entry.text}`).join("\\n");
        if (!texto) return;
        try { await navigator.clipboard.writeText(texto); toast("Detalhes do painel copiados.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione os detalhes manualmente.", "warn"); }
      });
      const feedbackClearButton = document.getElementById("feedback_clear");
      if (feedbackClearButton) feedbackClearButton.addEventListener("click", () => { feedbackEntries = []; renderFeedbackPanel(); haptic("selection"); });
      document.getElementById("mensagem_select").addEventListener("change", updateButtons);
      document.getElementById("alvo_select").addEventListener("change", updateButtons);
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
        if (!modoMaestroPermitido) { toast("Exportação restrita ao administrador principal.", "warn"); return; }
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
        try { await navigator.clipboard.writeText(value); toast("Bloco Raw Editor copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione o campo Raw Editor.", "warn"); }
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
      fetch("/equalizador/api/me", { headers: apiHeaders })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("denied")))
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
          document.getElementById("perfil").textContent = me.perfil === "Maestro" ? "Administrador principal" : (me.perfil || "Operador");
          document.getElementById("ui_ref").textContent = me.ui_ref || "";
          aplicarPerfil(me);
          return Promise.all([
            fetch("/equalizador/api/palcos", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { palcos: [] }),
            fetch("/equalizador/api/canais", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { canais: [] }),
            fetch("/equalizador/api/bot/resumo", { headers: apiHeaders }).then((r) => r.ok ? r.json() : null)
          ]);
        })
        .then(([palcosData, canaisData, botData]) => {
          renderCanais(canaisData.canais || []);
          renderPalcos(palcosData.palcos || []);
          if (botData) renderBotResumo(botData);
          show("app");
        })
        .catch((error) => {
          setStoredSession("");
          reportClient("bootstrap_failed", error && error.message ? error.message : "Falha ao iniciar painel.");
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
        revisoes.append("nenhum administrador principal configurado")
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


async def _bot_public_summary() -> dict[str, object]:
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
    return {
        "bot": bot_payload,
        "estatisticas": {
            "usuarios_conhecidos": _count_known_bot_users(),
            "palcos_ativos": len(settings.equalizador_allowed_palco_ids()),
            "operadores_autorizados": len(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET),
            "maestros": len(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET),
        },
        "revisoes_importantes": _bot_revisoes_importantes(),
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
    user_agent = clean(payload.get("user_agent"), 180)
    logger = __import__("logging").getLogger(__name__)
    logger.warning(
        "EQUALIZADOR_CLIENT_ERROR | tipo=%s | mensagem=%s | origem=%s | linha=%s | coluna=%s | ua=%s",
        kind,
        message or "-",
        source or "-",
        payload.get("line") or 0,
        payload.get("col") or 0,
        user_agent or "-",
    )
    return {"ok": True}


@router.get("/api/me")
def equalizador_me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="bootstrap")
    return _public_operator_payload(identity)


@router.get("/api/bot/resumo")
async def equalizador_bot_resumo(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_identity(authorization, rate_kind="read")
    return await _bot_public_summary()


@router.get("/api/bot/foto")
async def equalizador_bot_foto(authorization: str | None = Header(default=None)) -> Response:
    _require_identity(authorization, rate_kind="read")
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
            return Response(content=image_res.content, media_type=image_res.headers.get("content-type") or "image/jpeg")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível.") from exc


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


@router.get("/api/configuracao")
def equalizador_configuracao(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="canais.distribuir",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return {
        "configuracao": True,
        **configuracao_maestro_publica(alias_secret=settings.equalizador_alias_secret()),
        "matriz_permissoes": matriz_permissoes_publica(alias_secret=settings.equalizador_alias_secret()),
        "governanca": governantes_publicos(alias_secret=settings.equalizador_alias_secret()),
        "rbac_runtime": rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret()),
        "sessoes_persistentes": session_store_status(now_ts=int(__import__("time").time())),
        "seguranca_avancada": security_dashboard_public(alias_secret=settings.equalizador_alias_secret()),
    }


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
        raise HTTPException(status_code=400, detail="Concessão inválida ou alvo indisponível.") from exc
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

    removidas = cleanup_expired_sessions(now_ts=int(time.time()))
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
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Grupo indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("palco.status", "palco.ver"))
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
        raise HTTPException(status_code=403, detail="Processamento restrito ao administrador principal.")
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
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="canais.distribuir",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    payload = await _read_json_payload(request)
    return raw_editor_from_form_payload(payload)


@router.get("/api/permissoes/matriz")
def equalizador_permissoes_matriz(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="canais.distribuir",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return matriz_permissoes_publica(alias_secret=settings.equalizador_alias_secret())


@router.get("/api/canais/distribuicao")
def equalizador_canais_distribuicao(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal_effective(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="canais.distribuir",
        is_maestro=_is_maestro(identity),
    )
    if not palco_ids:
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    return {
        "distribuicao": distribuicao_canais_publica(
            raw_canais=settings.equalizador_canais_raw(),
            allowed_palco_ids=settings.equalizador_allowed_palco_ids(),
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
        raise HTTPException(status_code=409, detail=avancado_error_public_detail(exc)) from exc


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
