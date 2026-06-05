from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.configuracao import nome_canal_publico
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import get_operador_public_by_user_id, get_palco_internal_by_ref, list_equalizador_palcos
from app.equalizador.permissions import CRITICAL_CANAL_CODES
from app.equalizador.rbac_runtime import canal_is_allowed_effective


@dataclass(frozen=True)
class GovernancaPerfil:
    codigo: str
    nome: str
    descricao: str
    canais: tuple[str, ...]
    critico: bool = False


GOVERNANCA_PERFIS: tuple[GovernancaPerfil, ...] = (
    GovernancaPerfil(
        codigo="dono",
        nome="Dono do código",
        descricao="Autoridade máxima, configuração, distribuição de canais e ações críticas.",
        canais=("canais.distribuir", "palco.afinar", "historico.exportar"),
        critico=True,
    ),
    GovernancaPerfil(
        codigo="perfil",
        nome="Governante de perfil",
        descricao="Título, descrição, foto e identidade pública do grupo.",
        canais=("grupo.titulo", "grupo.descricao", "grupo.foto", "grupo.foto.remover"),
        critico=True,
    ),
    GovernancaPerfil(
        codigo="mensagens",
        nome="Governante de mensagens",
        descricao="Enviar, fixar, desfixar, apagar e resolver mensagens.",
        canais=("mensagens.enviar", "mensagens.apagar", "fixados.criar", "fixados.remover"),
    ),
    GovernancaPerfil(
        codigo="pessoas",
        nome="Governante de pessoas",
        descricao="Membros, entrada, administradores, bots e canais remetentes.",
        canais=(
            "membros.silenciar",
            "membros.liberar",
            "membros.remover",
            "membros.reintegrar",
            "membros.tag.definir",
            "entradas.ver",
            "entradas.aprovar",
            "entradas.recusar",
            "admins.promover",
            "admins.rebaixar",
            "admins.titulo",
            "canais_remetentes.banir",
            "canais_remetentes.liberar",
        ),
        critico=True,
    ),
    GovernancaPerfil(
        codigo="convites_topicos",
        nome="Governante de convites e tópicos",
        descricao="Convites, pedidos de acesso e organização de fóruns/tópicos.",
        canais=(
            "convites.criar",
            "convites.ver",
            "convites.editar",
            "convites.revogar",
            "topicos.criar",
            "topicos.editar",
            "topicos.fechar",
            "topicos.reabrir",
            "topicos.apagar",
            "topicos.desfixar",
            "topicos.geral.fechar",
            "topicos.geral.reabrir",
            "topicos.geral.ocultar",
            "topicos.geral.exibir",
            "topicos.geral.desfixar",
        ),
    ),
    GovernancaPerfil(
        codigo="radio",
        nome="Governante do Radio",
        descricao="Rascunhos, modelos, agendamento, janela de silêncio e broadcast multi-grupo.",
        canais=("mensagens.enviar", "fixados.criar", "radio.agendar", "radio.quiet", "radio.broadcast", "transmissao.enviar"),
        critico=True,
    ),
    GovernancaPerfil(
        codigo="filtros",
        nome="Governante de filtros",
        descricao="DDX imediato, DDX 10 minutos e monitor de recém-chegados com link.",
        canais=("ddx.imediato", "ddx.temporario", "novos.ver", "novos.apagar", "novos.silenciar", "novos.banir", "novos.ignorar"),
    ),
    GovernancaPerfil(
        codigo="seguranca",
        nome="Governante de segurança",
        descricao="Histórico, diagnóstico, exportação e revisão de permissões.",
        canais=("historico.ver", "historico.exportar", "palco.status", "palco.afinar", "canais.ver"),
        critico=True,
    ),
)


def catalogo_governanca_publico() -> list[dict[str, object]]:
    return [
        {
            "codigo": perfil.codigo,
            "nome": perfil.nome,
            "descricao": perfil.descricao,
            "critico": bool(perfil.critico),
            "canais": [{"codigo": codigo, "nome": nome_canal_publico(codigo)} for codigo in perfil.canais],
        }
        for perfil in GOVERNANCA_PERFIS
    ]


def _operator_ids() -> list[int]:
    return sorted({int(value) for value in (settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET | settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET) if int(value) != 0})


def _allowed_chat_ids(chat_id: int | None) -> list[int]:
    allowed = sorted({int(value) for value in settings.equalizador_allowed_palco_ids() if int(value) != 0})
    if chat_id is None:
        return allowed
    return [int(chat_id)] if int(chat_id) in set(allowed) else []


