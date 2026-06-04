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
    body { margin: 0; padding: 24px; background: var(--tg-theme-bg-color, #101014); color: var(--tg-theme-text-color, #f4f4f5); }
    main { max-width: 760px; margin: 0 auto; }
    .card { border: 1px solid rgba(255,255,255,.10); border-radius: 18px; padding: 18px; background: rgba(255,255,255,.04); }
    h1 { margin: 0 0 14px; font-size: 24px; }
    p { line-height: 1.45; }
    .muted { color: var(--tg-theme-hint-color, #a1a1aa); }
    .hidden { display: none; }
    .row { display: flex; justify-content: space-between; gap: 16px; border-top: 1px solid rgba(255,255,255,.08); padding-top: 12px; margin-top: 12px; }
    h2 { margin: 22px 0 10px; font-size: 17px; }
    ul { list-style: none; padding: 0; margin: 0; }
    li { border-top: 1px solid rgba(255,255,255,.08); padding: 12px 0; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
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
      <h1>Equalizador</h1>
      <p class="muted">Mesa em modo controlado.</p>
      <div class="row"><span>Operador</span><strong id="nome"></strong></div>
      <div class="row"><span>Perfil</span><strong id="perfil"></strong></div>
      <div class="row"><span>Referência</span><code id="ui_ref"></code></div>
      <div class="row"><span>Canais</span><span id="canais"></span></div>
      <h2>Palcos disponíveis</h2>
      <div id="palcos" class="muted">Nenhum palco disponível.</div>
      <h2>Distribuição de canais</h2>
      <div id="canais_mesa" class="muted">Nenhum canal disponível.</div>
      <h2>Afinação</h2>
      <div id="afinacao" class="muted">Nenhum diagnóstico carregado.</div>
    </section>
  </main>
  <script>
    (function () {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      const initData = tg && tg.initData ? tg.initData : "";
      const show = (id) => {
        for (const el of document.querySelectorAll("section")) el.classList.add("hidden");
        document.getElementById(id).classList.remove("hidden");
      };
      if (!initData) { show("denied"); return; }
      const headers = { "Authorization": "tma " + initData };
      fetch("/equalizador/api/me", { headers })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("denied")))
        .then((data) => {
          const sessionToken = data.sessao && data.sessao.token ? data.sessao.token : "";
          const apiHeaders = sessionToken ? { "Authorization": "eqs " + sessionToken } : headers;
          return Promise.all([
            Promise.resolve(data),
            fetch("/equalizador/api/palcos", { headers: apiHeaders }).then((response) => response.ok ? response.json() : { palcos: [] }),
            fetch("/equalizador/api/canais", { headers: apiHeaders }).then((response) => response.ok ? response.json() : { canais: [] }),
            Promise.resolve(apiHeaders)
          ]);
        })
        .then(([data, palcosData, canaisData, apiHeaders]) => {
          document.getElementById("nome").textContent = data.nome || "Operador";
          document.getElementById("perfil").textContent = data.perfil || "Operador";
          document.getElementById("ui_ref").textContent = data.ui_ref || "";
          document.getElementById("canais").textContent = Array.isArray(data.canais) ? data.canais.join(", ") : "";
          const canaisMesa = Array.isArray(canaisData.canais) ? canaisData.canais : [];
          const canaisContainer = document.getElementById("canais_mesa");
          if (canaisMesa.length) {
            const list = document.createElement("ul");
            for (const palco of canaisMesa) {
              const item = document.createElement("li");
              const nomes = Array.isArray(palco.canais) ? palco.canais.map((canal) => canal.nome || canal.codigo).join(", ") : "";
              item.textContent = (palco.titulo || "Palco") + " · " + nomes;
              list.appendChild(item);
            }
            canaisContainer.replaceChildren(list);
            canaisContainer.classList.remove("muted");
          }
          const palcos = Array.isArray(palcosData.palcos) ? palcosData.palcos : [];
          const container = document.getElementById("palcos");
          if (palcos.length) {
            const list = document.createElement("ul");
            for (const palco of palcos) {
              const item = document.createElement("li");
              item.textContent = (palco.titulo || "Palco") + " · " + (palco.estado || "habilitado");
              list.appendChild(item);
            }
            container.replaceChildren(list);
            container.classList.remove("muted");

            const afinacao = document.getElementById("afinacao");
            afinacao.textContent = "Carregando afinação…";
            Promise.all(palcos.map((palco) =>
              fetch("/equalizador/api/palcos/" + encodeURIComponent(palco.grp_ref) + "/afinacao", { headers: apiHeaders })
                .then((response) => response.ok ? response.json() : null)
                .catch(() => null)
            )).then((snapshots) => {
              const rows = snapshots.filter(Boolean);
              if (!rows.length) { afinacao.textContent = "Afinação indisponível."; return; }
              const afList = document.createElement("ul");
              for (const snapshot of rows) {
                const item = document.createElement("li");
                const available = Array.isArray(snapshot.canais)
                  ? snapshot.canais.filter((canal) => canal.disponivel).map((canal) => canal.codigo).join(", ")
                  : "";
                item.textContent = (snapshot.titulo || "Palco") + " · " + (snapshot.estado || "indisponível") + (available ? " · " + available : "");
                afList.appendChild(item);
              }
              afinacao.replaceChildren(afList);
              afinacao.classList.remove("muted");
            });
          }
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

