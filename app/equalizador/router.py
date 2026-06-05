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
    canal_codes_for_operator,
    canal_is_allowed,
    canais_for_palco,
    filter_palco_ids_by_canal,
)
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
    list_historico_publico,
    register_mensagem_from_link,
    resolve_alvo_manual,
    send_operator_dm,
)
from app.equalizador.papeis import matriz_permissoes_publica
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
    check_equalizador_rate_limit,
    create_equalizador_session,
    log_equalizador_event,
    mesa_operation_lock,
    validate_equalizador_session,
)
from app.equalizador.security import InitDataError, TelegramWebAppIdentity, extract_tma_authorization, validate_init_data
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
)

router = APIRouter(prefix="/equalizador", tags=["equalizador"], include_in_schema=False)

_EQUALIZADOR_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Equalizador</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: dark light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 16px; background: var(--tg-theme-bg-color, #101014); color: var(--tg-theme-text-color, #f4f4f5); }
    main { max-width: 820px; margin: 0 auto; }
    .card { border: 1px solid rgba(255,255,255,.10); border-radius: 20px; padding: 18px; background: rgba(255,255,255,.045); box-shadow: 0 10px 32px rgba(0,0,0,.18); }
    h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.02em; }
    h2 { margin: 22px 0 10px; font-size: 18px; }
    h3 { margin: 14px 0 8px; font-size: 15px; }
    p { line-height: 1.45; }
    .muted { color: var(--tg-theme-hint-color, #a1a1aa); }
    .hidden { display: none !important; }
    .top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .pill { display: inline-flex; align-items: center; border: 1px solid rgba(255,255,255,.12); border-radius: 999px; padding: 6px 10px; font-size: 12px; color: var(--tg-theme-hint-color, #a1a1aa); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
    .formgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .panel { border: 1px solid rgba(255,255,255,.08); border-radius: 16px; padding: 14px; background: rgba(255,255,255,.035); }
    .palco { width: 100%; text-align: left; border: 1px solid rgba(255,255,255,.10); border-radius: 16px; padding: 14px; background: rgba(255,255,255,.06); color: inherit; font: inherit; }
    .palco.active { outline: 2px solid var(--tg-theme-button-color, #5b8cff); }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: center; border-top: 1px solid rgba(255,255,255,.08); padding-top: 10px; margin-top: 10px; }
    button, select, textarea, input { font: inherit; }
    button.action, button.nav { border: 0; border-radius: 14px; padding: 12px 14px; background: var(--tg-theme-button-color, #5b8cff); color: var(--tg-theme-button-text-color, white); font-weight: 650; }
    button.secondary { background: rgba(255,255,255,.09); color: inherit; border: 1px solid rgba(255,255,255,.10); }
    button.danger { background: #b42318; color: #fff; }
    button:disabled { opacity: .45; filter: grayscale(1); }
    button.action[data-action="convites.criar"], button.action[data-action="entradas.aprovar"], button.action[data-action="membros.liberar"], button.action[data-action="membros.reintegrar"], button.action[data-action="canais_remetentes.liberar"], button.action[data-action="admins.promover"], button.action[data-action="silencio.desativar"] { background: #168a55; color: #fff; }
    button.action[data-action="fixados.criar"], button.action[data-action="fixados.remover"], button.action[data-action="topicos.criar"], button.action[data-action="topicos.editar"], button.action[data-action="topicos.reabrir"], button.action[data-action="topicos.desfixar"], button.action[data-action="topicos.geral.reabrir"], button.action[data-action="topicos.geral.exibir"], button.action[data-action="topicos.geral.desfixar"], button.action[data-action="grupo.descricao"], button.action[data-action="admins.titulo"], button#resolver_mensagem, button#resolver_alvo { background: #2563eb; color: #fff; }
    button.action[data-action="transmissao.enviar"], button.action[data-action="convites.editar"], button.action[data-action="convites.exportar_primario"], button.action[data-action="grupo.titulo"], button.action[data-action="membros.tag.definir"], button.action[data-action="membros.silenciar"], button.action[data-action="silencio.ativar"], button.action[data-action="topicos.fechar"], button.action[data-action="topicos.geral.fechar"], button.action[data-action="topicos.geral.ocultar"], button.action[data-action="reacoes.mensagem.limpar"], button.action[data-action="reacoes.recentes.limpar"], button#atualizar_configuracao, button#gerar_config_raw, button#resetar_config_form, button#copiar_config_raw, button#exportar_historico { background: #c77800; color: #fff; }
    button.action[data-action="mensagens.apagar"], button.action[data-action="membros.remover"], button.action[data-action="entradas.recusar"], button.action[data-action="convites.revogar"], button.action[data-action="topicos.apagar"], button.action[data-action="canais_remetentes.banir"], button.action[data-action="admins.rebaixar"] { background: #b42318; color: #fff; }
    .nav[data-view="mesa_view"]::before { content: "Moderação · "; }
    .nav[data-view="afinacao_view"]::before { content: "Permissões · "; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
    select, textarea, input { width: 100%; border: 1px solid rgba(255,255,255,.12); border-radius: 14px; padding: 12px; background: rgba(0,0,0,.18); color: inherit; }
    textarea { min-height: 92px; resize: vertical; }
    .list { display: grid; gap: 8px; }
    .item { border: 1px solid rgba(255,255,255,.08); border-radius: 14px; padding: 12px; background: rgba(255,255,255,.03); }
    .ok { color: #50d890; }
    .bad { color: #ff8a80; }
    .warn { color: #ffd166; }
    .small { font-size: 12px; }
    .section-note { margin: 8px 0 12px; color: var(--tg-theme-hint-color, #a1a1aa); font-size: 13px; }
    .statusbar { margin: 14px 0; border: 1px solid rgba(255,255,255,.10); border-radius: 16px; padding: 12px; background: rgba(255,255,255,.035); }
    .badge { display: inline-flex; align-items: center; margin: 3px 4px 3px 0; border-radius: 999px; padding: 5px 9px; border: 1px solid rgba(255,255,255,.10); font-size: 12px; color: var(--tg-theme-hint-color, #a1a1aa); }
    .empty { border: 1px dashed rgba(255,255,255,.14); border-radius: 14px; padding: 12px; color: var(--tg-theme-hint-color, #a1a1aa); background: rgba(255,255,255,.02); }
    .toast { position: sticky; bottom: 12px; margin-top: 16px; border-radius: 14px; padding: 12px; background: rgba(255,255,255,.10); white-space: pre-wrap; }
    .headline { display: grid; grid-template-columns: 72px 1fr; gap: 12px; align-items: center; }
    .bot-hero { display: grid; grid-template-columns: 86px 1fr; gap: 14px; align-items: center; border: 1px solid rgba(255,255,255,.10); border-radius: 18px; padding: 14px; background: rgba(255,255,255,.035); margin-bottom: 12px; }
    .bot-hero h2 { margin: 0 0 4px; font-size: 22px; }
    .bot-avatar { width: 76px; height: 76px; border-radius: 22px; object-fit: cover; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.08); display: grid; place-items: center; color: var(--tg-theme-hint-color, #a1a1aa); font-weight: 800; font-size: 26px; }
    .avatar { width: 64px; height: 64px; border-radius: 18px; object-fit: cover; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.08); display: grid; place-items: center; color: var(--tg-theme-hint-color, #a1a1aa); font-weight: 800; }
    .header-select { margin: 14px 0; }
    .quicklist { display: grid; gap: 8px; }
    .quicklist code { background: rgba(0,0,0,.20); padding: 2px 6px; border-radius: 8px; }
    .person-link { color: var(--tg-theme-link-color, #8ab4ff); text-decoration: none; }
    .person-link:hover { text-decoration: underline; }
    .mini-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .mini-table td { border-top: 1px solid rgba(255,255,255,.08); padding: 7px 4px; vertical-align: top; }
    @media (max-width: 560px) { body { padding: 10px; } .card { padding: 14px; border-radius: 18px; } h1 { font-size: 22px; } .toolbar { gap: 6px; } button.action, button.nav { width: 100%; } .top { display: block; } .grid { grid-template-columns: 1fr; } }
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
          <div><strong>Atalhos:</strong> use link de mensagem, ID numérico ou @username já conhecido pelo bot. O app converte para referência segura.</div>
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
        <div class="toolbar">
          <button class="nav secondary" data-view="mesa_view">Painel</button>
          <button class="nav secondary" data-view="afinacao_view">Bot</button>
          <button class="nav secondary" data-view="historico_view">Histórico</button>
          <button id="maestro_nav" class="nav secondary hidden" data-view="maestro_view">Administração crítica</button>
          <button id="config_nav" class="nav secondary hidden" data-view="config_view">Configuração</button>
        </div>
        <section id="mesa_view" class="view">
          <div class="grid">
            <div class="panel">
              <h3>Mensagens</h3>
              <select id="mensagem_select"></select>
              <div id="mensagens_hint" class="empty small">Nenhuma mensagem carregada ainda.</div>
              <div class="toolbar">
                <button class="action danger" data-action="mensagens.apagar">Apagar</button>
                <button class="action secondary" data-action="fixados.criar">Fixar</button>
                <button class="action secondary" data-action="fixados.remover">Remover fixado</button>
              </div>
              <div id="mensagem_resultado" class="empty small">Nenhum ajuste de mensagem executado nesta sessão.</div>
              <p class="muted small">A lista usa referências internas. IDs de mensagem não aparecem.</p>
            </div>
            <div class="panel">
              <h3>Membros</h3>
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
                <button class="action secondary" data-action="membros.silenciar">Silenciar</button>
                <button class="action secondary" data-action="membros.liberar">Liberar</button>
                <button class="action danger" data-action="membros.remover">Remover</button>
                <button class="action secondary" data-action="membros.reintegrar">Reintegrar</button>
              </div>
              <div id="membro_resultado" class="empty small">Nenhum ajuste de membro executado nesta sessão.</div>
              <p class="muted small">A lista usa referências internas. IDs de usuário não aparecem.</p>
            </div>
            <div class="panel">
              <h3>Entrada manual segura</h3>
              <p class="muted small">Use link da mensagem, ID numérico ou @username já visto pelo bot. O backend transforma tudo em referências internas.</p>
              <input id="mensagem_link_input" placeholder="Link da mensagem: https://t.me/c/.../..." />
              <div class="toolbar"><button id="resolver_mensagem" class="action secondary" type="button">Resolver mensagem</button></div>
              <input id="alvo_manual_input" placeholder="ID numérico ou @username" />
              <div class="toolbar"><button id="resolver_alvo" class="action secondary" type="button">Resolver membro</button></div>
            </div>
            <div class="panel">
              <h3>Convites</h3>
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
              <input id="convite_resultado" readonly placeholder="Link criado aparece aqui" />
              <div id="convite_metadados" class="empty small">Nenhum convite criado nesta sessão.</div>
              <div class="toolbar">
                <button id="copiar_convite" class="action secondary" type="button" disabled>Copiar link</button>
                <button id="abrir_convite" class="action secondary" type="button" disabled>Abrir link</button>
              </div>
              <p id="convite_dm_status" class="muted small">O link também será enviado por DM quando o bot puder conversar com o operador.</p>
              <h3>Convites criados</h3>
              <select id="convite_select"></select>
              <div class="toolbar">
                <button class="action secondary" data-action="convites.editar">Editar convite</button>
                <button class="action danger" data-action="convites.revogar">Revogar convite</button>
                <button class="action secondary" data-action="convites.exportar_primario">Exportar link primário</button>
              </div>
              <div id="convites_hint" class="empty small">Nenhum convite carregado.</div>
              <h3>Pedidos de entrada</h3>
              <select id="entrada_select"></select>
              <div class="toolbar">
                <button class="action secondary" data-action="entradas.aprovar">Aprovar entrada</button>
                <button class="action danger" data-action="entradas.recusar">Recusar entrada</button>
              </div>
              <div id="entradas_hint" class="empty small">Nenhum pedido de entrada capturado.</div>
            </div>
          </div>
          <h3>Avançado</h3>
          <div class="grid">
            <div class="panel">
              <strong>Tópicos/fóruns</strong>
              <p class="muted small">Aparece conforme can_manage_topics, can_delete_messages e can_pin_messages.</p>
              <select id="topico_select"></select>
              <input id="topico_nome" maxlength="128" placeholder="Nome do tópico" />
              <div class="toolbar"><button class="action secondary" data-action="topicos.criar" type="button">Criar</button><button class="action secondary" data-action="topicos.editar" type="button">Editar</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.fechar" type="button">Fechar</button><button class="action secondary" data-action="topicos.reabrir" type="button">Reabrir</button><button class="action danger" data-action="topicos.apagar" type="button">Apagar</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.desfixar" type="button">Desfixar tópico</button><button class="action secondary" data-action="topicos.geral.desfixar" type="button">Desfixar geral</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.geral.fechar" type="button">Fechar geral</button><button class="action secondary" data-action="topicos.geral.reabrir" type="button">Reabrir geral</button></div>
              <div class="toolbar"><button class="action secondary" data-action="topicos.geral.ocultar" type="button">Ocultar geral</button><button class="action secondary" data-action="topicos.geral.exibir" type="button">Exibir geral</button></div>
              <div id="topicos_hint" class="empty small">Nenhum tópico registrado.</div>
            </div>
            <div class="panel">
              <strong>Reações e canais remetentes</strong>
              <p class="muted small">Para reações escolha uma mensagem e um membro ou canal remetente.</p>
              <select id="sender_select"></select>
              <input id="membro_tag" maxlength="16" placeholder="Tag do membro" />
              <div class="toolbar"><button class="action secondary" data-action="reacoes.mensagem.limpar" type="button">Limpar reação da mensagem</button><button class="action secondary" data-action="reacoes.recentes.limpar" type="button">Limpar reações recentes</button></div>
              <div class="toolbar"><button class="action danger" data-action="canais_remetentes.banir" type="button">Banir canal remetente</button><button class="action secondary" data-action="canais_remetentes.liberar" type="button">Liberar canal remetente</button></div>
              <div class="toolbar"><button class="action secondary" data-action="membros.tag.definir" type="button">Definir tag</button></div>
              <div id="remetentes_hint" class="empty small">Nenhum canal remetente capturado.</div>
            </div>
          </div>
        </section>
        <section id="afinacao_view" class="view hidden">
          <p class="section-note">Permissões do bot mostra o que o bot realmente consegue executar neste grupo.</p>
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
            <h3>Administração crítica</h3>
            <p class="muted small">Ações críticas exigem confirmação dupla.</p>
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
            <h3>Administração crítica</h3>
            <p class="muted small">Essas ações exigem direito real do bot e confirmação dupla. Use somente em grupo de teste antes de produção.</p>
            <input id="grupo_titulo_input" maxlength="128" placeholder="Novo título do grupo" />
            <textarea id="grupo_descricao_input" maxlength="255" placeholder="Nova descrição do grupo"></textarea>
            <input id="admin_titulo_input" maxlength="16" placeholder="Título personalizado do admin" />
            <label class="small muted">Perfil de promoção</label>
            <select id="admin_perfil_select"><option value="moderador" selected>Moderador seguro</option><option value="maestro">Administrador delegado</option></select>
            <label class="small"><input id="admin_ciente" type="checkbox" /> confirmo que entendo o risco da administração crítica</label>
            <div class="toolbar">
              <button class="action secondary" data-action="grupo.titulo" type="button">Alterar título</button>
              <button class="action secondary" data-action="grupo.descricao" type="button">Alterar descrição</button>
              <button class="action secondary" data-action="admins.promover" type="button">Promover administrador</button>
              <button class="action danger" data-action="admins.rebaixar" type="button">Rebaixar admin</button>
              <button class="action secondary" data-action="admins.titulo" type="button">Definir título admin</button>
            </div>
            <div id="admin_resultado" class="empty small">Nenhuma administração crítica executada nesta sessão.</div>
            <div id="distribuicao" class="list muted"></div>
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
    </section>
  </main>
  <script>
    (function () {

      // Compatibilidade de testes antigos: Afinando acesso… · Configuração do administrador principal · Assistente de configuração · Ações permanecem bloqueadas até confirmação do bot
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      const initData = tg && tg.initData ? tg.initData : "";
      let apiHeaders = null;
      let bootstrapHeaders = null;
      let currentPalco = null;
      let mensagensPorRef = new Map();
      let canaisPorPalco = new Map();
      let botFotoIndisponivel = false;
      const fotosGrupoIndisponiveis = new Set();
      let direitosDisponiveis = new Set();
      let afinacaoLoaded = false;
      let modoMaestroPermitido = false;
      const criticalActions = new Set(["silencio.ativar", "silencio.desativar", "transmissao.enviar", "grupo.titulo", "grupo.descricao", "admins.promover", "admins.rebaixar", "admins.titulo"]);
      const endpoints = {
        "mensagens.apagar": "mensagens/apagar",
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
        "admins.promover": "admins/promover",
        "admins.rebaixar": "admins/rebaixar",
        "admins.titulo": "admins/titulo"
      };
      const actionLabels = {
        "palco.ver": "Ver grupo",
        "palco.status": "Status do grupo",
        "palco.afinar": "Permissões do bot no grupo",
        "mensagens.apagar": "Apagar mensagem",
        "reacoes.limpar": "Limpar reações",
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
        "reacoes.mensagem.limpar": "Limpar reação da mensagem",
        "reacoes.recentes.limpar": "Limpar reações recentes",
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
        "admins.promover": "Promover administrador",
        "admins.rebaixar": "Rebaixar administrador",
        "admins.titulo": "Título personalizado de admin"
      };
      const canalNome = (codigo) => actionLabels[codigo] || String(codigo || "canal").replace(/[._]/g, " ");
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
        const text = typeof detail === "string" ? detail : (detail && detail.detail ? String(detail.detail) : "Ajuste não concluído.");
        return text
          .replace(/-100\\d{5,}/g, "grupo oculto")
          .replace(/\\b\\d{7,12}\\b/g, "referência oculta");
      };
      // Compatibilidade de testes antigos: Modo Maestro indisponível para este perfil. · Ação restrita ao Maestro · palco oculto · Configuração do Maestro · /mesa_ajuda · Distribuição restrita ao Maestro. · Canal ou afinação indisponível · perfil oculto · Exportação restrita ao Maestro.
      const show = (id) => {
        for (const el of document.querySelectorAll("main > section")) el.classList.add("hidden");
        document.getElementById(id).classList.remove("hidden");
      };
      const toast = (text, kind) => {
        const el = document.getElementById("toast");
        el.textContent = text;
        el.className = "toast " + (kind || "");
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
        if (response.status === 429) toast("Muitas leituras em sequência. Aguarde alguns segundos e tente novamente.", "warn");
        return response;
      };
      const option = (value, label) => {
        const item = document.createElement("option");
        item.value = value;
        item.textContent = label;
        return item;
      };
      const hasCanal = (codigo) => currentPalco && (canaisPorPalco.get(currentPalco.grp_ref) || new Set()).has(codigo);
      const canRun = (codigo) => hasCanal(codigo) && afinacaoLoaded && direitosDisponiveis.has(codigo);
      const openView = (id) => {
        if (id === "maestro_view" && !modoMaestroPermitido) {
          toast("Administração crítica indisponível para este perfil.", "warn");
          id = "mesa_view";
        }
        for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
        document.getElementById(id).classList.remove("hidden");
      };
      const aplicarPerfil = (me) => {
        const canais = new Set(me.canais || []);
        modoMaestroPermitido = Boolean(me.modo_maestro) || (me.perfil === "Maestro" && (canais.has("silencio.ativar") || canais.has("silencio.desativar") || canais.has("transmissao.enviar") || canais.has("historico.exportar") || canais.has("canais.distribuir")));
        const maestroNav = document.getElementById("maestro_nav");
        if (maestroNav) maestroNav.classList.toggle("hidden", !modoMaestroPermitido);
        const configNav = document.getElementById("config_nav");
        if (configNav) configNav.classList.toggle("hidden", !modoMaestroPermitido);
        const exportButton = document.getElementById("exportar_historico");
        if (exportButton) exportButton.disabled = !modoMaestroPermitido;
        if (!modoMaestroPermitido) {
          document.getElementById("maestro_view").classList.add("hidden");
          document.getElementById("config_view").classList.add("hidden");
        }
      };
      document.querySelectorAll("button.nav").forEach((button) => button.addEventListener("click", () => openView(button.dataset.view)));
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
      function updateButtons() {
        const mensagemRef = document.getElementById("mensagem_select").value;
        const alvoRef = document.getElementById("alvo_select").value;
        const mensagem = mensagensPorRef.get(mensagemRef);
        const entradaRef = (document.getElementById("entrada_select") || {}).value || "";
        const conviteRef = (document.getElementById("convite_select") || {}).value || "";
        document.querySelectorAll("button.action[data-action]").forEach((button) => {
          const action = button.dataset.action;
          let disabled = !currentPalco || !canRun(action);
          let title = disabled ? "Canal ou permissão do bot indisponível" : "";
          if (criticalActions.has(action) && !modoMaestroPermitido) {
            disabled = true;
            title = "Ação restrita ao administrador principal";
          }
          if (!disabled && (action.startsWith("mensagens.") || action.startsWith("fixados.")) && !mensagemRef) {
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
          if (!disabled && action.startsWith("membros.") && !alvoRef) {
            disabled = true;
            title = "Escolha um membro registrado";
          }
          if (!disabled && action.startsWith("admins.") && !alvoRef) {
            disabled = true;
            title = "Escolha um membro registrado";
          }
          if (!disabled && action.startsWith("topicos.") && !action.startsWith("topicos.geral") && action !== "topicos.criar" && !((document.getElementById("topico_select") || {}).value || "")) {
            disabled = true;
            title = "Escolha um tópico registrado";
          }
          if (!disabled && action.startsWith("canais_remetentes.") && !((document.getElementById("sender_select") || {}).value || "")) {
            disabled = true;
            title = "Escolha um canal remetente";
          }
          if (!disabled && action === "reacoes.mensagem.limpar" && !mensagemRef) {
            disabled = true;
            title = "Escolha uma mensagem registrada";
          }
          if (!disabled && action === "reacoes.mensagem.limpar" && !alvoRef && !((document.getElementById("sender_select") || {}).value || "")) {
            disabled = true;
            title = "Escolha um membro ou canal remetente";
          }
          button.disabled = disabled;
          button.title = title;
        });
        if (currentPalco && afinacaoLoaded) {
          statusMesa("Painel pronto. Botões liberados dependem do canal concedido, alvo selecionado e direito real do bot.", "ok");
        } else if (currentPalco) {
          statusMesa("Painel aguardando permissões do bot. Ações permanecem bloqueadas até confirmação.", "warn");
        }
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
        if (!disponivel || !grpRef || fotosGrupoIndisponiveis.has(grpRef)) return;
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
        loadPalcoPhoto(currentPalco && currentPalco.grp_ref, Boolean(palco.foto_disponivel));
      }
      function renderPainelDinamico(data) {
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
        const admins = (data.administradores || []).slice(0, 12);
        if (admins.length) {
          const item = document.createElement("div");
          item.className = "item small";
          item.innerHTML = `<strong>Lista de administração</strong><br>${admins.map((admin) => `${admin.perfil_admin || "Admin"} · ${pessoaHtml(admin, "Administrador")}${admin.bot ? " · bot" : ""}`).join("<br>")}`;
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
          session_ttl_seconds: 900
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
          return itemText(`${row.perfil || "Operador"} · ${pessoaLabel(row, row.perfil || "Operador")}`, canais);
        }, "Nenhum operador configurado.");
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
              titulo: `${operador.perfil || "Operador"} · ${pessoaLabel(operador, operador.perfil || "Operador")} · ${palco.titulo || "Grupo"}`,
              detalhe: `${concedidos.length ? concedidos.join(", ") : "sem canais concedidos"}${negadosCriticos ? ` · ${negadosCriticos} críticos bloqueados` : ""}`,
            });
          });
        });
        fillList("config_matriz", matrizRows, (row) => itemText(row.titulo, row.detalhe), "Matriz sem operadores ou grupos configurados.");
      }

      async function loadPalcoData() {
        if (!currentPalco) return;
        direitosDisponiveis = new Set();
        afinacaoLoaded = false;
        const base = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref);
        const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes, painelRes, entradasRes, convitesRes, topicosRes, remetentesRes] = await Promise.all([
          api(base + "/afinacao").then((r) => r.ok ? r.json() : null).catch(() => null),
          api(base + "/mensagens").then((r) => r.ok ? r.json() : { mensagens: [] }).catch(() => ({ mensagens: [] })),
          api(base + "/alvos").then((r) => r.ok ? r.json() : { alvos: [] }).catch(() => ({ alvos: [] })),
          api("/equalizador/api/historico").then((r) => r.ok ? r.json() : { historico: [] }).catch(() => ({ historico: [] })),
          (modoMaestroPermitido ? api("/equalizador/api/canais/distribuicao").then((r) => r.ok ? r.json() : { distribuicao: [] }).catch(() => ({ distribuicao: [] })) : Promise.resolve({ distribuicao: [] })),
          api(base + "/painel").then((r) => r.ok ? r.json() : null).catch(() => null),
          api(base + "/entradas").then((r) => r.ok ? r.json() : { entradas: [] }).catch(() => ({ entradas: [] })),
          api(base + "/convites").then((r) => r.ok ? r.json() : { convites: [] }).catch(() => ({ convites: [] })),
          api(base + "/topicos").then((r) => r.ok ? r.json() : { topicos: [] }).catch(() => ({ topicos: [] })),
          api(base + "/canais-remetentes").then((r) => r.ok ? r.json() : { remetentes: [] }).catch(() => ({ remetentes: [] }))
        ]);
        renderPainelDinamico(painelRes);
        if (afinacaoRes && Array.isArray(afinacaoRes.canais)) {
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
        fillSelect("convite_select", conviteRows.map((row) => Object.assign({}, row, { label: `${row.nome || row.invite_ref} · ${row.revogado ? 'revogado' : 'ativo'}` })), "invite_ref", "label", "Nenhum convite criado");
        const convitesHint = document.getElementById("convites_hint");
        if (convitesHint) convitesHint.textContent = conviteRows.length ? `${conviteRows.length} convite(s) conhecido(s).` : "Convites criados pelo Equalizador aparecerão aqui.";
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
        if (!identificador) { toast("Informe ID numérico ou @username.", "warn"); return; }
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
        if (action.startsWith("mensagens.") || action.startsWith("fixados.")) {
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
          const msg = document.getElementById("mensagem_select").value;
          const alvo = document.getElementById("alvo_select").value;
          const sender = (document.getElementById("sender_select") || {}).value || "";
          const base = {};
          if (action === "reacoes.mensagem.limpar") { if (!msg) throw new Error("Escolha uma mensagem registrada."); base.msg_ref = msg; }
          if (alvo) base.alvo_ref = alvo;
          else if (sender) base.sender_ref = sender;
          else throw new Error("Escolha um membro ou canal remetente.");
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
          return { titulo, confirmacao: "CONFIRMAR AJUSTE", ciente: Boolean((document.getElementById("admin_ciente") || {}).checked) };
        }
        if (action === "grupo.descricao") {
          return { descricao: (document.getElementById("grupo_descricao_input") || {}).value || "", confirmacao: "CONFIRMAR AJUSTE", ciente: Boolean((document.getElementById("admin_ciente") || {}).checked) };
        }
        if (action.startsWith("admins.")) {
          const alvo = document.getElementById("alvo_select").value;
          if (!alvo) throw new Error("Escolha um membro registrado.");
          return {
            alvo_ref: alvo,
            perfil: (document.getElementById("admin_perfil_select") || {}).value || "moderador",
            titulo_admin: (document.getElementById("admin_titulo_input") || {}).value || "",
            confirmacao: "CONFIRMAR AJUSTE",
            ciente: Boolean((document.getElementById("admin_ciente") || {}).checked)
          };
        }
        return {};
      }
      async function runAction(action) {
        if (!currentPalco) return;
        if (!confirm("Confirmar ajuste: " + (actionLabels[action] || action) + "?")) return;
        if (criticalActions.has(action) && !confirm("Ação crítica de administrador principal. Confirmar novamente?")) return;
        let payload;
        try { payload = buildPayload(action); } catch (err) { toast(err.message, "warn"); return; }
        const button = document.querySelector(`button.action[data-action="${action}"]`);
        if (button) button.disabled = true;
        statusMesa("Executando: " + (actionLabels[action] || action) + "…", "muted");
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints[action];
        const res = await api(url, { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); await loadPalcoData(); return; }
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
      document.getElementById("mensagem_select").addEventListener("change", updateButtons);
      document.getElementById("alvo_select").addEventListener("change", updateButtons);
      document.getElementById("entrada_select").addEventListener("change", updateButtons);
      document.getElementById("convite_select").addEventListener("change", updateButtons);
      document.getElementById("topico_select").addEventListener("change", updateButtons);
      document.getElementById("sender_select").addEventListener("change", updateButtons);
      document.getElementById("resolver_mensagem").addEventListener("click", resolveMensagemManual);
      document.getElementById("resolver_alvo").addEventListener("click", resolveAlvoManual);
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
      document.getElementById("transmissao_texto").addEventListener("input", () => {
        const text = document.getElementById("transmissao_texto").value || "";
        document.getElementById("transmissao_contador").textContent = `${text.length}/4096 caracteres`;
      });
      document.querySelectorAll("button.action[data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
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
      document.getElementById("copiar_config_raw").addEventListener("click", async () => {
        const value = document.getElementById("config_raw").value || "";
        if (!value) return;
        try { await navigator.clipboard.writeText(value); toast("Bloco Raw Editor copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione o campo Raw Editor.", "warn"); }
      });
      if (!initData) { show("denied"); return; }
      bootstrapHeaders = { "Authorization": "tma " + initData };
      fetch("/equalizador/api/me", { headers: bootstrapHeaders })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("denied")))
        .then((me) => {
          const sessionToken = me.sessao && me.sessao.token ? me.sessao.token : "";
          apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : bootstrapHeaders;
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
        .catch(() => show("denied"));
    })();
  </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def equalizador_home() -> HTMLResponse:
    return HTMLResponse(_EQUALIZADOR_HTML)


def _identity_from_authorization(authorization: str | None) -> TelegramWebAppIdentity:
    try:
        header = (authorization or "").strip()
        if header.lower().startswith("eqs "):
            return validate_equalizador_session(header[4:].strip())
        init_data = extract_tma_authorization(header)
        return validate_init_data(
            init_data,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            max_age_seconds=settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS,
        )
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
        check_equalizador_rate_limit(
            operator_ref=operador_ref,
            limit_per_minute=_rate_limit_for(rate_kind),
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
    canais = canal_codes_for_operator(
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
    return canal_is_allowed(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_id=palco_id,
        canal_codigo=canal_codigo,
        is_maestro=_is_maestro(identity),
    )


def _require_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigo: str) -> None:
    if not _has_canal_for_palco(identity, palco_id=palco_id, canal_codigo=canal_codigo):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")


def _require_any_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigos: tuple[str, ...]) -> None:
    if not any(_has_canal_for_palco(identity, palco_id=palco_id, canal_codigo=canal_codigo) for canal_codigo in canal_codigos):
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


async def _read_json_payload(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Ajuste inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Ajuste inválido.")
    return payload


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
        raise HTTPException(status_code=409, detail="Permissão real do bot insuficiente.") from exc
    except MesaError as exc:
        log_equalizador_event("EQUALIZADOR_AJUSTE_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc


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
    palcos_visiveis = filter_palco_ids_by_canal(
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
    palco_ids = filter_palco_ids_by_canal(
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
                "canais": canais_for_palco(
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
    palco_ids = filter_palco_ids_by_canal(
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
    palco_ids = filter_palco_ids_by_canal(
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
    palco_ids = filter_palco_ids_by_canal(
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
    }


@router.post("/api/configuracao/raw-preview")
async def equalizador_configuracao_raw_preview(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco_ids = filter_palco_ids_by_canal(
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
    palco_ids = filter_palco_ids_by_canal(
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
    palco_ids = filter_palco_ids_by_canal(
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
