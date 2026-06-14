from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.bot.music_broadcast_core import (
    add_manual_music_catalog_item,
    add_music_broadcast_block,
    create_music_broadcast_schedule,
    music_broadcast_config_public,
    remove_manual_music_catalog_item,
    remove_music_broadcast_block,
    set_music_broadcast_schedule_paused,
    delete_music_broadcast_schedule,
)
from app.equalizador.ddx import DDX_HARD_MODE, list_ddx_publico, salvar_ddx_config
from app.equalizador.entradas import (
    criar_link_direto_owner,
    entradas_error_public_detail,
    executar_pedido_entrada,
    list_join_requests_publicos,
    reset_join_request_owner,
)
from app.equalizador.afinacao import RIGHT_FIELDS, sincronizar_afinacao_palco
from app.equalizador.mesa import list_historico_publico
from app.equalizador.governante_scope import (
    GovernanteScopeError,
    grant_governante_limit_exception,
    grant_governante_package,
    list_governante_scope_public,
    revoke_governante_limit_exception,
    revoke_governante_package,
    set_governante_daily_limit,
)
from app.equalizador.governante_webapp import CUSTOM_ALLOWED_ACTIONS, CUSTOM_PACKAGE, WEBAPP_PACKAGES
from app.equalizador.palcos import get_palco_internal_by_ref, list_equalizador_palcos
from app.equalizador.rbac_runtime import rbac_runtime_catalogo_publico

router = Router(name="show_owner")
logger = logging.getLogger(__name__)
LEGACY_SHOW_TEST_HINT = "Governante indisponível ou expirado."
SHOW_OBJECTIVE_LIMITS_LABEL = "Limites e exceções"

CAPABILITY_LABELS: tuple[tuple[str, str], ...] = (
    ("can_delete_messages", "apagar"),
    ("can_restrict_members", "ban/unban"),
    ("can_invite_users", "convites"),
    ("can_pin_messages", "fixar"),
    ("can_change_info", "info grupo"),
    ("can_promote_members", "admins"),
    ("can_manage_tags", "tags"),
)

WEBAPP_RELEASE_HINTS: tuple[str, ...] = (
    "Básico: postagem + broadcast musical do moderador",
    "Moderador: apagar por link + ban/unban + convite único",
    "Avançado: operação segura do grupo atual",
    "Personalizado: ações marcadas pelo owner em botões",
)

_STATE: dict[int, dict[str, Any]] = {}

_SHOW_SIMPLE_ACTIONS = {
    "home", "groups", "users", "packages", "custom", "save_custom", "revoke",
    "limits", "exceptions", "entries", "direct_link", "ddx", "ddx_enable", "ddx_disable", "ddx_add", "music", "music_blocks", "music_block_artist", "music_block_track", "music_catalog", "music_catalog_add", "music_schedules", "music_schedule_add", "logs", "security", "status", "gsearch", "usearch",
}
_SHOW_REF_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
_SHOW_INDEX_RE = re.compile(r"^\d{1,3}$")
_SHOW_LIMIT_RE = re.compile(r"^(0|1|5)$")
_DDX_OWNER_WORD_MAX_LEN = 80



@dataclass(frozen=True)
class ShowPalcoStatus:
    grp_ref: str
    titulo: str
    estado: str
    disponiveis: tuple[str, ...]
    faltando: tuple[str, ...]
    erro: str = ""


def is_show_owner_allowed(user_id: int) -> bool:
    """Return whether a Telegram user may use /tctl owner/maestro."""
    return int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET


def _owner_state(user_id: int) -> dict[str, Any]:
    state = _STATE.setdefault(int(user_id), {})
    state.setdefault("actions", [])
    return state