def _public_palco_label(chat_id: int, *, alias_secret: str, db_engine=default_engine) -> dict[str, object]:
    rows = list_equalizador_palcos(palco_ids={int(chat_id)}, alias_secret=alias_secret, db_engine=db_engine)
    if rows:
        row = rows[0]
        return {"grp_ref": row.get("grp_ref"), "titulo": row.get("titulo") or "Grupo"}
    return {"grp_ref": make_ui_ref("grp", int(chat_id), alias_secret), "titulo": settings.group_alias_for_chat(int(chat_id)) or "Grupo"}


def _profile_match(
    perfil: GovernancaPerfil,
    *,
    raw_canais: str,
    user_id: int,
    chat_id: int,
    is_maestro: bool,
) -> tuple[list[str], list[str]]:
    concedidos: list[str] = []
    bloqueados: list[str] = []
    for codigo in perfil.canais:
        if canal_is_allowed_effective(raw_canais=raw_canais, user_id=user_id, chat_id=chat_id, canal_codigo=codigo, is_maestro=is_maestro):
            concedidos.append(codigo)
        else:
            bloqueados.append(codigo)
    return concedidos, bloqueados


def governantes_publicos(
    *,
    alias_secret: str,
    grp_ref: str | None = None,
    db_engine=default_engine,
) -> dict[str, object]:
    """Return a sanitized governance map for the Mini App.

    This is read-only. It describes who can act in each functional window and
    which capabilities are missing. Raw Telegram user/chat IDs never leave this
    function.
    """
    chat_id: int | None = None
    palco_publico: dict[str, object] | None = None
    if grp_ref:
        palco = get_palco_internal_by_ref(grp_ref=grp_ref, db_engine=db_engine)
        if not palco:
            return {"catalogo": catalogo_governanca_publico(), "governantes": [], "palco": None, "resumo": {"governantes": 0, "janelas_ativas": 0}}
        chat_id = int(palco["telegram_chat_id"])
        palco_publico = {"grp_ref": str(palco["ui_ref"]), "titulo": str(palco.get("titulo") or palco.get("ui_label") or "Grupo")}

    raw_canais = settings.equalizador_canais_raw()
    chat_ids = _allowed_chat_ids(chat_id)
    rows: list[dict[str, object]] = []
    janelas_ativas: set[str] = set()
    for user_id in _operator_ids():
        is_maestro = int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET
        operador = get_operador_public_by_user_id(
            user_id=int(user_id),
            alias_secret=alias_secret,
            perfil="Dono do código" if is_maestro else "Governante",
            db_engine=db_engine,
        )
        palcos_rows: list[dict[str, object]] = []
        for cid in chat_ids:
            perfis_rows: list[dict[str, object]] = []
            canais_concedidos_set: set[str] = set()
            for perfil in GOVERNANCA_PERFIS:
                concedidos, bloqueados = _profile_match(
                    perfil,
                    raw_canais=raw_canais,
                    user_id=int(user_id),
                    chat_id=int(cid),
                    is_maestro=is_maestro,
                )
                if concedidos:
                    janelas_ativas.add(perfil.codigo)
                    canais_concedidos_set.update(concedidos)
                perfis_rows.append(
                    {
                        "codigo": perfil.codigo,
                        "nome": perfil.nome,
                        "descricao": perfil.descricao,
                        "ativo": bool(concedidos),
                        "critico": bool(perfil.critico or any(code in CRITICAL_CANAL_CODES for code in perfil.canais)),
                        "concedidos": [{"codigo": code, "nome": nome_canal_publico(code)} for code in concedidos],
                        "bloqueados": [{"codigo": code, "nome": nome_canal_publico(code)} for code in bloqueados[:12]],
                    }
                )
            palcos_rows.append(
                {
                    **_public_palco_label(int(cid), alias_secret=alias_secret, db_engine=db_engine),
                    "perfis": perfis_rows,
                    "canais_concedidos": [{"codigo": code, "nome": nome_canal_publico(code)} for code in sorted(canais_concedidos_set)],
                }
            )
        operador.update(
            {
                "perfil": "Dono do código" if is_maestro else "Governante",
                "modo_maestro": bool(is_maestro),
                "palcos": palcos_rows,
                "perfis_ativos": sorted({perfil["codigo"] for palco in palcos_rows for perfil in palco["perfis"] if perfil["ativo"]}),
            }
        )
        rows.append(operador)
    return {
        "catalogo": catalogo_governanca_publico(),
        "governantes": rows,
        "palco": palco_publico,
        "resumo": {
            "governantes": len(rows),
            "palcos": len(chat_ids),
            "janelas_ativas": len(janelas_ativas),
            "modo": "palco" if chat_id is not None else "global",
        },
        "observacao": "Mapa de leitura com variáveis e concessões runtime. O dono delega por TR4_EQUALIZADOR_CANAIS ou pelo painel; a interface mostra nome público e @username quando já vistos pelo bot.",
    }
