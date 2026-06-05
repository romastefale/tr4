from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables, get_operador_public_by_user_id, list_equalizador_palcos
from app.equalizador.permissions import canal_codes_for_operator, parse_equalizador_canais


_CANAL_NOMES: dict[str, str] = {
    "palco.ver": "Ver grupo",
    "palco.status": "Status do grupo",
    "palco.afinar": "Permissões do bot no grupo",
    "mensagens.enviar": "Enviar mensagem",
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
    "convites.editar": "Editar convites",
    "convites.revogar": "Revogar convites",
    "entradas.ver": "Ver pedidos de entrada",
    "entradas.aprovar": "Aprovar pedidos de entrada",
    "entradas.recusar": "Recusar pedidos de entrada",
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
                    "titulo": str(row["ui_label"] or row["titulo"] or "Grupo oculto"),
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



def _split_ids_text(value: object) -> list[int]:
    if isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = str(value or "").replace(";", ",").replace("\n", ",").split(",")
    ids: list[int] = []
    for part in parts:
        text_value = str(part).strip().strip('"').strip("'")
        if not text_value:
            continue
        try:
            ids.append(int(text_value))
        except ValueError:
            continue
    return _sorted_ids(ids)


def _aliases_from_lines(value: object) -> dict[str, int]:
    if isinstance(value, dict):
        result: dict[str, int] = {}
        for key, chat_id in value.items():
            try:
                label = str(key).strip()
                if label:
                    result[label] = int(chat_id)
            except (TypeError, ValueError):
                continue
        return dict(sorted(result.items(), key=lambda item: item[0].casefold()))
    text_value = str(value or "").strip()
    if text_value.startswith("{"):
        try:
            data = json.loads(text_value)
            return _aliases_from_lines(data)
        except Exception:
            pass
    result: dict[str, int] = {}
    for line in text_value.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "=" in raw:
            name, raw_id = raw.split("=", 1)
        elif ":" in raw:
            name, raw_id = raw.split(":", 1)
        else:
            continue
        label = name.strip().strip('"').strip("'")
        try:
            chat_id = int(raw_id.strip().strip('"').strip("'"))
        except ValueError:
            continue
        if label:
            result[label] = chat_id
    return dict(sorted(result.items(), key=lambda item: item[0].casefold()))


def formulario_maestro_atual() -> dict[str, object]:
    aliases = settings.group_aliases()
    alias_lines = "\n".join(f"{name}={chat_id}" for name, chat_id in sorted(aliases.items(), key=lambda item: item[0].casefold()))
    return {
        "enabled": bool(settings.TR4_EQUALIZADOR_ENABLED),
        "app_name": settings.TR4_EQUALIZADOR_APP_NAME,
        "aliases_linhas": alias_lines,
        "palco_ids": ",".join(str(value) for value in _sorted_ids(settings.equalizador_allowed_palco_ids())),
        "maestro_ids": ",".join(str(value) for value in _sorted_ids(settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET)),
        "operador_ids": ",".join(str(value) for value in _sorted_ids(settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET)),
        "canais": settings.equalizador_canais_raw(),
        "hide_technical_ids": bool(settings.TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS),
        "initdata_max_age_seconds": int(settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS),
        "session_ttl_seconds": int(settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS),
        "rate_limit_per_minute": int(settings.TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE),
    }


def raw_editor_from_form_payload(payload: dict[str, Any]) -> dict[str, object]:
    """Generate a Raw Editor block from administrator-friendly fields without mutating Railway."""
    aliases = _aliases_from_lines(payload.get("aliases_linhas") or payload.get("aliases") or "")
    palco_ids = _split_ids_text(payload.get("palco_ids"))
    maestro_ids = _split_ids_text(payload.get("maestro_ids"))
    operador_ids = _split_ids_text(payload.get("operador_ids"))
    app_name = str(payload.get("app_name") or settings.TR4_EQUALIZADOR_APP_NAME or "equalizador").strip() or "equalizador"
    enabled = str(payload.get("enabled", "true")).strip().lower() not in {"0", "false", "no", "não", "off"}
    hide_ids = str(payload.get("hide_technical_ids", "true")).strip().lower() not in {"0", "false", "no", "não", "off"}
    canais_raw = str(payload.get("canais") or "").strip()
    if not canais_raw and maestro_ids:
        canais_raw = ";".join(f"{user_id}:*: *".replace(":*:", ":*:*") for user_id in maestro_ids)
    aliases_json = json.dumps(aliases, ensure_ascii=False, separators=(",", ":"))
    linhas = [
        f'GROUP_ALIASES={json.dumps(aliases_json, ensure_ascii=False)}',
        f'TR4_EQUALIZADOR_ENABLED="{str(enabled).lower()}"',
        f'TR4_EQUALIZADOR_APP_NAME="{app_name}"',
        f'TR4_EQUALIZADOR_MAESTRO_IDS="{",".join(str(value) for value in maestro_ids)}"',
        f'TR4_EQUALIZADOR_OPERADOR_IDS="{",".join(str(value) for value in operador_ids)}"',
        f'TR4_EQUALIZADOR_PALCO_IDS="{",".join(str(value) for value in palco_ids)}"',
        f'TR4_EQUALIZADOR_CANAIS={json.dumps(canais_raw, ensure_ascii=False)}',
        f'TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS="{str(hide_ids).lower()}"',
        f'TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS="{int(payload.get("initdata_max_age_seconds") or settings.TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS)}"',
        f'TR4_EQUALIZADOR_SESSION_TTL_SECONDS="{int(payload.get("session_ttl_seconds") or settings.TR4_EQUALIZADOR_SESSION_TTL_SECONDS)}"',
        f'TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE="{int(payload.get("rate_limit_per_minute") or settings.TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE)}"',
    ]
    avisos: list[str] = []
    alias_ids = set(aliases.values())
    palco_set = set(palco_ids)
    fora_de_alias = sorted(palco_set - alias_ids)
    fora_de_palco = sorted(alias_ids - palco_set)
    if fora_de_alias:
        avisos.append("Há palcos ativos sem alias público.")
    if fora_de_palco:
        avisos.append("Há aliases fora da lista de palcos ativos; eles ficarão ocultos.")
    if not maestro_ids:
        avisos.append("Nenhum administrador principal informado.")
    return {
        "raw_editor": "\n".join(linhas),
        "resumo": {
            "aliases": len(aliases),
            "palcos": len(palco_ids),
            "maestros": len(maestro_ids),
            "operadores": len(operador_ids),
        },
        "avisos": avisos,
    }

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
        operador = get_operador_public_by_user_id(
            user_id=int(user_id),
            alias_secret=alias_secret,
            perfil="Administrador principal" if is_maestro else "Operador",
        )
        operador.update({
            "perfil": "Administrador principal" if is_maestro else "Operador",
            "modo_maestro": bool(is_maestro),
            "canais": [{"codigo": codigo, "nome": nome_canal_publico(codigo)} for codigo in canais],
        })
        rows.append(operador)
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
        "formulario": formulario_maestro_atual(),
        "raw_editor": raw_editor_equalizador_block(),
        "observacao": "Use os campos amigáveis para montar a configuração. Gere Raw Editor apenas no final e não deixe chaves duplicadas. Nomes públicos e @username aparecem quando já conhecidos; IDs seguem restritos à configuração.",
    }
