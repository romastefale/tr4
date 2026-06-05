from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables, list_equalizador_palcos
from app.equalizador.permissions import canal_codes_for_operator, parse_equalizador_canais


_CANAL_NOMES: dict[str, str] = {
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
    "transmissao.enviar": "Enviar transmissão",
}


def nome_canal_publico(codigo: str) -> str:
    return _CANAL_NOMES.get(str(codigo or ""), str(codigo or "canal").replace(".", " ").replace("_", " ").strip())


def _sorted_ids(values: Iterable[int]) -> list[int]:
    return sorted({int(value) for value in values if int(value) != 0})


def aliases_ativos_publicos(*, alias_secret: str) -> list[dict[str, object]]:
    allowed = set(settings.equalizador_allowed_palco_ids())
    rows: list[dict[str, object]] = []
    for label, chat_id in sorted(settings.group_aliases().items(), key=lambda item: item[0].casefold()):
        is_active = int(chat_id) in allowed
        rows.append(
            {
                "alias": str(label),
                "grp_ref": make_ui_ref("grp", int(chat_id), alias_secret),
                "ativo": is_active,
                "estado": "ativo" if is_active else "fora da variável TR4_EQUALIZADOR_PALCO_IDS",
            }
        )
    return rows


def palcos_ocultos_publicos(*, allowed_palco_ids: set[int], alias_secret: str, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    """Return old eq_palcos rows not present in TR4_EQUALIZADOR_PALCO_IDS, without raw IDs."""
    ensure_equalizador_tables(db_engine)
    allowed = {int(value) for value in allowed_palco_ids}
    rows: list[dict[str, object]] = []
    with db_engine.begin() as conn:
        if allowed:
            placeholders = ",".join(f":id_{idx}" for idx, _ in enumerate(allowed))
            params = {f"id_{idx}": value for idx, value in enumerate(allowed)}
            result = conn.execute(
                text(
                    f"""
                    SELECT telegram_chat_id, ui_ref, ui_label, titulo, habilitado
                    FROM eq_palcos
                    WHERE telegram_chat_id NOT IN ({placeholders})
                    ORDER BY COALESCE(ui_label, titulo, ui_ref)
                    """
                ),
                params,
            ).mappings().all()
        else:
            result = conn.execute(
                text(
                    """
                    SELECT telegram_chat_id, ui_ref, ui_label, titulo, habilitado
                    FROM eq_palcos
                    ORDER BY COALESCE(ui_label, titulo, ui_ref)
                    """
                )
            ).mappings().all()
        for row in result:
            rows.append(
                {
                    "grp_ref": str(row["ui_ref"] or make_ui_ref("grp", int(row["telegram_chat_id"]), alias_secret)),
                    "titulo": str(row["ui_label"] or row["titulo"] or "Palco oculto"),
                    "estado": "oculto por configuração",
                }
            )
    return rows


def mark_unconfigured_palcos_inactive(*, allowed_palco_ids: set[int], db_engine: Engine = default_engine) -> None:
    """Keep old rows in DB for audit, but hide them from the operational UI."""
    ensure_equalizador_tables(db_engine)
    allowed = {int(value) for value in allowed_palco_ids}
    with db_engine.begin() as conn:
        if allowed:
            placeholders = ",".join(f":id_{idx}" for idx, _ in enumerate(allowed))
            params = {f"id_{idx}": value for idx, value in enumerate(allowed)}
            conn.execute(
                text(f"UPDATE eq_palcos SET habilitado=0 WHERE telegram_chat_id NOT IN ({placeholders})"),
                params,
            )
        else:
            conn.execute(text("UPDATE eq_palcos SET habilitado=0"))


def raw_editor_equalizador_block() -> str:
    """Generate a Railway Raw Editor block for the Equalizador keys only."""
    aliases = settings.group_aliases()
    aliases_json = json.dumps(aliases, ensure_ascii=False, separators=(",", ":"))
    palco_ids = ",".join(str(value) for value in _sorted_ids(settings.equalizador_allowed_palco_ids()))
    maestro_ids = ",".join(str(value) for value in _sorted_ids(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET))
    operador_ids = ",".join(str(value) for value in _sorted_ids(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET))
    linhas = [
        f'GROUP_ALIASES={json.dumps(aliases_json, ensure_ascii=False)}',
        f'TR4_EQUALIZADOR_ENABLED="{str(bool(settings.TR4_EQUALIZADOR_ENABLED)).lower()}"',
        f'TR4_EQUALIZADOR_APP_NAME="{settings.TR4_EQUALIZADOR_APP_NAME}"',
        f'TR4_EQUALIZADOR_MAESTRO_IDS="{maestro_ids}"',
        f'TR4_EQUALIZADOR_OPERADOR_IDS="{operador_ids}"',
        f'TR4_EQUALIZADOR_PALCO_IDS="{palco_ids}"',
        f'TR4_EQUALIZADOR_CANAIS={json.dumps(settings.equalizador_canais_raw(), ensure_ascii=False)}',
        f'TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS="{str(bool(settings.TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS)).lower()}"',
        f'TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS="{int(settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS)}"',
        f'TR4_EQUALIZADOR_SESSION_TTL_SECONDS="{int(settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS)}"',
        f'TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE="{int(settings.TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE)}"',
    ]
    return "\n".join(linhas)


def matriz_operadores_publica(*, alias_secret: str) -> list[dict[str, object]]:
    allowed_palcos = set(settings.equalizador_allowed_palco_ids())
    raw_canais = settings.equalizador_canais_raw()
    user_ids = set(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET) | set(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET)
    rows: list[dict[str, object]] = []
    for user_id in sorted(user_ids):
        is_maestro = int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET
        canais = canal_codes_for_operator(
            raw_canais=raw_canais,
            user_id=int(user_id),
            chat_ids=allowed_palcos,
            is_maestro=is_maestro,
        )
        rows.append(
            {
                "usr_ref": make_ui_ref("usr", int(user_id), alias_secret),
                "perfil": "Maestro" if is_maestro else "Operador",
                "canais": [{"codigo": codigo, "nome": nome_canal_publico(codigo)} for codigo in canais],
            }
        )
    return rows


def configuracao_maestro_publica(*, alias_secret: str, db_engine: Engine = default_engine) -> dict[str, object]:
    allowed_palcos = settings.equalizador_allowed_palco_ids()
    mark_unconfigured_palcos_inactive(allowed_palco_ids=allowed_palcos, db_engine=db_engine)
    ativos = list_equalizador_palcos(palco_ids=allowed_palcos, alias_secret=alias_secret, db_engine=db_engine)
    return {
        "palcos_ativos": ativos,
        "aliases": aliases_ativos_publicos(alias_secret=alias_secret),
        "palcos_ocultos": palcos_ocultos_publicos(allowed_palco_ids=allowed_palcos, alias_secret=alias_secret, db_engine=db_engine),
        "operadores": matriz_operadores_publica(alias_secret=alias_secret),
        "raw_editor": raw_editor_equalizador_block(),
        "observacao": "Confira no Railway Raw Editor. Não deixe chaves duplicadas.",
    }