def _safe_text(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return text.replace("@", "")[:160]


def _valid_show_callback_data(data: str) -> bool:
    parts = str(data or "").split(":")
    if len(parts) < 2 or parts[0] != "show":
        return False
    action = parts[1]
    if action in _SHOW_SIMPLE_ACTIONS:
        return len(parts) == 2
    if action in {"g", "u", "x"}:
        return len(parts) == 3 and bool(_SHOW_REF_RE.fullmatch(parts[2]))
    if action == "p":
        return len(parts) == 3 and parts[2] in {"basico", "moderador", "avancado"}
    if action in {"a", "e", "ent_ap", "ent_rej", "ent_reset", "ddx_rm", "lo", "mb_rm", "mc_rm", "ms_pause", "ms_resume", "ms_delete"}:
        return len(parts) == 3 and bool(_SHOW_INDEX_RE.fullmatch(parts[2]))
    if action in {"gpage", "upage"}:
        return len(parts) == 3 and bool(_SHOW_INDEX_RE.fullmatch(parts[2]))
    if action == "l":
        return len(parts) == 4 and bool(_SHOW_INDEX_RE.fullmatch(parts[2])) and bool(_SHOW_LIMIT_RE.fullmatch(parts[3]))
    return False


def _sanitize_ddx_owner_word(value: object) -> tuple[str, str]:
    word = re.sub(r"\s+", " ", str(value or "").strip())
    if not word:
        return "", "Informe a palavra/frase para adicionar ao DDX."
    if len(word) > _DDX_OWNER_WORD_MAX_LEN:
        return "", f"Palavra/frase muito longa. Limite: {_DDX_OWNER_WORD_MAX_LEN} caracteres."
    if any(ord(ch) < 32 for ch in word):
        return "", "Palavra/frase contém caractere de controle inválido."
    if "<" in word or ">" in word:
        return "", "Evitei salvar texto com sinais de HTML. Use só a palavra/frase literal."
    return word, ""


def _operator_ref(user_id: int) -> str:
    # Internal audit-only label; raw IDs never go to the public Web App payload.
    return f"owner:{int(user_id)}"


def _rights_from_snapshot(snapshot: dict[str, Any]) -> dict[str, bool]:
    bot = snapshot.get("bot") if isinstance(snapshot.get("bot"), dict) else {}
    rights = bot.get("direitos") if isinstance(bot.get("direitos"), dict) else {}
    return {field: bool(rights.get(field) is True) for field in RIGHT_FIELDS}


def _status_from_snapshot(*, grp_ref: str, titulo: str, snapshot: dict[str, Any] | None) -> ShowPalcoStatus:
    if not snapshot:
        return ShowPalcoStatus(
            grp_ref=str(grp_ref),
            titulo=_safe_text(titulo, fallback="Grupo"),
            estado="pendente",
            disponiveis=(),
            faltando=tuple(label for _, label in CAPABILITY_LABELS),
        )
    rights = _rights_from_snapshot(snapshot)
    available = tuple(label for key, label in CAPABILITY_LABELS if rights.get(key))
    missing = tuple(label for key, label in CAPABILITY_LABELS if not rights.get(key))
    return ShowPalcoStatus(
        grp_ref=str(grp_ref),
        titulo=_safe_text(snapshot.get("titulo") or titulo, fallback="Grupo"),
        estado=_safe_text(snapshot.get("estado"), fallback="pendente"),
        disponiveis=available,
        faltando=missing,
        erro=_safe_text(snapshot.get("erro"), fallback=""),
    )


def _cached_snapshot_for_grp_ref(grp_ref: str) -> dict[str, Any] | None:
    palco = get_palco_internal_by_ref(grp_ref=grp_ref)
    if not palco:
        return None
    raw = palco.get("bot_rights_json")
    if not raw:
        return None
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def collect_show_palco_statuses(*, refresh: bool = True, limit: int = 20) -> list[ShowPalcoStatus]:
    """Collect a compact /tctl capability overview for known Equalizador groups."""
    palcos = list_equalizador_palcos(
        palco_ids=settings.equalizador_allowed_palco_ids(),
        alias_secret=settings.equalizador_alias_secret(),
    )[: max(1, int(limit))]
    statuses: list[ShowPalcoStatus] = []
    for palco in palcos:
        grp_ref = str(palco.get("grp_ref") or "")
        titulo = str(palco.get("titulo") or "Grupo")
        snapshot: dict[str, Any] | None = None
        if refresh and settings.TELEGRAM_BOT_TOKEN:
            try:
                snapshot = await sincronizar_afinacao_palco(
                    grp_ref=grp_ref,
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                )
            except Exception:
                snapshot = _cached_snapshot_for_grp_ref(grp_ref)
        else:
            snapshot = _cached_snapshot_for_grp_ref(grp_ref)
        statuses.append(_status_from_snapshot(grp_ref=grp_ref, titulo=titulo, snapshot=snapshot))
    return statuses


def _rbac_payload() -> dict[str, Any]:
    return rbac_runtime_catalogo_publico(alias_secret=settings.equalizador_alias_secret())


def _scope_payload() -> dict[str, Any]:
    return list_governante_scope_public(alias_secret=settings.equalizador_alias_secret())


def _operators() -> list[dict[str, Any]]:
    rows = _rbac_payload().get("operadores", [])
    return [row for row in rows if isinstance(row, dict)]


def _palcos() -> list[dict[str, Any]]:
    rows = _rbac_payload().get("palcos", [])
    return [row for row in rows if isinstance(row, dict) and row.get("grp_ref") and row.get("grp_ref") != "*"]


def _assignments() -> list[dict[str, Any]]:
    rows = _scope_payload().get("assignments", [])
    return [row for row in rows if isinstance(row, dict)]


def _filter_rows(rows: list[dict[str, Any]], query: object, *keys: str) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    if not q:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        hay = " ".join(str(row.get(key) or "") for key in keys).lower()
        if q in hay:
            out.append(row)
    return out


def _page_rows(rows: list[dict[str, Any]], page: object, *, per_page: int = 8) -> tuple[list[dict[str, Any]], int, int]:
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    try:
        page_i = int(page or 0)
    except Exception:
        page_i = 0
    page_i = max(0, min(page_i, total_pages - 1))
    start = page_i * per_page
    return rows[start:start + per_page], page_i, total_pages


def _selected_context_text(state: dict[str, Any]) -> str:
    usr = state.get("usr_label") or "moderador não escolhido"
    grp = state.get("grp_label") or "grupo não escolhido"
    assignment_ref = state.get("assignment_ref") or "sem pacote ativo"
    return f"Moderador: {html.escape(str(usr))}\nGrupo: {html.escape(str(grp))}\nPacote ativo: {html.escape(str(assignment_ref))}"


def _keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_keyboard() -> InlineKeyboardMarkup:
    """Owner Center organized by objectives, not by technical modules."""
    return _keyboard([
        [InlineKeyboardButton(text="Configurar moderadores", callback_data="show:groups"), InlineKeyboardButton(text="Escolher moderador", callback_data="show:users")],
        [InlineKeyboardButton(text="Pacotes e ações", callback_data="show:packages"), InlineKeyboardButton(text="Limites", callback_data="show:limits")],
        [InlineKeyboardButton(text="Exceções 24h", callback_data="show:exceptions"), InlineKeyboardButton(text="Entradas", callback_data="show:entries")],
        [InlineKeyboardButton(text="DDX", callback_data="show:ddx"), InlineKeyboardButton(text="Música", callback_data="show:music")],
        [InlineKeyboardButton(text="Logs", callback_data="show:logs"), InlineKeyboardButton(text="Diagnóstico", callback_data="show:status")],
        [InlineKeyboardButton(text="Segurança", callback_data="show:security")],
    ])


def render_show_owner_text(statuses: Iterable[ShowPalcoStatus], *, config_ok: bool, total_config_errors: int = 0) -> str:
    rows = list(statuses)
    lines: list[str] = [
        "<b>TR4 /tctl — Owner Center</b>",
        "Centro do owner: configure moderadores, DDX, música, limites, logs e segurança.",
        "",
        f"Configuração: {'OK' if config_ok else 'com avisos'}",
    ]
    if total_config_errors:
        lines.append(f"Avisos de configuração: {int(total_config_errors)}")
    lines.append(f"Grupos conhecidos: {len(rows)}")
    if not rows:
        lines.extend([
            "",
            "Nenhum grupo conhecido para o Equalizador.",
            "Configure TR4_EQUALIZADOR_PALCO_IDS e faça o bot ver os grupos antes de liberar moderadores.",
        ])
    for idx, row in enumerate(rows[:8], start=1):
        available = ", ".join(row.disponiveis) if row.disponiveis else "nenhuma capacidade crítica detectada"
        missing = ", ".join(row.faltando) if row.faltando else "nada relevante"
        lines.extend([
            "",
            f"<b>{idx}. {html.escape(row.titulo)}</b>",
            f"Estado: {html.escape(row.estado)}",
            f"Consegue: {html.escape(available)}",
            f"Falta: {html.escape(missing)}",
        ])
        if row.erro:
            lines.append(f"Aviso: {html.escape(row.erro)}")
    lines.extend([
        "",
        "<b>Pacotes Web App</b>",
        *[f"• {html.escape(item)}" for item in WEBAPP_RELEASE_HINTS],
        "",
        "<b>DDX</b>",
        "• Configuração exclusiva do owner/maestro.",
        "• Moderador não vê, não configura e não recebe logs.",
        "",
        "Use os botões por objetivo. O painel do moderador fica simples: Mensagens, Pessoas e Música.",
    ])
    text = "\n".join(lines)
    return text[:3900]


def _refresh_selected_assignment(state: dict[str, Any]) -> None:
    """Keep /tctl state aligned with an existing persisted moderator package."""
    usr_ref = str(state.get("usr_ref") or "")
    grp_ref = str(state.get("grp_ref") or "")
    if not usr_ref or not grp_ref:
        return
    assignment = next(
        (row for row in _assignments() if row.get("usr_ref") == usr_ref and row.get("grp_ref") == grp_ref),
        None,
    )
    if assignment:
        state["assignment_ref"] = assignment.get("assignment_ref") or ""
        state["actions"] = list(assignment.get("actions") or [])
    else:
        state["assignment_ref"] = ""


def _groups_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    rows_all = _filter_rows(_palcos(), state.get("group_query"), "titulo", "alias", "grp_ref")
    page_rows, page, total_pages = _page_rows(rows_all, state.get("group_page"), per_page=8)
    rows = [[InlineKeyboardButton(text=str(row.get("titulo") or "Grupo")[:32], callback_data=f"show:g:{row.get('grp_ref')}")] for row in page_rows]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"show:gpage:{page-1}"))
    if total_pages > page + 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"show:gpage:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="Buscar grupo", callback_data="show:gsearch"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    query = state.get("group_query") or ""
    prefix = f"Filtro: {html.escape(str(query))}\n" if query else ""
    return f"<b>/tctl · escolha o grupo</b>\n{prefix}Página {page+1}/{total_pages}\n" + _selected_context_text(state), _keyboard(rows)


