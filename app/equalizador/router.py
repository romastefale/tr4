from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.equalizador.afinacao import PalcoNotFoundError, get_palco_internal_by_ref, sincronizar_afinacao_palco
from app.equalizador.palcos import list_equalizador_palcos, upsert_operador
from app.equalizador.permissions import (
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
    executar_ajuste,
    list_historico_publico,
)
from app.equalizador.maestro import (
    MaestroConfirmationError,
    MaestroError,
    distribuicao_canais_publica,
    executar_modo_silencio,
    executar_transmissao,
    exportar_historico_publico,
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
    .toast { position: sticky; bottom: 12px; margin-top: 16px; border-radius: 14px; padding: 12px; background: rgba(255,255,255,.10); }
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
      <div id="palcos" class="grid"></div>
      <div id="mesa" class="hidden">
        <h2 id="mesa_titulo">Mesa do palco</h2>
        <div class="toolbar">
          <button class="nav secondary" data-view="mesa_view">Mesa</button>
          <button class="nav secondary" data-view="afinacao_view">Afinação</button>
          <button class="nav secondary" data-view="historico_view">Histórico</button>
          <button class="nav secondary" data-view="maestro_view">Modo Maestro</button>
        </div>
        <section id="mesa_view" class="view">
          <div class="grid">
            <div class="panel">
              <h3>Mensagens</h3>
              <select id="mensagem_select"></select>
              <div class="toolbar">
                <button class="action danger" data-action="mensagens.apagar">Apagar</button>
                <button class="action secondary" data-action="fixados.criar">Fixar</button>
                <button class="action secondary" data-action="fixados.remover">Remover fixado</button>
              </div>
              <p class="muted small">A lista usa referências internas. IDs de mensagem não aparecem.</p>
            </div>
            <div class="panel">
              <h3>Membros</h3>
              <select id="alvo_select"></select>
              <div class="toolbar">
                <button class="action secondary" data-action="membros.silenciar">Silenciar</button>
                <button class="action secondary" data-action="membros.liberar">Liberar</button>
                <button class="action danger" data-action="membros.remover">Remover</button>
                <button class="action secondary" data-action="membros.reintegrar">Reintegrar</button>
              </div>
              <p class="muted small">A lista usa referências internas. IDs de usuário não aparecem.</p>
            </div>
            <div class="panel">
              <h3>Convites</h3>
              <input id="convite_nome" maxlength="32" placeholder="Nome do convite" value="Equalizador" />
              <div class="toolbar"><button class="action secondary" data-action="convites.criar">Criar convite</button></div>
            </div>
          </div>
        </section>
        <section id="afinacao_view" class="view hidden">
          <div id="afinacao" class="list muted">Afinação não carregada.</div>
        </section>
        <section id="historico_view" class="view hidden">
          <div id="historico" class="list muted">Histórico não carregado.</div>
        </section>
        <section id="maestro_view" class="view hidden">
          <div class="panel">
            <h3>Modo Maestro</h3>
            <p class="muted small">Ações críticas exigem confirmação dupla.</p>
            <textarea id="transmissao_texto" maxlength="4096" placeholder="Texto da transmissão"></textarea>
            <div class="toolbar">
              <button class="action danger" data-action="silencio.ativar">Ativar modo silêncio</button>
              <button class="action secondary" data-action="transmissao.enviar">Enviar transmissão</button>
              <button id="exportar_historico" class="action secondary" type="button">Exportar histórico</button>
            </div>
            <div id="distribuicao" class="list muted"></div>
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
      let canaisPorPalco = new Map();
      let direitosDisponiveis = new Set();
      let afinacaoLoaded = false;
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
        "transmissao.enviar": "transmissao/enviar"
      };
      const actionLabels = {
        "mensagens.apagar": "Apagar mensagem",
        "membros.silenciar": "Silenciar membro",
        "membros.liberar": "Liberar membro",
        "membros.remover": "Remover membro",
        "membros.reintegrar": "Reintegrar membro",
        "fixados.criar": "Fixar mensagem",
        "fixados.remover": "Remover fixado",
        "convites.criar": "Criar convite",
        "silencio.ativar": "Ativar modo silêncio",
        "transmissao.enviar": "Enviar transmissão"
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
      const api = (url, options) => fetch(url, Object.assign({ headers: apiHeaders }, options || {}));
      const option = (value, label) => {
        const item = document.createElement("option");
        item.value = value;
        item.textContent = label;
        return item;
      };
      const hasCanal = (codigo) => currentPalco && (canaisPorPalco.get(currentPalco.grp_ref) || new Set()).has(codigo);
      const canRun = (codigo) => hasCanal(codigo) && (!afinacaoLoaded || direitosDisponiveis.has(codigo) || codigo === "convites.criar" || codigo === "transmissao.enviar" || codigo === "silencio.ativar");
      const openView = (id) => {
        for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
        document.getElementById(id).classList.remove("hidden");
      };
      document.querySelectorAll("button.nav").forEach((button) => button.addEventListener("click", () => openView(button.dataset.view)));
      function renderPalcos(palcos) {
        const container = document.getElementById("palcos");
        container.replaceChildren();
        if (!palcos.length) {
          container.textContent = "Nenhum palco disponível.";
          container.className = "muted";
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
        document.querySelectorAll("button.action[data-action]").forEach((button) => {
          button.disabled = !currentPalco || !canRun(button.dataset.action);
          button.title = button.disabled ? "Canal ou afinação indisponível" : "";
        });
      }
      async function selectPalco(palco, button) {
        currentPalco = palco;
        document.querySelectorAll(".palco").forEach((el) => el.classList.remove("active"));
        if (button) button.classList.add("active");
        document.getElementById("mesa").classList.remove("hidden");
        document.getElementById("mesa_titulo").textContent = "Mesa · " + (palco.titulo || "Palco");
        openView("mesa_view");
        await loadPalcoData();
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
          api("/equalizador/api/canais/distribuicao").then((r) => r.ok ? r.json() : { distribuicao: [] }).catch(() => ({ distribuicao: [] }))
        ]);
        if (afinacaoRes && Array.isArray(afinacaoRes.canais)) {
          afinacaoLoaded = true;
          direitosDisponiveis = new Set(afinacaoRes.canais.filter((canal) => canal.disponivel).map((canal) => canal.codigo));
          const af = document.getElementById("afinacao");
          af.className = "list";
          af.replaceChildren(...afinacaoRes.canais.map((canal) => {
            const item = document.createElement("div");
            item.className = "item";
            item.innerHTML = `<strong>${canal.nome}</strong><br><span class="${canal.disponivel ? 'ok' : 'bad'}">${canal.disponivel ? 'Disponível' : 'Indisponível'}</span>`;
            return item;
          }));
        }
        if (!afinacaoLoaded) {
          const af = document.getElementById("afinacao");
          af.className = "list muted";
          af.textContent = "Afinação restrita ao Maestro ou indisponível. A execução continua validada pelo servidor.";
        }
        fillSelect("mensagem_select", mensagensRes.mensagens || [], "msg_ref", "resumo", "Nenhuma mensagem registrada");
        fillSelect("alvo_select", alvosRes.alvos || [], "alvo_ref", "nome", "Nenhum membro registrado");
        const hist = document.getElementById("historico");
        const rows = (historicoRes.historico || []).filter((row) => row.palco_ref === currentPalco.grp_ref).slice(0, 20);
        hist.className = rows.length ? "list" : "list muted";
        hist.replaceChildren(...(rows.length ? rows.map((row) => {
          const item = document.createElement("div");
          item.className = "item";
          item.textContent = `${row.resumo} · ${row.status}`;
          return item;
        }) : [document.createTextNode("Nenhum ajuste registrado.")]));
        const dist = document.getElementById("distribuicao");
        const distRows = distribuicaoRes.distribuicao || [];
        dist.className = distRows.length ? "list" : "list muted";
        dist.replaceChildren(...(distRows.length ? distRows.slice(0, 12).map((row) => {
          const item = document.createElement("div");
          item.className = "item small";
          item.textContent = `${row.operador || 'Operador'} · ${(row.canais || []).join(', ') || 'sem canais'}`;
          return item;
        }) : [document.createTextNode("Distribuição indisponível para este perfil.")]));
        updateButtons();
      }
      function buildPayload(action) {
        if (action.startsWith("mensagens.") || action.startsWith("fixados.")) {
          const msg = document.getElementById("mensagem_select").value;
          if (!msg) throw new Error("Escolha uma mensagem registrada.");
          return { msg_ref: msg, sem_notificacao: true };
        }
        if (action.startsWith("membros.")) {
          const alvo = document.getElementById("alvo_select").value;
          if (!alvo) throw new Error("Escolha um membro registrado.");
          return { alvo_ref: alvo, duracao_segundos: 3600, apenas_se_banido: true };
        }
        if (action === "convites.criar") return { nome: document.getElementById("convite_nome").value || "Equalizador" };
        if (action === "silencio.ativar") return { confirmacao: "CONFIRMAR AJUSTE" };
        if (action === "transmissao.enviar") {
          const texto = document.getElementById("transmissao_texto").value.trim();
          if (!texto) throw new Error("Escreva o texto da transmissão.");
          return { texto, confirmacao: "CONFIRMAR AJUSTE", sem_preview: true };
        }
        return {};
      }
      async function runAction(action) {
        if (!currentPalco) return;
        if (!confirm("Confirmar ajuste: " + (actionLabels[action] || action) + "?")) return;
        if ((action === "silencio.ativar" || action === "transmissao.enviar") && !confirm("Ação crítica de Maestro. Confirmar novamente?")) return;
        let payload;
        try { payload = buildPayload(action); } catch (err) { toast(err.message, "warn"); return; }
        const url = "/equalizador/api/palcos/" + encodeURIComponent(currentPalco.grp_ref) + "/" + endpoints[action];
        const res = await api(url, { method: "POST", headers: Object.assign({}, apiHeaders, { "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(data.detail || "Ajuste não concluído.", "bad"); return; }
        toast(data.resumo || "Ajuste concluído.", "ok");
        await loadPalcoData();
      }
      document.querySelectorAll("button.action[data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
      document.getElementById("exportar_historico").addEventListener("click", async () => {
        const res = await api("/equalizador/api/historico/exportar");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(data.detail || "Exportação indisponível.", "bad"); return; }
        toast("Exportação gerada: " + ((data.exportacao && data.exportacao.exportacao_ref) || "pronta"), "ok");
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


def _require_identity(authorization: str | None) -> TelegramWebAppIdentity:
    identity = _identity_from_authorization(authorization)
    if not settings.equalizador_user_is_allowed(identity.user_id):
        raise HTTPException(status_code=403, detail="Acesso indisponível.")
    operador_ref = _operator_ref(identity)
    try:
        check_equalizador_rate_limit(
            operator_ref=operador_ref,
            limit_per_minute=settings.TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE,
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
    return {
        "ui_ref": operador["ui_ref"],
        "nome": operador["nome"],
        "perfil": operador["perfil"],
        "canais": canal_codes_for_operator(
            raw_canais=settings.equalizador_canais_raw(),
            user_id=identity.user_id,
            chat_ids=settings.equalizador_allowed_palco_ids(),
            is_maestro=_is_maestro(identity),
        ),
        "sessao": create_equalizador_session(
            identity=identity,
            ttl_seconds=settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS,
        ),
    }


def _require_canal_for_palco(identity: TelegramWebAppIdentity, *, palco_id: int, canal_codigo: str) -> None:
    if not canal_is_allowed(
        raw_canais=settings.equalizador_canais_raw(),
        user_id=identity.user_id,
        chat_id=palco_id,
        canal_codigo=canal_codigo,
        is_maestro=_is_maestro(identity),
    ):
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
        raise HTTPException(status_code=409, detail="Ajuste não concluído.") from exc


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
    except (MaestroError, MesaError) as exc:
        log_equalizador_event("EQUALIZADOR_MAESTRO_FAIL", ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste)
        raise HTTPException(status_code=409, detail="Ajuste não concluído.") from exc
    raise HTTPException(status_code=404, detail="Ajuste indisponível.")


@router.get("/api/me")
def equalizador_me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
    return _public_operator_payload(identity)


@router.get("/api/palcos")
def equalizador_palcos(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
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
    identity = _require_identity(authorization)
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
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Palco indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="palco.afinar")
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
    identity = _require_identity(authorization)
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
    identity = _require_identity(authorization)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        raise HTTPException(status_code=404, detail="Palco indisponível.")
    _require_canal_for_palco(identity, palco_id=int(palco["telegram_chat_id"]), canal_codigo="palco.ver")
    return {"alvos": list_alvos_publicos(palco_id=int(palco["telegram_chat_id"]))}


@router.get("/api/historico")
def equalizador_historico(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
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
    identity = _require_identity(authorization)
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


@router.get("/api/canais/distribuicao")
def equalizador_canais_distribuicao(authorization: str | None = Header(default=None)) -> dict[str, object]:
    identity = _require_identity(authorization)
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

