from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.db.database import engine as default_engine
from app.equalizador.afinacao import canais_from_bot_rights, get_palco_internal_by_ref, public_rights_from_member
from app.equalizador.identity import make_ui_ref
from app.equalizador.palcos import ensure_equalizador_tables


class PainelDinamicoError(RuntimeError):
    """Raised when the dynamic moderation panel cannot be built."""


TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


RIGHT_LABELS: dict[str, str] = {
    "can_manage_chat": "Gerenciar palco",
    "can_delete_messages": "Apagar mensagens",
    "can_restrict_members": "Restringir/remover membros",
    "can_invite_users": "Convidar e aprovar entrada",
    "can_pin_messages": "Fixar mensagens",
    "can_change_info": "Alterar título/descrição",
    "can_promote_members": "Promover administradores",
    "can_manage_topics": "Gerenciar tópicos",
    "can_manage_video_chats": "Gerenciar chamadas",
    "can_manage_direct_messages": "Gerenciar mensagens diretas",
    "can_post_stories": "Publicar stories",
    "can_edit_stories": "Editar stories",
    "can_delete_stories": "Apagar stories",
}

ACTION_CATALOG: tuple[dict[str, object], ...] = (
    {"codigo": "mensagens.apagar", "nome": "Apagar mensagem", "categoria": "Mensagens", "direitos": ("can_delete_messages",)},
    {"codigo": "fixados.criar", "nome": "Fixar mensagem", "categoria": "Mensagens", "direitos": ("can_pin_messages",)},
    {"codigo": "fixados.remover", "nome": "Remover fixado", "categoria": "Mensagens", "direitos": ("can_pin_messages",)},
    {"codigo": "reacoes.limpar", "nome": "Limpar reações", "categoria": "Mensagens", "direitos": ("can_delete_messages",)},
    {"codigo": "membros.silenciar", "nome": "Silenciar membro", "categoria": "Membros", "direitos": ("can_restrict_members",)},
    {"codigo": "membros.liberar", "nome": "Liberar membro", "categoria": "Membros", "direitos": ("can_restrict_members",)},
    {"codigo": "membros.remover", "nome": "Remover membro", "categoria": "Membros", "direitos": ("can_restrict_members",)},
    {"codigo": "membros.reintegrar", "nome": "Reintegrar membro", "categoria": "Membros", "direitos": ("can_restrict_members",)},
    {"codigo": "convites.criar", "nome": "Criar convite", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "convites.editar", "nome": "Editar convite", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "convites.revogar", "nome": "Revogar convite", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "convites.exportar_primario", "nome": "Exportar link primário", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "entradas.aprovar", "nome": "Aprovar pedido de entrada", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "entradas.recusar", "nome": "Recusar pedido de entrada", "categoria": "Entradas", "direitos": ("can_invite_users",)},
    {"codigo": "grupo.titulo", "nome": "Alterar título do palco", "categoria": "Palco", "direitos": ("can_change_info",), "critico": True},
    {"codigo": "grupo.descricao", "nome": "Alterar descrição do palco", "categoria": "Palco", "direitos": ("can_change_info",), "critico": True},
    {"codigo": "topicos.criar", "nome": "Criar tópico", "categoria": "Tópicos", "direitos": ("can_manage_topics",)},
    {"codigo": "topicos.editar", "nome": "Editar tópico", "categoria": "Tópicos", "direitos": ("can_manage_topics",)},
    {"codigo": "topicos.apagar", "nome": "Apagar tópico", "categoria": "Tópicos", "direitos": ("can_delete_messages",)},
    {"codigo": "topicos.desfixar", "nome": "Remover fixados do tópico", "categoria": "Tópicos", "direitos": ("can_pin_messages",)},
    {"codigo": "topicos.geral.fechar", "nome": "Fechar tópico geral", "categoria": "Tópicos", "direitos": ("can_manage_topics",)},
    {"codigo": "topicos.geral.reabrir", "nome": "Reabrir tópico geral", "categoria": "Tópicos", "direitos": ("can_manage_topics",)},
    {"codigo": "reacoes.recentes.limpar", "nome": "Limpar reações recentes", "categoria": "Reações", "direitos": ("can_delete_messages",)},
    {"codigo": "canais_remetentes.banir", "nome": "Banir canal remetente", "categoria": "Canais remetentes", "direitos": ("can_restrict_members",)},
    {"codigo": "canais_remetentes.liberar", "nome": "Liberar canal remetente", "categoria": "Canais remetentes", "direitos": ("can_restrict_members",)},
    {"codigo": "membros.tag.definir", "nome": "Definir tag de membro", "categoria": "Membros", "direitos": ("can_manage_tags",)},
    {"codigo": "silencio.ativar", "nome": "Ativar modo silêncio", "categoria": "Maestro", "direitos": ("can_restrict_members",), "critico": True},
    {"codigo": "silencio.desativar", "nome": "Desativar modo silêncio", "categoria": "Maestro", "direitos": ("can_restrict_members",), "critico": True},
    {"codigo": "transmissao.enviar", "nome": "Enviar transmissão", "categoria": "Maestro", "direitos": ("can_manage_chat",), "critico": True},
    {"codigo": "admins.promover", "nome": "Promover administrador", "categoria": "Administração", "direitos": ("can_promote_members",), "critico": True},
    {"codigo": "admins.rebaixar", "nome": "Rebaixar administrador", "categoria": "Administração", "direitos": ("can_promote_members",), "critico": True},
    {"codigo": "admins.titulo", "nome": "Título personalizado de admin", "categoria": "Administração", "direitos": ("can_promote_members",), "critico": True},
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    return text_value.replace("@", "").strip()[:240] or fallback


def _safe_error(value: object) -> str:
    return _safe_text(value, fallback="telegram_erro")[:160]


async def _telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise PainelDinamicoError("token_indisponivel")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise PainelDinamicoError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        raise PainelDinamicoError(_safe_error(data.get("description") or "telegram_erro"))
    return data.get("result")


def _user_public(user: dict[str, Any], *, alias_secret: str) -> dict[str, object]:
    user_id = int(user.get("id") or 0)
    first = _safe_text(user.get("first_name"), fallback="")
    last = _safe_text(user.get("last_name"), fallback="")
    name = (first + " " + last).strip() or _safe_text(user.get("username"), fallback="Usuário") or "Usuário"
    username = _safe_text(user.get("username"), fallback="")
    return {
        "usr_ref": make_ui_ref("usr", user_id, alias_secret) if user_id else "usr_indisponivel",
        "nome": name,
        "username": username,
        "contato_url": f"https://t.me/{username}" if username else "",
        "bot": bool(user.get("is_bot") is True),
    }


def _admin_rights_public(member: dict[str, Any]) -> list[dict[str, object]]:
    status = str(member.get("status") or "")
    rows: list[dict[str, object]] = []
    for code, label in RIGHT_LABELS.items():
        granted = status == "creator" or member.get(code) is True
        rows.append({"codigo": code, "nome": label, "concedido": bool(granted)})
    return rows


def _admin_public(member: dict[str, Any], *, alias_secret: str) -> dict[str, object]:
    user = member.get("user") if isinstance(member.get("user"), dict) else {}
    public_user = _user_public(user, alias_secret=alias_secret)
    custom_title = _safe_text(member.get("custom_title"), fallback="")
    return {
        **public_user,
        "perfil_admin": "Criador" if str(member.get("status")) == "creator" else "Administrador",
        "titulo_customizado": custom_title,
        "direitos": _admin_rights_public(member),
    }


def _chat_public(
    chat: dict[str, Any],
    *,
    fallback_title: str,
    membros_count: int | None = None,
) -> dict[str, object]:
    permissions = chat.get("permissions") if isinstance(chat.get("permissions"), dict) else {}
    photo = chat.get("photo") if isinstance(chat.get("photo"), dict) else {}
    return {
        "titulo": _safe_text(chat.get("title"), fallback=fallback_title),
        "descricao": _safe_text(chat.get("description"), fallback="Sem descrição pública disponível."),
        "tipo": _safe_text(chat.get("type"), fallback="desconhecido"),
        "forum": bool(chat.get("is_forum") is True),
        "modo_lento_segundos": int(chat.get("slow_mode_delay") or 0) if str(chat.get("slow_mode_delay") or "0").isdigit() else 0,
        "endereco_publico": _safe_text(chat.get("username"), fallback=""),
        "membros_count": membros_count,
        "foto_disponivel": bool(photo.get("small_file_id") or photo.get("big_file_id")),
        "permissoes_padrao": {str(key): bool(value is True) for key, value in permissions.items()},
    }


def _rights_bool(member: dict[str, Any]) -> dict[str, bool]:
    status = str(member.get("status") or "")
    return {code: bool(status == "creator" or member.get(code) is True) for code in RIGHT_LABELS}


def dynamic_action_rows(bot_member: dict[str, Any]) -> list[dict[str, object]]:
    rights = _rights_bool(bot_member)
    rows: list[dict[str, object]] = []
    for item in ACTION_CATALOG:
        required = tuple(str(code) for code in item.get("direitos", ()))
        available = all(rights.get(code, False) for code in required)
        rows.append(
            {
                "codigo": str(item["codigo"]),
                "nome": str(item["nome"]),
                "categoria": str(item["categoria"]),
                "disponivel": bool(available),
                "critico": bool(item.get("critico", False)),
                "diagnostico": bool(item.get("diagnostico", False)),
                "futuro": bool(item.get("futuro", False)),
                "requer": list(required),
                "faltando": [] if available else [code for code in required if not rights.get(code, False)],
            }
        )
    return rows


async def _get_chat_administrators_with_bots(
    *,
    bot_token: str,
    chat_id: int,
    telegram_api_call: TelegramApiCallable,
) -> list[dict[str, Any]]:
    try:
        result = await telegram_api_call(bot_token, "getChatAdministrators", {"chat_id": int(chat_id), "return_bots": True})
    except PainelDinamicoError:
        result = await telegram_api_call(bot_token, "getChatAdministrators", {"chat_id": int(chat_id)})
    return [item for item in (result or []) if isinstance(item, dict)]


async def montar_painel_dinamico_palco(
    *,
    grp_ref: str,
    bot_token: str,
    alias_secret: str,
    db_engine=default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Build a sanitized, dynamic moderation panel for one palco.

    The returned payload is diagnostic/read-only: it shows what the bot can do
    and what is missing. Operational routes still enforce operator channels and
    real Bot API rights separately.
    """
    ensure_equalizador_tables(db_engine)
    palco = get_palco_internal_by_ref(grp_ref=grp_ref, db_engine=db_engine)
    if not palco:
        raise PainelDinamicoError("palco_indisponivel")
    chat_id = int(palco["telegram_chat_id"])
    titulo_fallback = str(palco.get("titulo") or "Palco")
    synced_at = _now_iso()
    try:
        me = await telegram_api_call(bot_token, "getMe", None)
        bot_id = int((me or {}).get("id") or 0)
        if bot_id <= 0:
            raise PainelDinamicoError("bot_id_indisponivel")
        chat = await telegram_api_call(bot_token, "getChat", {"chat_id": chat_id})
        if not isinstance(chat, dict):
            chat = {}
        try:
            membros_count_raw = await telegram_api_call(bot_token, "getChatMemberCount", {"chat_id": chat_id})
            membros_count = int(membros_count_raw)
        except Exception:
            membros_count = None
        bot_member = await telegram_api_call(bot_token, "getChatMember", {"chat_id": chat_id, "user_id": bot_id})
        if not isinstance(bot_member, dict):
            bot_member = {"status": "desconhecido"}
        admins_raw = await _get_chat_administrators_with_bots(
            bot_token=bot_token,
            chat_id=chat_id,
            telegram_api_call=telegram_api_call,
        )
        admins = [_admin_public(member, alias_secret=alias_secret) for member in admins_raw]
        bots_admins = [row for row in admins if row.get("bot") is True]
        direitos_bot = public_rights_from_member(bot_member)
        canais = canais_from_bot_rights(bot_member)
        acoes = dynamic_action_rows(bot_member)
        return {
            "grp_ref": str(palco["ui_ref"]),
            "sincronizado_em": synced_at,
            "palco": _chat_public(chat, fallback_title=titulo_fallback, membros_count=membros_count),
            "bot": direitos_bot,
            "canais": canais,
            "acoes": acoes,
            "administradores": admins,
            "bots_administradores": bots_admins,
            "resumo": {
                "administradores": len(admins),
                "bots_administradores": len(bots_admins),
                "acoes_disponiveis": sum(1 for row in acoes if row.get("disponivel")),
                "acoes_totais": len(acoes),
            },
        }
    except Exception as exc:
        return {
            "grp_ref": str(palco["ui_ref"]),
            "sincronizado_em": synced_at,
            "palco": {"titulo": titulo_fallback, "descricao": "Painel dinâmico indisponível.", "tipo": "desconhecido", "forum": False},
            "bot": {"status": "desconhecido", "direitos": {}},
            "canais": [],
            "acoes": [],
            "administradores": [],
            "bots_administradores": [],
            "resumo": {"administradores": 0, "bots_administradores": 0, "acoes_disponiveis": 0, "acoes_totais": 0},
            "erro": _safe_error(exc),
        }