def _users_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    rows_all = _filter_rows(_operators(), state.get("user_query"), "nome", "username", "usr_ref", "ui_ref")
    page_rows, page, total_pages = _page_rows(rows_all, state.get("user_page"), per_page=8)
    rows = [[InlineKeyboardButton(text=str(row.get("nome") or "Moderador")[:32], callback_data=f"show:u:{row.get('usr_ref') or row.get('ui_ref')}")] for row in page_rows]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"show:upage:{page-1}"))
    if total_pages > page + 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"show:upage:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="Buscar moderador", callback_data="show:usearch"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    query = state.get("user_query") or ""
    prefix = f"Filtro: {html.escape(str(query))}\n" if query else ""
    return f"<b>/tctl · escolha o moderador</b>\n{prefix}Página {page+1}/{total_pages}\n" + _selected_context_text(state), _keyboard(rows)


def _packages_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    rows = [
        [InlineKeyboardButton(text="Básico", callback_data="show:p:basico"), InlineKeyboardButton(text="Moderador", callback_data="show:p:moderador")],
        [InlineKeyboardButton(text="Avançado", callback_data="show:p:avancado"), InlineKeyboardButton(text="Personalizado", callback_data="show:custom")],
        [InlineKeyboardButton(text="Revogar pacote", callback_data="show:revoke"), InlineKeyboardButton(text="Voltar", callback_data="show:home")],
    ]
    return "<b>/tctl · pacote do moderador</b>\n" + _selected_context_text(state), _keyboard(rows)


