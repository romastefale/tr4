from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.config import settings
from app.equalizador.configuracao import nome_canal_publico
from app.equalizador.identity import make_ui_ref
from app.equalizador.permissions import CANAL_DEFINITIONS, CRITICAL_CANAL_CODES, canal_is_allowed, canais_for_palco


@dataclass(frozen=True)
class MatrizLinha:
    codigo: str
    nome: str
    critico: bool
    concedido: bool
    motivo: str


def _perfil(user_id: int) -> str:
    return "Maestro" if int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET else "Operador"


def _is_maestro(user_id: int) -> bool:
    return int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET


def _safe_alias_for_palco(chat_id: int) -> str:
    for alias, value in settings.group_aliases().items():
        if int(value) == int(chat_id):
            return str(alias)
    return "Palco"


def matriz_permissoes_publica(*, alias_secret: str) -> dict[str, object]:
    """Return a sanitized role/palco/channel matrix for the Maestro.

    This is diagnostic only. It does not grant permissions and does not expose
    Telegram user IDs, chat IDs or usernames to the Mini App.
    """
    allowed_palcos = sorted({int(value) for value in settings.equalizador_allowed_palco_ids()})
    operadores = sorted({int(value) for value in (settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET | settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET)})
    raw_canais = settings.equalizador_canais_raw()

    rows: list[dict[str, object]] = []
    for user_id in operadores:
        is_maestro = _is_maestro(user_id)
        palcos_rows: list[dict[str, object]] = []
        for chat_id in allowed_palcos:
            canais_rows: list[dict[str, object]] = []
            granted_codes = {str(row["codigo"]) for row in canais_for_palco(raw_canais=raw_canais, user_id=user_id, chat_id=chat_id, is_maestro=is_maestro)}
            for definition in CANAL_DEFINITIONS:
                granted = definition.codigo in granted_codes
                if granted:
                    motivo = "concedido"
                elif definition.critico and not is_maestro:
                    motivo = "bloqueado: canal crítico restrito ao Maestro"
                else:
                    motivo = "não concedido em TR4_EQUALIZADOR_CANAIS"
                canais_rows.append({
                    "codigo": definition.codigo,
                    "nome": nome_canal_publico(definition.codigo),
                    "critico": bool(definition.critico),
                    "concedido": bool(granted),
                    "motivo": motivo,
                })
            palcos_rows.append({
                "grp_ref": make_ui_ref("grp", chat_id, alias_secret),
                "titulo": _safe_alias_for_palco(chat_id),
                "canais_concedidos": sorted(granted_codes),
                "canais": canais_rows,
            })
        rows.append({
            "usr_ref": make_ui_ref("usr", user_id, alias_secret),
            "perfil": _perfil(user_id),
            "modo_maestro": bool(is_maestro),
            "palcos": palcos_rows,
        })

    canais_catalogo = [
        {"codigo": c.codigo, "nome": nome_canal_publico(c.codigo), "critico": bool(c.critico)}
        for c in CANAL_DEFINITIONS
    ]
    return {
        "matriz": rows,
        "canais_catalogo": canais_catalogo,
        "resumo": {
            "operadores": len(operadores),
            "palcos": len(allowed_palcos),
            "canais": len(canais_catalogo),
            "canais_criticos": len(CRITICAL_CANAL_CODES),
        },
        "observacao": "Matriz somente leitura. A fonte de verdade continua sendo TR4_EQUALIZADOR_CANAIS.",
    }
