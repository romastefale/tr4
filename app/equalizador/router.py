from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings
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
from app.equalizador.configuracao import configuracao_maestro_publica

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
    .panel { border: 1px solid rgba(255,255,255,.08); border-radius: 16px; padding: 14px; background: rgba(255,255,255,.035); }
    .palco { width: 100%; text-align: left; border: 1px solid rgba(255,255,255,.10); border-radius: 16px; padding: 14px; background: rgba(255,255,255,.06); color: inherit; font: inherit; }
    .palco.active { outline: 2px solid var(--tg-theme-button-color, #5b8cff); }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: center; border-top: 1px solid rgba(255,255,255,.08); padding-top: 10px; margin-top: 10px; }
    button, select, textarea, input { font: inherit; }
    button.action, button.nav { border: 0; border-radius: 14px; padding: 12px 14px; background: var(--tg-theme-button-color, #5b8cff); color: var(--tg-theme-button-text-color, white); font-weight: 650; }
    button.secondary { background: rgba(255,255,255,.09); color: inherit; border: 1px solid rgba(255,255,255,.10); }
    button.danger { background: #b42318; color: #fff; }
    button:disabled { opacity: .45; filter: grayscale(1); }
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
    @media (max-width: 560px) { body { padding: 10px; } .card { padding: 14px; border-radius: 18px; } h1 { font-size: 22px; } .toolbar { gap: 6px; } button.action, button.nav { width: 100%; } .top { display: block; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <section id="loading" class="card">
      <h1>Equalizador</h1>
      <p class="muted">Afinando acesso…</p>
    </section>
    <section id="denied" class="card hidden">
      <h1>Equalizador</h1>
      <p>Acesso indisponível.</p>
    </section>
    <section id="app" class="card hidden">
      <div class="top">
        <div>
          <h1>Equalizador</h1>
          <p class="muted">Mesa em modo controlado.</p>
        </div>
        <span id="perfil" class="pill">Operador</span>
      </div>
      <div class="row"><span>Operador</span><strong id="nome">Operador</strong></div>
      <div class="row"><span>Referência segura</span><span id="ui_ref" class="muted small"></span></div>
      <h2>Palcos</h2>
      <p class="section-note">Escolha um palco antes de qualquer ajuste. A mesa só libera botões quando canal e afinação estiverem válidos.</p>
      <div id="palcos" class="grid"></div>
      <div id="mesa" class="hidden">
        <div id="mesa_status" class="statusbar muted">Mesa aguardando seleção.</div>
        <h2 id="mesa_titulo">Mesa do palco</h2>
        <div class="toolbar">
          <button class="nav secondary" data-view="mesa_view">Mesa</button>
          <button class="nav secondary" data-view="afinacao_view">Afinação</button>
          <button class="nav secondary" data-view="historico_view">Histórico</button>
          <button id="maestro_nav" class="nav secondary hidden" data-view="maestro_view">Modo Maestro</button>
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
            </div>
          </div>
        </section>
        <section id="afinacao_view" class="view hidden">
          <p class="section-note">A Afinação mostra o que o bot realmente consegue executar neste palco.</p>
          <div id="afinacao_resumo" class="statusbar muted">Aguardando sincronização.</div>
          <div id="afinacao" class="list muted">Afinação não carregada.</div>
        </section>
        <section id="historico_view" class="view hidden">
          <p class="section-note">Histórico público da mesa, sem IDs técnicos ou payload interno.</p>
          <div id="historico" class="list muted">Histórico não carregado.</div>
        </section>
        <section id="maestro_view" class="view hidden">
          <div class="panel">
            <h3>Modo Maestro</h3>
            <p class="muted small">Ações críticas exigem confirmação dupla.</p>
            <textarea id="transmissao_texto" maxlength="4096" placeholder="Texto da transmissão"></textarea>
            <p id="transmissao_contador" class="muted small">0/4096 caracteres</p>
            <div class="toolbar">
              <button class="action danger" data-action="silencio.ativar">Ativar modo silêncio</button>
              <button class="action secondary" data-action="silencio.desativar">Desativar modo silêncio</button>
              <button class="action secondary" data-action="transmissao.enviar">Enviar transmissão</button>
              <button id="exportar_historico" class="action secondary" type="button">Exportar histórico</button>
            </div>
            <label class="small"><input id="transmissao_preview" type="checkbox" checked /> sem prévia de link</label>
            <label class="small"><input id="transmissao_silenciosa" type="checkbox" /> enviar sem notificação</label>
            <label class="small"><input id="transmissao_fixar" type="checkbox" /> fixar transmissão depois do envio</label>
            <textarea id="exportacao_resultado" readonly placeholder="Exportação sanitizada aparece aqui"></textarea>
            <div id="distribuicao" class="list muted"></div>
          </div>
        </section>
        <section id="config_view" class="view hidden">
          <div class="panel">
            <h3>Configuração do Maestro</h3>
            <p class="muted small">Área somente leitura para conferência. O app não edita Railway diretamente; ele gera bloco seguro para copiar no Raw Editor.</p>
            <div class="toolbar"><button id="atualizar_configuracao" class="action secondary" type="button">Atualizar configuração</button></div>
            <h3>Palcos ativos</h3>
            <div id="config_palcos_ativos" class="list muted">Configuração não carregada.</div>
            <h3>Aliases configurados</h3>
            <div id="config_aliases" class="list muted">Configuração não carregada.</div>
            <h3>Palcos ocultos</h3>
            <div id="config_palcos_ocultos" class="list muted">Configuração não carregada.</div>
            <h3>Operadores e canais</h3>
            <div id="config_operadores" class="list muted">Configuração não carregada.</div>
            <h3>Matriz completa de permissões</h3>
            <p class="muted small">Leitura de segurança por operador, palco e canal. Canais críticos ficam marcados e operadores comuns permanecem bloqueados.</p>
            <div id="config_matriz_resumo" class="empty small">Matriz não carregada.</div>
            <div id="config_matriz" class="list muted">Configuração não carregada.</div>
            <h3>Raw Editor</h3>
            <textarea id="config_raw" readonly placeholder="Bloco gerado pelo backend"></textarea>
            <div class="toolbar"><button id="copiar_config_raw" class="action secondary" type="button" disabled>Copiar Raw Editor</button></div>
          </div>
        </section>
      </div>
      <div id="toast" class="toast hidden"></div>
    </section>
  </main>
  <script>
    (function () {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      const initData = tg && tg.initData ? tg.initData : "";
      let apiHeaders = null;
      let currentPalco = null;
      let mensagensPorRef = new Map();
      let canaisPorPalco = new Map();
      let direitosDisponiveis = new Set();
      let afinacaoLoaded = false;
      let modoMaestroPermitido = false;
      const criticalActions = new Set(["silencio.ativar", "silencio.desativar", "transmissao.enviar"]);
      const endpoints = {
        "mensagens.apagar": "mensagens/apagar",
        "membros.silenciar": "membros/silenciar",
        "membros.liberar": "membros/liberar",
        "membros.remover": "membros/remover",
        "membros.reintegrar": "membros/reintegrar",
        "fixados.criar": "fixados/criar",
        "fixados.remover": "fixados/remover",
        "convites.criar": "convites/criar",
        "silencio.ativar": "silencio/ativar",
        "silencio.desativar": "silencio/desativar",
        "transmissao.enviar": "transmissao/enviar"
      };
      const actionLabels = {
        "palco.ver": "Ver palco",
        "palco.status": "Status do palco",
        "palco.afinar": "Afinação do palco",
        "mensagens.apagar": "Apagar mensagem",
        "reacoes.limpar": "Limpar reações",
        "membros.silenciar": "Silenciar membro",
        "membros.liberar": "Liberar membro",
        "membros.remover": "Remover membro",
        "membros.reintegrar": "Reintegrar membro",
        "fixados.criar": "Fixar mensagem",
        "fixados.remover": "Remover fixado",
        "convites.criar": "Criar convite",
        "canais.ver": "Ver canais",
        "canais.distribuir": "Distribuição de canais",
        "historico.ver": "Ver histórico",
        "historico.exportar": "Exportar histórico",
        "silencio.ativar": "Ativar modo silêncio",
        "silencio.desativar": "Desativar modo silêncio",
        "transmissao.enviar": "Enviar transmissão"
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
          .replace(/-100\\d{5,}/g, "palco oculto")
          .replace(/\\b\\d{7,12}\\b/g, "referência oculta")
          .replace(/@[A-Za-z0-9_]{3,}/g, "perfil oculto");
      };
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
        const response = await fetch(url, Object.assign({ headers: apiHeaders }, options || {}));
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
          toast("Modo Maestro indisponível para este perfil.", "warn");
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
      function renderPalcos(palcos) {
        const container = document.getElementById("palcos");
        container.replaceChildren();
        if (!palcos.length) {
          container.textContent = "Nenhum palco disponível para este operador.";
          container.className = "empty";
          return;
        }
        container.className = "grid";
        for (const palco of palcos) {
          const button = document.createElement("button");
          button.className = "palco";
          button.textContent = (palco.titulo || "Palco") + " · " + (palco.estado || "habilitado");
          button.addEventListener("click", () => selectPalco(palco, button));
          container.appendChild(button);
        }
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
        document.querySelectorAll("button.action[data-action]").forEach((button) => {
          const action = button.dataset.action;
          let disabled = !currentPalco || !canRun(action);
          let title = disabled ? "Canal ou afinação indisponível" : "";
          if (criticalActions.has(action) && !modoMaestroPermitido) {
            disabled = true;
            title = "Ação restrita ao Maestro";
          }
          if (!disabled && (action.startsWith("mensagens.") || action.startsWith("fixados.")) && !mensagemRef) {
            disabled = true;
            title = "Escolha uma mensagem registrada";
          }
          if (!disabled && action === "mensagens.apagar" && mensagem && mensagem.apagavel === false) {
            disabled = true;
            title = "Mensagem fora da janela de apagamento do Telegram";
          }
          if (!disabled && action.startsWith("membros.") && !alvoRef) {
            disabled = true;
            title = "Escolha um membro registrado";
          }
          button.disabled = disabled;
          button.title = title;
        });
        if (currentPalco && afinacaoLoaded) {
          statusMesa("Mesa pronta. Botões liberados dependem do canal concedido, alvo selecionado e direito real do bot.", "ok");
        } else if (currentPalco) {
          statusMesa("Mesa aguardando Afinação. Ações permanecem bloqueadas até confirmação do bot.", "warn");
        }
      }
      async function selectPalco(palco, button) {
        currentPalco = palco;
        document.querySelectorAll(".palco").forEach((el) => el.classList.remove("active"));
        if (button) button.classList.add("active");
        document.getElementById("mesa").classList.remove("hidden");
        document.getElementById("mesa_titulo").textContent = "Mesa · " + (palco.titulo || "Palco");
        statusMesa("Carregando afinação, mensagens, membros e histórico…", "muted");
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
      const itemText = (text, sub) => {
        const item = document.createElement("div");
        item.className = "item small";
        item.innerHTML = `<strong>${text}</strong>${sub ? `<br><span class="muted">${sub}</span>` : ""}`;
        return item;
      };
      async function loadConfiguracaoMaestro() {
        if (!modoMaestroPermitido) return;
        const res = await api("/equalizador/api/configuracao");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); return; }
        fillList("config_palcos_ativos", data.palcos_ativos || [], (row) => itemText(row.titulo || "Palco", row.estado || "ativo"), "Nenhum palco ativo em TR4_EQUALIZADOR_PALCO_IDS.");
        fillList("config_aliases", data.aliases || [], (row) => itemText(row.alias || "alias", `${row.estado || "estado"} · ${row.grp_ref || ""}`), "Nenhum alias configurado em GROUP_ALIASES.");
        fillList("config_palcos_ocultos", data.palcos_ocultos || [], (row) => itemText(row.titulo || "Palco oculto", `${row.estado || "oculto"} · ${row.grp_ref || ""}`), "Nenhum palco antigo fora da variável ativa.");
        fillList("config_operadores", data.operadores || [], (row) => {
          const canais = (row.canais || []).map((canal) => canal.nome || canal.codigo).join(", ") || "sem canais";
          return itemText(`${row.perfil || "Operador"} · ${row.usr_ref || ""}`, canais);
        }, "Nenhum operador configurado.");
        const matriz = data.matriz_permissoes || {};
        const resumo = matriz.resumo || {};
        const resumoEl = document.getElementById("config_matriz_resumo");
        if (resumoEl) resumoEl.textContent = `${resumo.operadores || 0} operadores · ${resumo.palcos || 0} palcos · ${resumo.canais || 0} canais · ${resumo.canais_criticos || 0} críticos`;
        const matrizRows = [];
        (matriz.matriz || []).forEach((operador) => {
          (operador.palcos || []).forEach((palco) => {
            const concedidos = (palco.canais || []).filter((canal) => canal.concedido).map((canal) => canal.nome || canal.codigo);
            const negadosCriticos = (palco.canais || []).filter((canal) => canal.critico && !canal.concedido).length;
            matrizRows.push({
              titulo: `${operador.perfil || "Operador"} · ${operador.usr_ref || ""} · ${palco.titulo || "Palco"}`,
              detalhe: `${concedidos.length ? concedidos.join(", ") : "sem canais concedidos"}${negadosCriticos ? ` · ${negadosCriticos} críticos bloqueados` : ""}`,
            });
          });
        });
        fillList("config_matriz", matrizRows, (row) => itemText(row.titulo, row.detalhe), "Matriz sem operadores ou palcos configurados.");
        const raw = document.getElementById("config_raw");
        if (raw) raw.value = data.raw_editor || "";
        const copy = document.getElementById("copiar_config_raw");
        if (copy) copy.disabled = !(data.raw_editor || "");
      }

      async function loadPalcoData() {
        if (!currentPalco) return;
        direitosDisponiveis = new Set();
        afinacaoLoaded = false;
        const base = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref);
        const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes] = await Promise.all([
          api(base + "/afinacao").then((r) => r.ok ? r.json() : null).catch(() => null),
          api(base + "/mensagens").then((r) => r.ok ? r.json() : { mensagens: [] }).catch(() => ({ mensagens: [] })),
          api(base + "/alvos").then((r) => r.ok ? r.json() : { alvos: [] }).catch(() => ({ alvos: [] })),
          api("/equalizador/api/historico").then((r) => r.ok ? r.json() : { historico: [] }).catch(() => ({ historico: [] })),
          (modoMaestroPermitido ? api("/equalizador/api/canais/distribuicao").then((r) => r.ok ? r.json() : { distribuicao: [] }).catch(() => ({ distribuicao: [] })) : Promise.resolve({ distribuicao: [] }))
        ]);
        if (afinacaoRes && Array.isArray(afinacaoRes.canais)) {
          afinacaoLoaded = true;
          direitosDisponiveis = new Set(afinacaoRes.canais.filter((canal) => canal.disponivel).map((canal) => canal.codigo));
          const af = document.getElementById("afinacao");
          const totalDisponivel = afinacaoRes.canais.filter((canal) => canal.disponivel).length;
          const resumo = document.getElementById("afinacao_resumo");
          if (resumo) {
            resumo.textContent = `${totalDisponivel} de ${afinacaoRes.canais.length} ajustes disponíveis neste palco.`;
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
          af.textContent = "Afinação indisponível no momento. Nenhum botão operacional será liberado sem direito real confirmado.";
          const resumo = document.getElementById("afinacao_resumo");
          if (resumo) {
            resumo.textContent = "Afinação não carregada.";
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
          nome_label: `${row.nome || row.alvo_ref} · ${row.situacao || 'desconhecido'}`
        }));
        fillSelect("alvo_select", alvosOptions, "alvo_ref", "nome_label", "Nenhum membro registrado");
        const mensagensHint = document.getElementById("mensagens_hint");
        if (mensagensHint) mensagensHint.textContent = mensagensRows.length ? `${mensagensRows.length} mensagem(ns) recente(s) registradas.` : "Envie uma mensagem no palco e atualize a mesa para criar uma referência segura.";
        const alvosRows = alvosRes.alvos || [];
        const alvosHint = document.getElementById("alvos_hint");
        if (alvosHint) alvosHint.textContent = alvosRows.length ? `${alvosRows.length} membro(s) registrado(s) para operação.` : "Faça um membro enviar mensagem ou entrar no palco para criar uma referência segura.";
        const hist = document.getElementById("historico");
        const rows = (historicoRes.historico || []).filter((row) => row.palco_ref === currentPalco.grp_ref).slice(0, 20);
        hist.className = rows.length ? "list" : "list muted";
        hist.replaceChildren(...(rows.length ? rows.map((row) => {
          const item = document.createElement("div");
          item.className = "item";
          item.textContent = `${row.resumo || row.ajuste || 'Ajuste'} · ${row.status || 'registrado'}`;
          return item;
        }) : [document.createTextNode("Nenhum ajuste registrado.")]));
        const dist = document.getElementById("distribuicao");
        const distRows = distribuicaoRes.distribuicao || [];
        dist.className = distRows.length ? "list" : "list muted";
        dist.replaceChildren(...(distRows.length ? distRows.slice(0, 12).map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          const operador = row.operador && (row.operador.usr_ref || row.operador.escopo) ? (row.operador.usr_ref || row.operador.escopo) : 'Operador';
          const palco = row.palco && (row.palco.titulo || row.palco.escopo || row.palco.grp_ref) ? (row.palco.titulo || row.palco.escopo || row.palco.grp_ref) : 'Palco';
          item.textContent = `${operador} · ${palco} · ${(row.canais || []).map(canalNome).join(', ') || 'sem canais'}`;
          return item;
        }) : [document.createTextNode(modoMaestroPermitido ? "Nenhuma distribuição disponível." : "Distribuição restrita ao Maestro.")]));
        if (modoMaestroPermitido) loadConfiguracaoMaestro().catch(() => null);
        updateButtons();
      }
      async function resolveMensagemManual() {
        if (!currentPalco) { toast("Escolha um palco antes de resolver mensagem.", "warn"); return; }
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
        if (!currentPalco) { toast("Escolha um palco antes de resolver membro.", "warn"); return; }
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
          select.prepend(option(row.alvo_ref, `${row.nome || row.alvo_ref} · ${row.situacao || 'desconhecido'}`));
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
        return {};
      }
      async function runAction(action) {
        if (!currentPalco) return;
        if (!confirm("Confirmar ajuste: " + (actionLabels[action] || action) + "?")) return;
        if (criticalActions.has(action) && !confirm("Ação crítica de Maestro. Confirmar novamente?")) return;
        let payload;
        try { payload = buildPayload(action); } catch (err) { toast(err.message, "warn"); return; }
        const button = document.querySelector(`button.action[data-action="${action}"]`);
        if (button) button.disabled = true;
        statusMesa("Executando: " + (actionLabels[action] || action) + "…", "muted");
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints[action];
        const res = await api(url, { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(detailPublico(data.detail || data), "bad"); await loadPalcoData(); return; }
        if (data.convite) {
          setConviteResult(data.convite, data.dm || null, data.convite_info || null);
          try { await navigator.clipboard.writeText(data.convite); toast("Convite criado, exibido e copiado.", "ok"); }
          catch (_) { toast("Convite criado e exibido na Mesa.", "ok"); }
        } else {
          if (data.mensagem) setMensagemResult(data.mensagem, data.resumo || "Ajuste de mensagem concluído.");
          if (data.membro) setMembroResult(data.membro, data.resumo || "Ajuste de membro concluído.");
          if (data.fixacao && data.fixacao.ok === false) toast("Transmissão enviada, mas não fixada: " + (data.fixacao.motivo || "afinação insuficiente"), "warn");
          toast(data.resumo || "Ajuste concluído.", "ok");
        }
        statusMesa("Último ajuste concluído: " + (actionLabels[action] || action) + ".", "ok");
        await loadPalcoData();
      }
      document.getElementById("mensagem_select").addEventListener("change", updateButtons);
      document.getElementById("alvo_select").addEventListener("change", updateButtons);
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
        if (!modoMaestroPermitido) { toast("Exportação restrita ao Maestro.", "warn"); return; }
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
      document.getElementById("copiar_config_raw").addEventListener("click", async () => {
        const value = document.getElementById("config_raw").value || "";
        if (!value) return;
        try { await navigator.clipboard.writeText(value); toast("Bloco Raw Editor copiado.", "ok"); }
        catch (_) { toast("Não foi possível copiar automaticamente. Selecione o campo Raw Editor.", "warn"); }
      });
      if (!initData) { show("denied"); return; }
      const bootstrapHeaders = { "Authorization": "tma " + initData };
      fetch("/equalizador/api/me", { headers: bootstrapHeaders })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("denied")))
        .then((me) => {
          const sessionToken = me.sessao && me.sessao.token ? me.sessao.token : "";
          apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : bootstrapHeaders;
          document.getElementById("nome").textContent = me.nome || "Operador";
          document.getElementById("perfil").textContent = me.perfil || "Operador";
          document.getElementById("ui_ref").textContent = me.ui_ref || "";
          aplicarPerfil(me);
          return Promise.all([
            fetch("/equalizador/api/palcos", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { palcos: [] }),
            fetch("/equalizador/api/canais", { headers: apiHeaders }).then((r) => r.ok ? r.json() : { canais: [] })
          ]);
        })
        .then(([palcosData, canaisData]) => {
          renderCanais(canaisData.canais || []);
          renderPalcos(palcosData.palcos || []);
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
        raise HTTPException(status_code=429, detail="Mesa temporariamente indisponível.") from exc
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
        "perfil": operador["perfil"],
        "canais": canais,
        "modo_maestro": modo_maestro,
        "sessao": create_equalizador_session(
            identity=identity,
            ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
        ),
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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
        raise HTTPException(status_code=409, detail="Afinação insuficiente.") from exc
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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
        raise HTTPException(status_code=409, detail="Afinação insuficiente.") from exc
    except MesaError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail=mesa_error_public_detail(exc)) from exc
    except MaestroError as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail=maestro_error_public_detail(exc)) from exc
    raise HTTPException(status_code=404, detail="Ajuste indisponível.")


@router.get("/api/me")
def equalizador_me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="bootstrap")
    return _public_operator_payload(identity)


@router.get("/api/palcos")
def equalizador_palcos(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palcos_visiveis = filter_palco_ids_by_canal(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_ids=settings.equalizador_allowed_palco_ids(),
        canal_codigo="palco.ver",
        is_maestro=_is_maestro(identity),
    )
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
    _require_any_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigos=("palco.afinar", "palco.status"))
    try:
        return await sincronizar_afinacao_palco(
            grp_ref=grp_ref,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
        )
    except PalcoNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Palco indisponível.") from exc


@router.get("/api/palcos/{grp_ref}/mensagens")
def equalizador_palco_mensagens(
    grp_ref: str,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    identity = _require_identity(authorization, rate_kind="read")
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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
        raise HTTPException(status_code=404, detail="Palco indisponível.")
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