def _custom_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    selected = set(str(x) for x in state.get("actions", []) if x)
    actions = list(CUSTOM_ALLOWED_ACTIONS)
    rows: list[list[InlineKeyboardButton]] = []
    for idx, action in enumerate(actions[:12]):
        marker = "✓ " if action in selected else "□ "
        rows.append([InlineKeyboardButton(text=(marker + action)[:48], callback_data=f"show:a:{idx}")])
    rows.append([InlineKeyboardButton(text="Salvar personalizado", callback_data="show:save_custom")])
    rows.append([InlineKeyboardButton(text="Pacotes", callback_data="show:packages"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "<b>/tctl · pacote personalizado</b>\nMarque as ações e salve.\n" + _selected_context_text(state), _keyboard(rows)


def _limits_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    assignment_ref = str(state.get("assignment_ref") or "")
    assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
    actions = list((assignment or {}).get("actions") or [])[:8]
    rows: list[list[InlineKeyboardButton]] = []
    for idx, action in enumerate(actions):
        rows.append([
            InlineKeyboardButton(text=f"{action} = 1/dia", callback_data=f"show:l:{idx}:1"),
            InlineKeyboardButton(text="5/dia", callback_data=f"show:l:{idx}:5"),
        ])
        rows.append([
            InlineKeyboardButton(text="outro valor", callback_data=f"show:lo:{idx}"),
            InlineKeyboardButton(text="sem limite", callback_data=f"show:l:{idx}:0"),
        ])
    rows.append([InlineKeyboardButton(text="Pacotes", callback_data="show:packages"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    if not assignment:
        return "<b>/tctl · limites</b>\nSelecione ou grave um pacote antes de definir limites.", _keyboard(rows)
    return "<b>/tctl · limites diários</b>\nEscolha a ação e o limite.\n" + _selected_context_text(state), _keyboard(rows)


def _exceptions_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    assignment_ref = str(state.get("assignment_ref") or "")
    assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
    actions = list((assignment or {}).get("actions") or [])[:8]
    exceptions = list((assignment or {}).get("limit_exceptions") or [])[:8]
    rows: list[list[InlineKeyboardButton]] = []
    for idx, action in enumerate(actions):
        rows.append([InlineKeyboardButton(text=f"Liberar 24h · {action}"[:48], callback_data=f"show:e:{idx}")])
    for item in exceptions:
        ref = str(item.get("exception_ref") or "")
        action = str(item.get("action") or "ação")
        rows.append([InlineKeyboardButton(text=f"Cancelar exceção · {action}"[:48], callback_data=f"show:x:{ref}")])
    rows.append([InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    if not assignment:
        return "<b>/tctl · exceções 24h</b>\nSelecione ou grave um pacote antes de liberar exceção.", _keyboard(rows)
    return "<b>/tctl · exceções 24h</b>\nA exceção vale por moderador, grupo e ação específica.\n" + _selected_context_text(state), _keyboard(rows)



def _selected_palco_for_entries(state: dict[str, Any]) -> dict[str, Any] | None:
    grp_ref = str(state.get("grp_ref") or "")
    if not grp_ref:
        return None
    return get_palco_internal_by_ref(grp_ref=grp_ref)


def _entries_for_state(state: dict[str, Any]) -> list[dict[str, object]]:
    palco = _selected_palco_for_entries(state)
    if not palco:
        return []
    return list_join_requests_publicos(palco_id=int(palco["telegram_chat_id"]), limit=10)


def _entries_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    palco = _selected_palco_for_entries(state)
    if not palco:
        return "<b>/tctl · entradas</b>\nEscolha um grupo antes de aprovar, recusar, resetar ou criar link direto.", _keyboard([[InlineKeyboardButton(text="Grupos", callback_data="show:groups"), InlineKeyboardButton(text="Voltar", callback_data="show:home")]])
    entries = _entries_for_state(state)
    state["entries_refs"] = [str(row.get("entrada_ref") or "") for row in entries]
    lines = [
        "<b>/tctl · entradas owner-only</b>",
        _selected_context_text(state),
        "",
        "Pedidos capturados pelo X9/Telegram join request. Aprovar/recusar exige permissão real can_invite_users.",
        "Link direto é owner-only e não usa aprovação.",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if not entries:
        lines.append("Nenhum pedido de entrada capturado para este grupo.")
    for idx, row in enumerate(entries[:8]):
        label = f"{idx+1}. {row.get('nome') or 'Membro'} · {row.get('situacao') or 'estado'}"
        lines.append("• " + html.escape(label))
        rows.append([
            InlineKeyboardButton(text=f"Aprovar {idx+1}", callback_data=f"show:ent_ap:{idx}"),
            InlineKeyboardButton(text=f"Recusar {idx+1}", callback_data=f"show:ent_rej:{idx}"),
        ])
        rows.append([InlineKeyboardButton(text=f"Resetar local {idx+1}", callback_data=f"show:ent_reset:{idx}")])
    rows.append([InlineKeyboardButton(text="Criar link direto", callback_data="show:direct_link")])
    rows.append([InlineKeyboardButton(text="Atualizar", callback_data="show:entries"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "\n".join(lines)[:3900], _keyboard(rows)


def _selected_palco_for_ddx(state: dict[str, Any]) -> dict[str, Any] | None:
    grp_ref = str(state.get("grp_ref") or "")
    if not grp_ref:
        return None
    return get_palco_internal_by_ref(grp_ref=grp_ref)


def _ddx_payload_for_state(state: dict[str, Any]) -> dict[str, Any]:
    palco = _selected_palco_for_ddx(state)
    if not palco:
        return {"filtros": [], "eventos": [], "pendentes": [], "resumo": {}}
    return list_ddx_publico(palco=palco, alias_secret=settings.equalizador_alias_secret())


def _ddx_words_for_state(state: dict[str, Any]) -> list[str]:
    payload = _ddx_payload_for_state(state)
    hard = next((row for row in payload.get("filtros", []) if row.get("modo") == DDX_HARD_MODE), {})
    return [str(word) for word in hard.get("palavras", [])]


def _save_ddx_words_for_state(state: dict[str, Any], *, words: list[str], enabled: bool, owner_id: int) -> None:
    palco = _selected_palco_for_ddx(state)
    if not palco:
        raise RuntimeError("Escolha um grupo antes de configurar DDX.")
    salvar_ddx_config(
        palco=palco,
        ator_ref=_operator_ref(owner_id),
        mode=DDX_HARD_MODE,
        words=words,
        enabled=enabled,
        alias_secret=settings.equalizador_alias_secret(),
    )


def _ddx_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    if not state.get("grp_ref"):
        return "<b>/tctl · DDX</b>\nEscolha um grupo antes de configurar DDX.", _keyboard([[InlineKeyboardButton(text="Grupos", callback_data="show:groups"), InlineKeyboardButton(text="Voltar", callback_data="show:home")]])
    payload = _ddx_payload_for_state(state)
    hard = next((row for row in payload.get("filtros", []) if row.get("modo") == DDX_HARD_MODE), {})
    words = [str(word) for word in hard.get("palavras", [])]
    eventos = list(payload.get("eventos") or [])
    enabled = bool(hard.get("enabled"))
    lines = [
        "<b>/tctl · DDX owner-only</b>",
        _selected_context_text(state),
        "",
        f"Status: {'ativo' if enabled else 'pausado'}",
        f"Palavras/frases: {len(words)}",
        "",
        "Palavras atuais:",
        *(f"• {html.escape(word)}" for word in words[:8]),
    ]
    if eventos:
        lines.extend(["", "Últimas ocorrências:"])
        autores: dict[str, int] = {}
        for ev in eventos[:8]:
            autor = str(ev.get('autor_ref') or ev.get('autor_nome') or 'autor')
            autores[autor] = autores.get(autor, 0) + 1
            lines.append(f"• {html.escape(str(ev.get('status') or 'evento'))} · {html.escape(str(ev.get('autor_nome') or 'autor'))} · {html.escape(', '.join(ev.get('palavras') or []))}")
        reincidentes = [autor for autor, count in autores.items() if count >= 5]
        if reincidentes:
            lines.extend(["", "Sugestão: há reincidência. Avalie banimento manual no grupo antes de confirmar qualquer ação crítica."])
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Ativar", callback_data="show:ddx_enable"), InlineKeyboardButton(text="Pausar", callback_data="show:ddx_disable")],
        [InlineKeyboardButton(text="Adicionar palavra", callback_data="show:ddx_add")],
    ]
    for idx, word in enumerate(words[:6]):
        rows.append([InlineKeyboardButton(text=("Remover · " + word)[:48], callback_data=f"show:ddx_rm:{idx}")])
    rows.append([InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "\n".join(lines)[:3900], _keyboard(rows)

def _music_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    payload = music_broadcast_config_public()
    blocks = payload.get("blocks") or []
    schedules = payload.get("schedules") or []
    catalog = payload.get("catalog") or []
    lines = [
        "<b>/tctl · música owner-only</b>",
        _selected_context_text(state),
        "",
        f"Bloqueios globais: {len(blocks)}",
        f"Catálogo manual: {len(catalog)}",
        f"Agendamentos: {len(schedules)}",
        "",
        "Controle por botões. Quando precisar de texto, o /tctl pede a entrada no privado.",
    ]
    rows = [
        [InlineKeyboardButton(text="Bloqueios", callback_data="show:music_blocks"), InlineKeyboardButton(text="Catálogo", callback_data="show:music_catalog")],
        [InlineKeyboardButton(text="Agendamentos", callback_data="show:music_schedules")],
        [InlineKeyboardButton(text="Bloquear artista", callback_data="show:music_block_artist"), InlineKeyboardButton(text="Bloquear faixa", callback_data="show:music_block_track")],
        [InlineKeyboardButton(text="Adicionar catálogo", callback_data="show:music_catalog_add"), InlineKeyboardButton(text="Agendar grupo", callback_data="show:music_schedule_add")],
        [InlineKeyboardButton(text="Voltar", callback_data="show:home")],
    ]
    return "\n".join(lines)[:3900], _keyboard(rows)


def _music_blocks_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    payload = music_broadcast_config_public()
    blocks = list(payload.get("blocks") or [])
    lines = ["<b>/tctl · Música · bloqueios</b>", _selected_context_text(state), ""]
    rows: list[list[InlineKeyboardButton]] = []
    if not blocks:
        lines.append("Nenhum artista/faixa bloqueado.")
    for idx, row in enumerate(blocks[:10]):
        kind = "artista" if row.get("block_type") == "artist" else "faixa"
        lines.append(f"• {kind}: {html.escape(str(row.get('raw_value') or ''))} · {html.escape(str(row.get('block_ref') or ''))}")
        rows.append([InlineKeyboardButton(text=("Remover · " + str(row.get('raw_value') or ''))[:48], callback_data=f"show:mb_rm:{idx}")])
    rows.append([InlineKeyboardButton(text="Bloquear artista", callback_data="show:music_block_artist"), InlineKeyboardButton(text="Bloquear faixa", callback_data="show:music_block_track")])
    rows.append([InlineKeyboardButton(text="Música", callback_data="show:music"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "\n".join(lines)[:3900], _keyboard(rows)


def _music_catalog_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    payload = music_broadcast_config_public()
    catalog = list(payload.get("catalog") or [])
    lines = ["<b>/tctl · Música · catálogo manual</b>", _selected_context_text(state), ""]
    rows: list[list[InlineKeyboardButton]] = []
    if not catalog:
        lines.append("Catálogo manual vazio.")
    for idx, row in enumerate(catalog[:10]):
        status = "ativo" if row.get("enabled") else "inativo"
        lines.append(f"• {html.escape(str(row.get('artist') or ''))} — {html.escape(str(row.get('track_name') or ''))} · {status} · {html.escape(str(row.get('catalog_ref') or ''))}")
        rows.append([InlineKeyboardButton(text=("Remover · " + str(row.get('artist') or '') + " — " + str(row.get('track_name') or ''))[:48], callback_data=f"show:mc_rm:{idx}")])
    rows.append([InlineKeyboardButton(text="Adicionar catálogo", callback_data="show:music_catalog_add")])
    rows.append([InlineKeyboardButton(text="Música", callback_data="show:music"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "\n".join(lines)[:3900], _keyboard(rows)


def _music_schedules_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    payload = music_broadcast_config_public()
    schedules = list(payload.get("schedules") or [])
    lines = ["<b>/tctl · Música · agendamentos</b>", _selected_context_text(state), ""]
    rows: list[list[InlineKeyboardButton]] = []
    if not schedules:
        lines.append("Nenhum agendamento musical ativo.")
    for idx, row in enumerate(schedules[:10]):
        status = "pausado" if row.get("paused") else "ativo"
        lines.append(f"• {html.escape(str(row.get('title') or 'Grupo'))} · {', '.join(row.get('times') or [])} · {status} · {html.escape(str(row.get('schedule_ref') or ''))}")
        if row.get("paused"):
            rows.append([InlineKeyboardButton(text=("Retomar · " + str(row.get('title') or 'Grupo'))[:48], callback_data=f"show:ms_resume:{idx}"), InlineKeyboardButton(text="Remover", callback_data=f"show:ms_delete:{idx}")])
        else:
            rows.append([InlineKeyboardButton(text=("Pausar · " + str(row.get('title') or 'Grupo'))[:48], callback_data=f"show:ms_pause:{idx}"), InlineKeyboardButton(text="Remover", callback_data=f"show:ms_delete:{idx}")])
    rows.append([InlineKeyboardButton(text="Adicionar agendamento", callback_data="show:music_schedule_add")])
    rows.append([InlineKeyboardButton(text="Música", callback_data="show:music"), InlineKeyboardButton(text="Voltar", callback_data="show:home")])
    return "\n".join(lines)[:3900], _keyboard(rows)


def _logs_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    grp_ref = str(state.get("grp_ref") or "")
    rows = list_historico_publico(palco_refs={grp_ref}, limit=8) if grp_ref else []
    lines = ["<b>/tctl · logs do grupo</b>", _selected_context_text(state), ""]
    if not grp_ref:
        lines.append("Escolha um grupo para ver os logs recentes.")
    elif not rows:
        lines.append("Nenhum log recente para este grupo.")
    for row in rows:
        lines.append(f"• {html.escape(str(row.get('created_at') or ''))} · {html.escape(str(row.get('ajuste') or 'ação'))} · {html.escape(str(row.get('status') or 'status'))} · {html.escape(str(row.get('resumo') or ''))}")
    return "\n".join(lines)[:3900], _keyboard([[InlineKeyboardButton(text="Grupos", callback_data="show:groups"), InlineKeyboardButton(text="Voltar", callback_data="show:home")]])


def _security_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "<b>/tctl · segurança</b>",
        _selected_context_text(state),
        "",
        "• /tctl só funciona na DM do owner.",
        "• DDX, logs e música automática ficam no /tctl.",
        "• Painel do moderador deve operar só Mensagens, Pessoas e Música.",
        "• Grupo atual deve ser resolvido por contexto assinado, grupo único ou seleção visual.",
        "• Ações destrutivas exigem confirmação no backend.",
    ]
    return "\n".join(lines)[:3900], _keyboard([[InlineKeyboardButton(text="Voltar", callback_data="show:home")]])


def _status_text(state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    assignments = _assignments()
    lines = ["<b>/tctl · status moderador</b>", _selected_context_text(state), "", f"Pacotes ativos de moderador: {len(assignments)}"]
    for row in assignments[:8]:
        gov = row.get("moderador") or {}
        palco = row.get("palco") or {}
        lines.append(f"• {html.escape(str(gov.get('nome') or 'Moderador'))} · {html.escape(str(palco.get('titulo') or 'Grupo'))} · {html.escape(str(row.get('pacote') or 'pacote'))}")
    return "\n".join(lines)[:3900], _keyboard([[InlineKeyboardButton(text="Voltar", callback_data="show:home")]])


async def _edit_callback(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if callback.message:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
    await callback.answer()


@router.message(lambda m: bool(m.from_user and m.chat and m.chat.type == "private" and _STATE.get(int(m.from_user.id), {}).get("awaiting")))
# compat: legacy tests expect awaiting") == "ddx_add_word" while this handler now multiplexes /tctl inputs.
async def show_owner_waiting_message(message: Message) -> None:
    if not message.from_user or not is_show_owner_allowed(int(message.from_user.id)):
        return
    state = _owner_state(int(message.from_user.id))
    awaiting = str(state.get("awaiting") or "")
    text_value = str(message.text or "").strip()
    try:
        if awaiting == "ddx_add_word":
            word, error = _sanitize_ddx_owner_word(message.text)
            if error:
                await message.answer(error)
                return
            words = _ddx_words_for_state(state)
            if word not in words:
                words.append(word)
            _save_ddx_words_for_state(state, words=words, enabled=True, owner_id=int(message.from_user.id))
            state["awaiting"] = ""
            await message.answer("Palavra adicionada ao DDX imediato.", reply_markup=_ddx_text(state)[1], parse_mode="HTML")
            return
        if awaiting == "group_search":
            state["group_query"] = text_value[:80]
            state["group_page"] = 0
            state["awaiting"] = ""
            await message.answer(_groups_text(state)[0], reply_markup=_groups_text(state)[1], parse_mode="HTML")
            return
        if awaiting == "user_search":
            state["user_query"] = text_value[:80]
            state["user_page"] = 0
            state["awaiting"] = ""
            await message.answer(_users_text(state)[0], reply_markup=_users_text(state)[1], parse_mode="HTML")
            return
        if awaiting == "limit_custom":
            assignment_ref = str(state.get("assignment_ref") or "")
            assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
            actions = list((assignment or {}).get("actions") or [])
            idx = int(state.get("limit_action_idx") or -1)
            try:
                daily_limit = int(text_value)
            except Exception:
                await message.answer("Informe um número inteiro de 0 a 999.")
                return
            if daily_limit < 0 or daily_limit > 999:
                await message.answer("Use um limite entre 0 e 999. Zero significa sem limite.")
                return
            if not assignment or idx < 0 or idx >= len(actions):
                await message.answer("Ação indisponível para limite.")
                return
            set_governante_daily_limit(
                assignment_ref=assignment_ref,
                action=str(actions[idx]),
                daily_limit=daily_limit,
                updated_by_ref=_operator_ref(int(message.from_user.id)),
            )
            state["awaiting"] = ""
            await message.answer(f"Limite salvo: {html.escape(str(actions[idx]))} = {daily_limit}/dia.", reply_markup=_limits_text(state)[1], parse_mode="HTML")
            return
        if awaiting in {"music_block_artist", "music_block_track"}:
            if not text_value:
                await message.answer("Informe o artista/faixa para bloquear.")
                return
            add_music_broadcast_block(block_type="artist" if awaiting.endswith("artist") else "track", value=text_value[:160], created_by=int(message.from_user.id))
            state["awaiting"] = ""
            await message.answer("Bloqueio musical salvo.", reply_markup=_music_blocks_text(state)[1], parse_mode="HTML")
            return
        if awaiting == "music_catalog_add":
            parts = [part.strip() for part in text_value.split("|")]
            main = parts[0] if parts else ""
            cover_url = parts[1] if len(parts) > 1 else ""
            spotify_url = parts[2] if len(parts) > 2 else ""
            if " - " in main:
                artist, track = [x.strip() for x in main.split(" - ", 1)]
            elif "—" in main:
                artist, track = [x.strip() for x in main.split("—", 1)]
            else:
                await message.answer("Formato: Artista - Música | URL_CAPA | URL_SPOTIFY")
                return
            if not cover_url:
                await message.answer("Informe uma URL de capa/card. O automático não envia música sem mídia.")
                return
            add_manual_music_catalog_item(artist=artist, track_name=track, cover_url=cover_url, spotify_url=spotify_url, created_by=int(message.from_user.id))
            state["awaiting"] = ""
            await message.answer("Música adicionada ao catálogo manual.", reply_markup=_music_catalog_text(state)[1], parse_mode="HTML")
            return
        if awaiting == "music_schedule_add":
            if not state.get("grp_ref"):
                await message.answer("Escolha um grupo antes de agendar música.")
                return
            palco = get_palco_internal_by_ref(grp_ref=str(state.get("grp_ref")))
            if not palco:
                await message.answer("Grupo indisponível para agendamento.")
                return
            create_music_broadcast_schedule(
                chat_id=int(palco["telegram_chat_id"]),
                title=str(state.get("grp_label") or palco.get("titulo") or "Grupo"),
                times=text_value,
                times_per_day=1,
                created_by=int(message.from_user.id),
                paused=True,
                preview_confirmed=True,
            )
            state["awaiting"] = ""
            await message.answer("Agendamento criado pausado. Revise em Música · Agendamentos e toque em Retomar quando estiver pronto.", reply_markup=_music_schedules_text(state)[1], parse_mode="HTML")
            return
    except Exception as exc:
        logger.exception("SHOW_OWNER_WAITING_FAILED awaiting=%s", awaiting)
        await message.answer("Não foi possível concluir essa entrada. Revise o formato e tente novamente.")
        return



@router.message(Command("town", "tctl", "show", "owner"))
async def show_owner_command(message: Message) -> None:
    """Owner-only /tctl entrypoint."""
    if not message.from_user:
        return
    if message.chat.type != "private":
        await message.answer("Use /town ou /tctl no privado do dono do código.")
        return
    if not is_show_owner_allowed(int(message.from_user.id)):
        await message.answer("Acesso indisponível.")
        return
    _owner_state(int(message.from_user.id))
    statuses = await collect_show_palco_statuses(refresh=True)
    text_value = render_show_owner_text(
        statuses,
        config_ok=settings.equalizador_config_ok(),
        total_config_errors=len(settings.equalizador_config_errors()),
    )
    await message.answer(text_value, parse_mode="HTML", disable_web_page_preview=True, reply_markup=_home_keyboard())


@router.callback_query(lambda c: bool(c.data and c.data.startswith("show:")))
async def show_owner_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_show_owner_allowed(int(callback.from_user.id)):
        await callback.answer("Acesso indisponível.", show_alert=True)
        return
    state = _owner_state(int(callback.from_user.id))
    data = str(callback.data or "")
    if not _valid_show_callback_data(data):
        logger.warning("SHOW_OWNER_INVALID_CALLBACK user_id=%s data=%r", getattr(callback.from_user, "id", None), data[:160])
        await callback.answer("Ação inválida ou expirada.", show_alert=True)
        return
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"
    try:
        if action == "home":
            await _edit_callback(callback, "<b>TR4 /tctl — Owner Center</b>\n" + _selected_context_text(state) + "\n\nEscolha um objetivo abaixo.", _home_keyboard())
            return
        if action == "groups":
            await _edit_callback(callback, *_groups_text(state))
            return
        if action == "users":
            await _edit_callback(callback, *_users_text(state))
            return
        if action == "gpage" and len(parts) >= 3:
            state["group_page"] = int(parts[2])
            await _edit_callback(callback, *_groups_text(state))
            return
        if action == "upage" and len(parts) >= 3:
            state["user_page"] = int(parts[2])
            await _edit_callback(callback, *_users_text(state))
            return
        if action == "gsearch":
            state["awaiting"] = "group_search"
            await callback.answer("Envie parte do nome do grupo no privado.", show_alert=True)
            return
        if action == "usearch":
            state["awaiting"] = "user_search"
            await callback.answer("Envie parte do nome do moderador no privado.", show_alert=True)
            return
        if action == "g" and len(parts) >= 3:
            ref = parts[2]
            row = next((item for item in _palcos() if item.get("grp_ref") == ref), None)
            if not row:
                await callback.answer("Grupo indisponível ou expirado.", show_alert=True)
                return
            state["grp_ref"] = ref
            state["grp_label"] = row.get("titulo") or "Grupo"
            _refresh_selected_assignment(state)
            await _edit_callback(callback, *_users_text(state))
            return
        if action == "u" and len(parts) >= 3:
            ref = parts[2]
            row = next((item for item in _operators() if (item.get("usr_ref") or item.get("ui_ref")) == ref), None)
            if not row:
                await callback.answer("Moderador indisponível ou expirado.", show_alert=True)
                return
            state["usr_ref"] = ref
            state["usr_label"] = row.get("nome") or "Moderador"
            _refresh_selected_assignment(state)
            await _edit_callback(callback, *_packages_text(state))
            return
        if action == "packages":
            await _edit_callback(callback, *_packages_text(state))
            return
        if action == "p" and len(parts) >= 3:
            if not state.get("usr_ref") or not state.get("grp_ref"):
                await callback.answer("Escolha grupo e moderador antes.", show_alert=True)
                return
            pacote = parts[2]
            assignment = grant_governante_package(
                usr_ref=str(state["usr_ref"]),
                grp_ref=str(state["grp_ref"]),
                pacote=pacote,
                granted_by_ref=_operator_ref(int(callback.from_user.id)),
                alias_secret=settings.equalizador_alias_secret(),
                motivo="/tctl owner",
            )
            state["assignment_ref"] = assignment.get("assignment_ref")
            await _edit_callback(callback, f"<b>Pacote {html.escape(pacote)} salvo.</b>\n" + _selected_context_text(state), _home_keyboard())
            return
        if action == "custom":
            await _edit_callback(callback, *_custom_text(state))
            return
        if action == "a" and len(parts) >= 3:
            idx = int(parts[2])
            actions = list(CUSTOM_ALLOWED_ACTIONS)
            if 0 <= idx < len(actions):
                selected = set(str(x) for x in state.get("actions", []) if x)
                if actions[idx] in selected:
                    selected.remove(actions[idx])
                else:
                    selected.add(actions[idx])
                state["actions"] = sorted(selected)
            await _edit_callback(callback, *_custom_text(state))
            return
        if action == "save_custom":
            if not state.get("usr_ref") or not state.get("grp_ref"):
                await callback.answer("Escolha grupo e moderador antes.", show_alert=True)
                return
            assignment = grant_governante_package(
                usr_ref=str(state["usr_ref"]),
                grp_ref=str(state["grp_ref"]),
                pacote=CUSTOM_PACKAGE,
                granted_by_ref=_operator_ref(int(callback.from_user.id)),
                alias_secret=settings.equalizador_alias_secret(),
                motivo="/tctl owner personalizado",
                actions=list(state.get("actions") or []),
            )
            state["assignment_ref"] = assignment.get("assignment_ref")
            await _edit_callback(callback, "<b>Pacote personalizado salvo.</b>\n" + _selected_context_text(state), _home_keyboard())
            return
        if action == "revoke":
            ref = str(state.get("assignment_ref") or "")
            if not ref:
                await callback.answer("Nenhum pacote ativo selecionado.", show_alert=True)
                return
            revoke_governante_package(assignment_ref=ref, revoked_by_ref=_operator_ref(int(callback.from_user.id)))
            state["assignment_ref"] = ""
            await _edit_callback(callback, "<b>Pacote revogado.</b>\n" + _selected_context_text(state), _home_keyboard())
            return
        if action == "limits":
            await _edit_callback(callback, *_limits_text(state))
            return
        if action == "l" and len(parts) >= 4:
            assignment_ref = str(state.get("assignment_ref") or "")
            assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
            actions = list((assignment or {}).get("actions") or [])
            idx = int(parts[2]); daily_limit = int(parts[3])
            if not assignment or idx < 0 or idx >= len(actions):
                await callback.answer("Ação indisponível.", show_alert=True)
                return
            set_governante_daily_limit(
                assignment_ref=assignment_ref,
                action=str(actions[idx]),
                daily_limit=daily_limit,
                updated_by_ref=_operator_ref(int(callback.from_user.id)),
            )
            await _edit_callback(callback, f"<b>Limite salvo: {html.escape(str(actions[idx]))} = {daily_limit}/dia.</b>\n" + _selected_context_text(state), *_limits_text(state)[1:])
            return
        if action == "exceptions":
            await _edit_callback(callback, *_exceptions_text(state))
            return
        if action == "e" and len(parts) >= 3:
            assignment_ref = str(state.get("assignment_ref") or "")
            assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
            actions = list((assignment or {}).get("actions") or [])
            idx = int(parts[2])
            if not assignment or idx < 0 or idx >= len(actions):
                await callback.answer("Ação indisponível.", show_alert=True)
                return
            grant_governante_limit_exception(
                assignment_ref=assignment_ref,
                action=str(actions[idx]),
                created_by_ref=_operator_ref(int(callback.from_user.id)),
                alias_secret=settings.equalizador_alias_secret(),
                hours=24,
            )
            await _edit_callback(callback, f"<b>Exceção 24h criada para {html.escape(str(actions[idx]))}.</b>\n" + _selected_context_text(state), _home_keyboard())
            return
        if action == "x" and len(parts) >= 3:
            assignment_ref = str(state.get("assignment_ref") or "")
            assignment = next((row for row in _assignments() if row.get("assignment_ref") == assignment_ref), None)
            active_refs = {str(item.get("exception_ref") or "") for item in list((assignment or {}).get("limit_exceptions") or [])}
            if parts[2] not in active_refs:
                await callback.answer("Exceção indisponível ou expirada.", show_alert=True)
                return
            revoke_governante_limit_exception(exception_ref=parts[2], revoked_by_ref=_operator_ref(int(callback.from_user.id)))
            await _edit_callback(callback, "<b>Exceção cancelada.</b>\n" + _selected_context_text(state), _home_keyboard())
            return
        if action == "entries":
            await _edit_callback(callback, *_entries_text(state))
            return
        if action in {"ent_ap", "ent_rej", "ent_reset"} and len(parts) >= 3:
            palco = _selected_palco_for_entries(state)
            refs = [str(ref) for ref in state.get("entries_refs", [])]
            idx = int(parts[2])
            if not palco or idx < 0 or idx >= len(refs) or not refs[idx]:
                await callback.answer("Entrada indisponível ou expirada.", show_alert=True)
                return
            try:
                if action == "ent_reset":
                    result = reset_join_request_owner(
                        palco=palco,
                        entrada_ref=refs[idx],
                        ator_ref=_operator_ref(int(callback.from_user.id)),
                        alias_secret=settings.equalizador_alias_secret(),
                    )
                else:
                    result = await executar_pedido_entrada(
                        acao="aprovar" if action == "ent_ap" else "recusar",
                        palco=palco,
                        ator_ref=_operator_ref(int(callback.from_user.id)),
                        entrada_ref=refs[idx],
                        bot_token=settings.TELEGRAM_BOT_TOKEN,
                        alias_secret=settings.equalizador_alias_secret(),
                    )
                await _edit_callback(callback, "<b>Entrada atualizada</b>\n\n" + html.escape(str(result.get("resumo") or "Concluído.")), *_entries_text(state)[1:])
            except Exception as exc:
                await callback.answer(entradas_error_public_detail(exc), show_alert=True)
            return
        if action == "direct_link":
            palco = _selected_palco_for_entries(state)
            if not palco:
                await callback.answer("Escolha um grupo antes.", show_alert=True)
                return
            try:
                result = await criar_link_direto_owner(
                    palco=palco,
                    ator_ref=_operator_ref(int(callback.from_user.id)),
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    alias_secret=settings.equalizador_alias_secret(),
                    nome="Owner direct",
                    member_limit=1,
                )
                link = html.escape(str(result.get("convite") or ""))
                await _edit_callback(callback, "<b>Link direto owner criado</b>\n\n" + (link or "Link indisponível no retorno."), *_entries_text(state)[1:])
            except Exception as exc:
                await callback.answer(entradas_error_public_detail(exc), show_alert=True)
            return
        if action == "ddx":
            await _edit_callback(callback, *_ddx_text(state))
            return
        if action == "ddx_enable":
            words = _ddx_words_for_state(state)
            _save_ddx_words_for_state(state, words=words, enabled=True, owner_id=int(callback.from_user.id))
            await _edit_callback(callback, "<b>DDX ativado.</b>\n" + _selected_context_text(state), *_ddx_text(state)[1:])
            return
        if action == "ddx_disable":
            words = _ddx_words_for_state(state)
            _save_ddx_words_for_state(state, words=words, enabled=False, owner_id=int(callback.from_user.id))
            await _edit_callback(callback, "<b>DDX pausado.</b>\n" + _selected_context_text(state), *_ddx_text(state)[1:])
            return
        if action == "ddx_add":
            if not state.get("grp_ref"):
                await callback.answer("Escolha um grupo antes.", show_alert=True)
                return
            state["awaiting"] = "ddx_add_word"
            await callback.answer("Envie a palavra/frase no chat privado.", show_alert=True)
            return
        if action == "ddx_rm" and len(parts) >= 3:
            idx = int(parts[2])
            words = _ddx_words_for_state(state)
            if 0 <= idx < len(words):
                removed = words.pop(idx)
                _save_ddx_words_for_state(state, words=words, enabled=bool(words), owner_id=int(callback.from_user.id))
                await _edit_callback(callback, f"<b>Palavra removida:</b> {html.escape(removed)}\n" + _selected_context_text(state), *_ddx_text(state)[1:])
                return
            await callback.answer("Palavra indisponível.", show_alert=True)
            return
        if action == "music":
            await _edit_callback(callback, *_music_text(state))
            return
        if action == "music_blocks":
            await _edit_callback(callback, *_music_blocks_text(state))
            return
        if action == "music_catalog":
            await _edit_callback(callback, *_music_catalog_text(state))
            return
        if action == "music_schedules":
            await _edit_callback(callback, *_music_schedules_text(state))
            return
        if action == "music_block_artist":
            state["awaiting"] = "music_block_artist"
            await callback.answer("Envie o nome do artista para bloquear.", show_alert=True)
            return
        if action == "music_block_track":
            state["awaiting"] = "music_block_track"
            await callback.answer("Envie o nome da faixa para bloquear.", show_alert=True)
            return
        if action == "music_catalog_add":
            state["awaiting"] = "music_catalog_add"
            await callback.answer("Envie: Artista - Música | URL_CAPA | URL_SPOTIFY", show_alert=True)
            return
        if action == "music_schedule_add":
            if not state.get("grp_ref"):
                await callback.answer("Escolha um grupo antes de agendar.", show_alert=True)
                return
            state["awaiting"] = "music_schedule_add"
            await callback.answer("Envie horários, exemplo: 09:00,18:00. O agendamento será criado pausado.", show_alert=True)
            return
        if action == "mb_rm" and len(parts) >= 3:
            blocks = list(music_broadcast_config_public().get("blocks") or [])[:10]
            idx = int(parts[2])
            if 0 <= idx < len(blocks):
                remove_music_broadcast_block(block_id=int(blocks[idx].get("id") or 0))
            await _edit_callback(callback, *_music_blocks_text(state))
            return
        if action == "mc_rm" and len(parts) >= 3:
            catalog = list(music_broadcast_config_public().get("catalog") or [])[:10]
            idx = int(parts[2])
            if 0 <= idx < len(catalog):
                remove_manual_music_catalog_item(catalog_ref=str(catalog[idx].get("catalog_ref") or ""))
            await _edit_callback(callback, *_music_catalog_text(state))
            return
        if action in {"ms_pause", "ms_resume", "ms_delete"} and len(parts) >= 3:
            schedules = list(music_broadcast_config_public().get("schedules") or [])[:10]
            idx = int(parts[2])
            if 0 <= idx < len(schedules):
                ref = str(schedules[idx].get("schedule_ref") or "")
                if action == "ms_delete":
                    delete_music_broadcast_schedule(schedule_ref=ref)
                else:
                    set_music_broadcast_schedule_paused(schedule_ref=ref, paused=(action == "ms_pause"))
            await _edit_callback(callback, *_music_schedules_text(state))
            return
        if action == "logs":
            await _edit_callback(callback, *_logs_text(state))
            return
        if action == "security":
            await _edit_callback(callback, *_security_text(state))
            return
        if action == "status":
            await _edit_callback(callback, *_status_text(state))
            return
    except GovernanteScopeError as exc:
        await callback.answer(exc.public_detail, show_alert=True)
        return
    except Exception:
        await callback.answer("Ação indisponível no momento.", show_alert=True)
        return
    await callback.answer()
