from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelegramErrorInfo:
    """Sanitized Telegram Bot API failure for operator-facing UI/history."""

    public_detail: str
    category: str
    status_code: int | None = None
    error_code: int | None = None
    retry_after: int | None = None


def sanitize_public_error(value: object, *, fallback: str = "Telegram recusou a operação.") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot_token_oculto", text)
    text = re.sub(r"https://api\.telegram\.org/bot[^\s/]+", "telegram_api", text, flags=re.I)
    text = re.sub(r"(?<![A-Za-z0-9_])-?100\d{5,}", "grupo oculto", text)
    text = re.sub(r"\b\d{7,16}\b", "referência oculta", text)
    text = text.replace("Bad Request: ", "").replace("Forbidden: ", "").replace("Conflict: ", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:260] or fallback


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def telegram_error_info(
    *,
    description: object,
    status_code: int | None = None,
    error_code: int | None = None,
    parameters: dict[str, Any] | None = None,
) -> TelegramErrorInfo:
    raw = sanitize_public_error(description, fallback="telegram_erro")
    lower = raw.casefold()
    params = parameters if isinstance(parameters, dict) else {}
    retry_after = _int_or_none(params.get("retry_after"))
    code = _int_or_none(error_code)
    http_status = _int_or_none(status_code)

    if code == 429 or http_status == 429 or "too many requests" in lower or retry_after is not None:
        wait = f" Aguarde {retry_after} segundo(s) e tente novamente." if retry_after else " Aguarde alguns segundos e tente novamente."
        return TelegramErrorInfo(
            public_detail="Limite do Telegram atingido." + wait,
            category="rate_limit",
            status_code=http_status,
            error_code=code,
            retry_after=retry_after,
        )

    precondition_markers = {
        "chat admin required": ("Bot precisa ser administrador do grupo para executar esta ação.", "bot_lacks_admin"),
        "not enough rights to restrict": ("Bot sem direito real de restringir membros neste grupo.", "bot_lacks_permissions"),
        "not enough rights to promote": ("Bot sem direito real de promover ou alterar administradores neste grupo.", "bot_lacks_permissions"),
        "not enough rights to delete": ("Bot sem direito real de apagar mensagens neste grupo.", "bot_lacks_permissions"),
        "not enough rights to manage topics": ("Bot sem direito real de gerenciar tópicos neste grupo.", "bot_lacks_permissions"),
        "user is not an administrator": ("O alvo não é administrador ativo no momento da ação.", "target_not_admin"),
        "user is an administrator": ("O alvo já é administrador; atualize o painel antes de repetir a operação.", "target_already_admin"),
        "right_forbidden": ("Título administrativo recusado pelo Telegram. Para título personalizado, o administrador precisa ter sido promovido pelo próprio bot e estar abaixo dele na hierarquia.", "admin_title_not_bot_promoted"),
        "user_admin_invalid": ("Título administrativo recusado pelo Telegram. O alvo precisa ser administrador elegível e promovido pelo próprio bot.", "admin_title_not_bot_promoted"),
        "can't demote chat creator": ("O dono do grupo não pode ser rebaixado pelo bot.", "target_is_creator"),
        "can't restrict chat owner": ("O dono do grupo não pode ser restringido pelo bot.", "target_is_creator"),
        "can't remove chat owner": ("O dono do grupo não pode ser removido pelo bot.", "target_is_creator"),
    }
    for marker, (message, category) in precondition_markers.items():
        if marker in lower:
            status = 403 if category.startswith("bot_lacks") else 409
            return TelegramErrorInfo(
                public_detail=message,
                category=category,
                status_code=http_status or status,
                error_code=code,
                retry_after=retry_after,
            )

    if code == 403 or http_status == 403 or "forbidden" in lower or "not enough rights" in lower:
        return TelegramErrorInfo(
            public_detail="Bot sem acesso ou sem hierarquia suficiente para executar esta ação no grupo.",
            category="forbidden",
            status_code=http_status,
            error_code=code,
            retry_after=retry_after,
        )

    if code == 409 or http_status == 409 or "conflict" in lower:
        return TelegramErrorInfo(
            public_detail="Conflito de estado no Telegram. Atualize o painel e confirme se o alvo ainda existe ou se outro processo mudou esse item.",
            category="conflict",
            status_code=http_status,
            error_code=code,
            retry_after=retry_after,
        )

    bad_request_markers = {
        "message to delete not found": "Mensagem não encontrada pelo Telegram. Ela pode já ter sido apagada ou a referência ficou antiga.",
        "message identifier is not specified": "Referência de mensagem ausente ou inválida para o Telegram.",
        "message_id_invalid": "Referência de mensagem inválida ou antiga para o Telegram.",
        "message can't be deleted": "Mensagem fora da janela de apagamento ou sem direito real de apagar.",
        "message to pin not found": "Mensagem não encontrada para fixação. Resolva novamente o link ou selecione outra mensagem.",
        "message to unpin not found": "Mensagem fixada não encontrada. Atualize o painel antes de repetir a operação.",
        "chat not found": "Grupo não encontrado pelo bot. Verifique se o bot ainda está no grupo autorizado.",
        "user not found": "Usuário não encontrado pelo bot. O alvo precisa ter sido visto pelo bot ou informado por referência válida.",
        "user is not a member": "Usuário não é membro ativo do grupo no momento da ação.",
        "not enough rights": "Bot sem direito real suficiente para executar esta ação.",
        "can't demote chat creator": "O dono do grupo não pode ser rebaixado pelo bot.",
        "can't promote chat member": "O bot não conseguiu promover esse membro. Verifique hierarquia e direitos de promoção.",
        "can't restrict self": "O bot não pode aplicar esta ação em si mesmo.",
        "administrator rights must be specified": "Escolha ao menos uma permissão administrativa para promover o membro.",
        "custom title": "Título personalizado recusado. O Telegram só permite em administrador elegível, promovido pelo próprio bot e dentro dos limites do título.",
        "photo_invalid_dimensions": "Imagem recusada por dimensão/formato. Use JPG, PNG ou WEBP com tamanho e proporção comuns.",
        "wrong file identifier": "Arquivo de imagem recusado. Envie uma imagem local novamente.",
        "file must be non-empty": "Arquivo de imagem vazio. Escolha outra imagem.",
        "invite link not found": "Convite não encontrado ou já revogado pelo Telegram.",
        "topic not found": "Tópico não encontrado. Atualize a lista de tópicos e tente novamente.",
        "topic closed": "Tópico já fechado ou indisponível. Atualize o painel antes de repetir.",
        "topic not modified": "Tópico já estava nesse estado. Atualize o painel para conferir.",
        "chat is not a forum": "Este grupo não está com fóruns/tópicos habilitados.",
    }
    for marker, message in bad_request_markers.items():
        if marker in lower:
            return TelegramErrorInfo(
                public_detail=message,
                category="bad_request",
                status_code=http_status,
                error_code=code,
                retry_after=retry_after,
            )

    if code == 400 or http_status == 400 or "bad request" in lower:
        return TelegramErrorInfo(
            public_detail=f"Telegram recusou a solicitação: {raw}",
            category="bad_request",
            status_code=http_status,
            error_code=code,
            retry_after=retry_after,
        )

    if code and code >= 500 or http_status and http_status >= 500:
        return TelegramErrorInfo(
            public_detail="Telegram instável ou indisponível no momento. Tente novamente depois.",
            category="telegram_unavailable",
            status_code=http_status,
            error_code=code,
            retry_after=retry_after,
        )

    return TelegramErrorInfo(
        public_detail=f"Telegram recusou: {raw}",
        category="telegram_rejected",
        status_code=http_status,
        error_code=code,
        retry_after=retry_after,
    )


def telegram_error_info_from_payload(*, data: dict[str, Any] | None, status_code: int | None = None) -> TelegramErrorInfo:
    payload = data if isinstance(data, dict) else {}
    return telegram_error_info(
        description=payload.get("description") or "telegram_erro",
        status_code=status_code,
        error_code=_int_or_none(payload.get("error_code")),
        parameters=payload.get("parameters") if isinstance(payload.get("parameters"), dict) else None,
    )


def telegram_error_payload(info: TelegramErrorInfo) -> dict[str, object]:
    payload: dict[str, object] = {"categoria": info.category, "motivo_publico": info.public_detail}
    if info.status_code is not None:
        payload["telegram_http_status"] = info.status_code
    if info.error_code is not None:
        payload["telegram_error_code"] = info.error_code
    if info.retry_after is not None:
        payload["retry_after"] = info.retry_after
    return payload
