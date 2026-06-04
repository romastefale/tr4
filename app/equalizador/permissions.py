from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CanalDefinition:
    codigo: str
    nome: str
    critico: bool = False


@dataclass(frozen=True)
class CanalGrant:
    user_id: int | None
    chat_id: int | None
    canais: frozenset[str]
    todos_canais: bool = False


CANAL_DEFINITIONS: tuple[CanalDefinition, ...] = (
    CanalDefinition("palco.ver", "Ver palco"),
    CanalDefinition("palco.status", "Ver status do palco"),
    CanalDefinition("palco.afinar", "Afinar palco", critico=True),
    CanalDefinition("mensagens.apagar", "Apagar mensagens"),
    CanalDefinition("reacoes.limpar", "Limpar reações"),
    CanalDefinition("membros.silenciar", "Silenciar membros"),
    CanalDefinition("membros.liberar", "Liberar membros"),
    CanalDefinition("membros.remover", "Remover membros"),
    CanalDefinition("membros.reintegrar", "Reintegrar membros"),
    CanalDefinition("fixados.criar", "Fixar mensagens"),
    CanalDefinition("fixados.remover", "Remover fixados"),
    CanalDefinition("convites.criar", "Criar convites"),
    CanalDefinition("canais.ver", "Ver canais"),
    CanalDefinition("canais.distribuir", "Distribuir canais", critico=True),
    CanalDefinition("historico.ver", "Ver histórico de mesa"),
    CanalDefinition("historico.exportar", "Exportar histórico", critico=True),
    CanalDefinition("silencio.ativar", "Ativar modo silêncio", critico=True),
    CanalDefinition("transmissao.enviar", "Enviar transmissão", critico=True),
)

CANAL_BY_CODE: dict[str, CanalDefinition] = {canal.codigo: canal for canal in CANAL_DEFINITIONS}
CRITICAL_CANAL_CODES: frozenset[str] = frozenset(canal.codigo for canal in CANAL_DEFINITIONS if canal.critico)


def _parse_target_int(raw: str, *, field_name: str) -> int | None:
    value = raw.strip()
    if value == "*":
        return None
    if not value:
        raise ValueError(f"campo vazio em {field_name}")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"valor inválido em {field_name}: {value!r}") from exc


def parse_equalizador_canais(raw: str) -> list[CanalGrant]:
    """Parse TR4_EQUALIZADOR_CANAIS.

    Format: telegram_user_id:telegram_chat_id:canal1,canal2;...
    Wildcards are allowed with ``*`` for user, chat and channel list.
    """
    grants: list[CanalGrant] = []
    value = (raw or "").strip()
    if not value:
        return grants

    for block in value.split(";"):
        item = block.strip()
        if not item:
            continue
        parts = item.split(":", 2)
        if len(parts) != 3:
            raise ValueError("TR4_EQUALIZADOR_CANAIS exige user_id:chat_id:canais")
        user_raw, chat_raw, canais_raw = parts
        user_id = _parse_target_int(user_raw, field_name="user_id")
        chat_id = _parse_target_int(chat_raw, field_name="chat_id")
        canal_tokens = {token.strip() for token in canais_raw.split(",") if token.strip()}
        if not canal_tokens:
            raise ValueError("TR4_EQUALIZADOR_CANAIS exige ao menos um canal")
        todos_canais = "*" in canal_tokens
        unknown = sorted(token for token in canal_tokens if token != "*" and token not in CANAL_BY_CODE)
        if unknown:
            raise ValueError(f"canal desconhecido em TR4_EQUALIZADOR_CANAIS: {unknown[0]}")
        grants.append(
            CanalGrant(
                user_id=user_id,
                chat_id=chat_id,
                canais=frozenset() if todos_canais else frozenset(canal_tokens),
                todos_canais=todos_canais,
            )
        )
    return grants


def _grant_matches(grant: CanalGrant, *, user_id: int, chat_id: int, canal_codigo: str) -> bool:
    if grant.user_id is not None and grant.user_id != int(user_id):
        return False
    if grant.chat_id is not None and grant.chat_id != int(chat_id):
        return False
    return grant.todos_canais or canal_codigo in grant.canais


def canal_is_allowed(
    *,
    raw_canais: str,
    user_id: int,
    chat_id: int,
    canal_codigo: str,
    is_maestro: bool,
) -> bool:
    """Return whether an operator has a channel in a palco.

    The default is deny. Critical channels remain denied unless the operator is
    Maestro, even when a wildcard grant exists.
    """
    canal = CANAL_BY_CODE.get(canal_codigo)
    if canal is None:
        return False
    if canal.critico and not is_maestro:
        return False
    for grant in parse_equalizador_canais(raw_canais):
        if _grant_matches(grant, user_id=user_id, chat_id=chat_id, canal_codigo=canal_codigo):
            return True
    return False


def canais_for_palco(
    *,
    raw_canais: str,
    user_id: int,
    chat_id: int,
    is_maestro: bool,
) -> list[dict[str, object]]:
    """Return public channel rows granted to an operator for one palco."""
    rows: list[dict[str, object]] = []
    for definition in CANAL_DEFINITIONS:
        if canal_is_allowed(
            raw_canais=raw_canais,
            user_id=user_id,
            chat_id=chat_id,
            canal_codigo=definition.codigo,
            is_maestro=is_maestro,
        ):
            rows.append(
                {
                    "codigo": definition.codigo,
                    "nome": definition.nome,
                    "critico": definition.critico,
                }
            )
    return rows


def canal_codes_for_operator(
    *,
    raw_canais: str,
    user_id: int,
    chat_ids: Iterable[int],
    is_maestro: bool,
) -> list[str]:
    """Return the stable union of channel codes granted across visible palcos."""
    codes: set[str] = set()
    for chat_id in chat_ids:
        for canal in canais_for_palco(raw_canais=raw_canais, user_id=user_id, chat_id=chat_id, is_maestro=is_maestro):
            codes.add(str(canal["codigo"]))
    return [definition.codigo for definition in CANAL_DEFINITIONS if definition.codigo in codes]


def filter_palco_ids_by_canal(
    *,
    raw_canais: str,
    user_id: int,
    chat_ids: Iterable[int],
    canal_codigo: str,
    is_maestro: bool,
) -> set[int]:
    """Return only palco IDs where a channel is explicitly granted."""
    return {
        int(chat_id)
        for chat_id in chat_ids
        if canal_is_allowed(
            raw_canais=raw_canais,
            user_id=user_id,
            chat_id=int(chat_id),
            canal_codigo=canal_codigo,
            is_maestro=is_maestro,
        )
    }
