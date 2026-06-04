from __future__ import annotations

import logging
import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.config.settings import AUDIT_EXPORT_DECRYPTION_KEYS, AUDIT_EXPORT_ENCRYPTION_KEY, AUDIT_EXPORT_ENCRYPTION_KEY_ID, AUDIT_EXPORT_LIMIT, AUDIT_RETENTION_DAYS, CRITICAL_OPERATION_EXPORT_LIMIT, CRITICAL_OPERATION_RETENTION_DAYS, OPERATIONAL_LOCK_TTL_SECONDS

from app.moderation_tigrao.actions import (
    _with_telegram_retry,
    approve_join_request,
    ban_user,
    copy_message,
    create_approval_link,
    create_direct_link,
    delete_all_message_reactions,
    delete_message,
    delete_message_reaction,
    mute_reactions,
    mute_user,
    reset_entry,
    resolve_user_target,
    set_group_description,
    set_group_title,
    unban_user,
    unmute_user,
)
from app.moderation_tigrao.keyboards import (
    audit_cleanup_confirm_keyboard,
    confirm_keyboard,
    delegate_home_keyboard,
    entry_keyboard,
    ddx_keyboard,
    governance_confirm_keyboard,
    governance_keyboard,
    groups_keyboard,
    home_keyboard,
    link_result_keyboard,
    links_keyboard,
    logs_keyboard,
    messages_keyboard,
    moderators_keyboard,
    owner_home_keyboard,
    radio_keyboard,
    radio_draft_confirm_keyboard,
    radio_broadcast_confirm_keyboard,
    radio_history_keyboard,
    radio_quiet_keyboard,
    radio_schedules_keyboard,
    radio_template_manage_keyboard,
    radio_templates_keyboard,
    reactions_mod_keyboard,
    rmod_confirm_keyboard,
    rmod_duration_keyboard,
    rmod_reactors_picker_keyboard,
    security_keyboard,
    user_actions_keyboard,
)
from app.services.reaction_audit import reaction_audit_service
from app.bot.setup_commands import sync_active_grant_command_scopes, sync_user_command_scope
import secrets as _secrets


def _new_picker_nonce() -> str:
    """Sprint X3: token curto pra invalidar pickers antigos."""
    return _secrets.token_urlsafe(6)
from app.moderation_tigrao.parsers import parse_chat_id, parse_duration, parse_message_link, parse_user_id
from app.moderation_tigrao.display import group_display_name
from app.moderation_tigrao.permissions import (
    OWNER_ID,
    is_moderator_user,
    is_owner_callback,
    is_owner_private_message,
)
from app.security.permissions import (
    DELEGABLE_GRANT_PERMISSIONS,
    MODERATION_GRANT_PERMISSIONS,
    RADIO_GRANT_PERMISSIONS,
    grant_permissions,
    has_any_grant,
    has_any_radio_permission,
    has_permission,
    is_root_user,
    list_active_chat_grants,
    moderation_full_permissions,
    radio_full_permissions,
    revoke_all_chat_permissions,
    revoke_permissions,
)
from app.security.audit import cleanup_audit_events_older_than, export_audit_events_jsonl, list_recent_events as list_audit_events, log_audit_event
from app.security.callbacks import CallbackParseError, page_number, trailing_int
from app.security.critical_operations import begin_critical_operation, cleanup_critical_operations_older_than, export_critical_operations_jsonl, finish_critical_operation, format_critical_operations, list_critical_operations, replay_packet
from app.security.bot_rights import BotRights, format_bot_rights, format_rights_refresh_report, get_bot_rights, refresh_managed_group_rights
from app.security.managed_groups import get_managed_group, list_managed_groups, update_managed_group_title
from app.security.radio_drafts import (
    create_media_draft,
    create_text_draft,
    get_draft,
    is_draft_expired,
    mark_cancelled,
    mark_error,
    mark_sent,
)
from app.security.radio_templates import (
    create_template,
    delete_template,
    find_recent_duplicate,
    get_template,
    list_post_history,
    list_templates,
    message_hash,
    record_post_history,
)
from app.security.radio_schedules import (
    broadcast_template_to_managed_groups,
    create_schedule,
    delete_schedule,
    format_utc_offset,
    get_group_policy,
    is_quiet_now,
    list_schedules,
    parse_utc_offset_minutes,
    run_due_schedules,
    set_group_policy,
)
from app.security.private_panels import (
    cleanup_ephemeral_messages,
    remember_ephemeral,
    upsert_panel,
)
from app.security.alerts import send_security_alert
from app.security.monitor import run_once as run_security_check
from app.security.panic import get_security_reason, security_status, set_security_mode
from app.security.rate_limit import rate_limit_status
from app.security.task_registry import task_count, list_tasks
from app.security.signed_exports import SignedExport, create_signed_jsonl_export
from app.security.encrypted_exports import EncryptedSignedExport, EncryptionNotConfigured, create_encrypted_signed_export, keyring_public_summary
from app.security.session_store import acquire_operational_lock, cleanup_expired_operational_locks, cleanup_expired_private_sessions, list_operational_locks, list_private_sessions, release_operational_lock
from app.moderation_tigrao.state import (
    cleanup_expired_sessions as tigrao_cleanup_expired_sessions,
    clear_action,
    consume_if_expired,
    get_session,
    session_diagnostics as tigrao_session_diagnostics,
    set_action,
    set_selected_group,
    touch_session,
)
from app.btb.state import cleanup_expired_sessions as btb_cleanup_expired_sessions, session_diagnostics as btb_session_diagnostics
from app.moderation_tigrao.storage import get_group, list_groups, list_logs, log_action, remember_group
from app.moderation_tigrao.texts import delegate_home_text, entry_text, error_text, home_text, owner_home_text, radio_home_text, success_text

logger = logging.getLogger(__name__)

router = Router(name="moderation_tigrao")

RADIO_PAGE_SIZE = 8


def _format_session_diagnostics() -> str:
    tigrao = tigrao_session_diagnostics()
    btb = btb_session_diagnostics()
    persisted = list_private_sessions(limit=100)
    locks = list_operational_locks()
    lines = [
        "Sessões privadas — diagnóstico",
        "",
        f"Tigrão em memória: {tigrao.get('total', 0)}",
        f"BTB em memória: {btb.get('total', 0)}",
        f"Persistidas SQLite: {len(persisted)}",
        f"Locks operacionais: {len(locks)}",
        "",
        "Tigrão:",
    ]
    for row in tigrao.get("rows", [])[:20]:
        lines.append(
            f"- user={row.get('user_id')} grupo={row.get('selected_chat_id') or '-'} "
            f"ação={row.get('selected_action') or '-'} waiting={row.get('waiting_for') or '-'} "
            f"idle={row.get('idle_seconds')}s payload={','.join(row.get('payload_keys') or []) or '-'}"
        )
    if not tigrao.get("rows"):
        lines.append("- nenhuma sessão persistente")
    lines.append("")
    lines.append("BTB:")
    for row in btb.get("rows", [])[:20]:
        lines.append(
            f"- user={row.get('user_id')} grupo={row.get('group_id') or '-'} "
            f"alvo={row.get('target_username') or '-'} waiting={row.get('waiting_for') or '-'} "
            f"idle={row.get('idle_seconds')}s payload={','.join(row.get('payload_keys') or []) or '-'}"
        )
    if not btb.get("rows"):
        lines.append("- nenhuma sessão persistente")
    return "\n".join(lines)




async def _validate_group_access(bot, chat_id: int) -> tuple[str | None, str | None]:
    """Valida acesso ao grupo e atualiza cache/status de direitos reais.

    Fase 10E: seleção de grupo não exige admin total. Quando o bot não é
    administrador, o grupo pode ser selecionado, mas os botões de ações que
    exigem admin passam a aparecer como indisponíveis.
    """
    try:
        rights = await get_bot_rights(bot, chat_id, force_refresh=True)
    except Exception as exc:
        logger.warning(
            "TIGRAO_GROUP_ACCESS_CHECK_FAILED | chat_id=%s | %s: %s",
            chat_id, type(exc).__name__, exc,
        )
        return (None, " (permissão não verificada — siga com cautela)")

    if rights.error:
        if "TelegramForbiddenError" in rights.error:
            return (
                error_text(
                    "Bot removido do grupo",
                    "O bot não está mais nesse grupo.",
                    "Escolha outro grupo ou readicione o bot antes de prosseguir.",
                ),
                None,
            )
        if "TelegramBadRequest" in rights.error:
            return (
                error_text(
                    "Grupo inválido",
                    "O Telegram recusou consultar esse grupo.",
                    "Confira o chat_id e tente outro grupo.",
                ),
                None,
            )
        return (None, f" (direitos do bot não verificados: {rights.error})")

    if not rights.is_admin:
        return (
            None,
            f" (bot não é admin: status {rights.status}; ações administrativas ficam indisponíveis)",
        )

    missing: list[str] = []
    if not rights.can_delete_messages:
        missing.append("can_delete_messages")
    if not rights.can_restrict_members:
        missing.append("can_restrict_members")
    if not rights.can_pin_messages:
        missing.append("can_pin_messages")
    if missing:
        return (None, " (direitos parciais: sem " + ", ".join(missing) + ")")
    return (None, None)


ACTION_LABELS = {
    "ban": "Banir usuário",
    "unban": "Desbanir usuário",
    "mute": "Mutar usuário",
    "unmute": "Desmutar usuário",
    "approve": "Aprovar entrada",
    "reset": "Resetar entrada",
    "rmod_del_user_msg": "Apagar reaction de 1 pessoa (msg)",
    "rmod_del_user_chat": "Apagar reactions de 1 pessoa (grupo)",
    "rmod_del_all_msg": "Apagar TODAS reactions desta msg",
    "rmod_mute_react": "Silenciar reactor",
}
SIMPLE_EXECUTABLE_ACTIONS = {"ban", "unban", "unmute", "approve", "reset"}
TEXT_WAITING_STATES = {
    "chat_id", "outbound_text", "message_link", "user_id", "duration",
    "customize_title", "customize_bio",
    "rmod_link", "rmod_user",
    "moderator_grant", "moderator_revoke",
}

RADIO_TEXT_WAITING_STATES = {
    "outbound_text",
    "radio_template_body",
    "radio_schedule_body",
    "radio_quiet_policy",
    "radio_broadcast_template",
}
RADIO_MEDIA_WAITING_STATES = {"outbound_media"}



def _session_group_label() -> str:
    session = get_session()
    return group_display_name(session.selected_group_title)


def _group_label_for_chat(chat_id: int | str | None, fallback: str = "grupo selecionado") -> str:
    if chat_id is None:
        return fallback
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return fallback
    managed = get_managed_group(cid)
    if managed:
        return group_display_name(managed.get("title"), fallback)
    discovered = get_group(cid)
    if discovered:
        return group_display_name(discovered.get("title"), fallback)
    return fallback


def _group_panel_counts() -> tuple[list[dict], int, int]:
    managed = [g for g in list_managed_groups(limit=100) if int(g.get("enabled") or 0) == 1]
    managed_ids = {int(g["chat_id"]) for g in managed}
    discovered = [g for g in list_groups(limit=100) if int(g.get("chat_id")) not in managed_ids]
    # Inacessíveis são expostos apenas por diagnóstico técnico; aqui o número
    # é conservador para não inventar status sem refresh explícito.
    inaccessible_count = 0
    return managed, len(discovered), inaccessible_count


def _section_text(title: str, detail: str) -> str:
    session = get_session()
    selected = ""
    if session.selected_chat_id:
        selected = f"\n\nGrupo selecionado: {_session_group_label()}"
    return f"Tigrão — {title}\n\n{detail}{selected}\n\nEscolha uma opção pelos botões abaixo."


def _confirm_text() -> str:
    session = get_session()
    action_label = ACTION_LABELS.get(session.selected_action or "", session.selected_action or "ação")
    target_user_id = session.payload.get("target_user_id")
    duration_label = session.payload.get("duration_label")
    duration_line = f"Duração: {duration_label}\n" if duration_label else ""
    return (
        "Tigrão — confirmar ação\n\n"
        f"Grupo: {_session_group_label()}\n"
        f"Ação: {action_label}\n"
        f"Usuário: {target_user_id}\n"
        f"{duration_line}\n"
        "Confirme para prosseguir ou cancele para abandonar."
    )


def _execution_text(action: str, chat_id: int | str, target_user_id: int | str, payload: dict) -> str:
    action_label = ACTION_LABELS.get(action, action)
    duration_line = f"\nDuração: {payload.get('duration_label')}" if payload.get("duration_label") else ""
    return (
        "Tigrão — executando ação\n\n"
        f"Grupo: {_group_label_for_chat(chat_id)}\n"
        f"Ação: {action_label}\n"
        f"Usuário: {target_user_id}"
        f"{duration_line}\n\n"
        "Aguarde o retorno de conclusão ou erro."
    )


def _rmod_confirm_text() -> str:
    session = get_session()
    action = session.selected_action or ""
    action_label = ACTION_LABELS.get(action, action)
    p = session.payload
    lines = ["Tigrão — confirmar moderação de reactions", "", f"Ação: {action_label}"]
    if action == "rmod_del_user_msg":
        lines.append(f"Mensagem: {p.get('link_chat_id')} / {p.get('link_msg_id')}")
        lines.append(f"Alvo: {p.get('target_label')} ({p.get('target_user_id')})")
        lines.append("")
        lines.append("Vai apagar a reaction dessa pessoa NESSA mensagem (Telegram permite 1 reaction por user/msg).")
    elif action == "rmod_del_user_chat":
        lines.append(f"Grupo: {_session_group_label()}")
        lines.append(f"Alvo: {p.get('target_label')} ({p.get('target_user_id')})")
        lines.append("")
        lines.append("Vai apagar até 10000 reactions RECENTES dessa pessoa no GRUPO INTEIRO (todas mensagens).")
    elif action == "rmod_del_all_msg":
        lines.append(f"Mensagem: {p.get('link_chat_id')} / {p.get('link_msg_id')}")
        lines.append("")
        lines.append("Atenção: vai remover TODAS as reactions desta mensagem, inclusive as do próprio bot.")
    elif action == "rmod_mute_react":
        lines.append(f"Grupo: {_session_group_label()}")
        lines.append(f"Alvo: {p.get('target_label')} ({p.get('target_user_id')})")
        lines.append(f"Duração: {p.get('duration_label')}")
        lines.append("")
        lines.append("Apenas a permissão de reagir será alterada. Outras permissões serão preservadas.")
    lines.append("")
    lines.append("Confirme para prosseguir ou cancele para abandonar.")
    return "\n".join(lines)


def _logs_text() -> str:
    rows = list_logs(10)
    if not rows:
        return "Tigrão — logs\n\nNenhum registro encontrado."
    lines = ["Tigrão — logs", "", "Últimos registros:"]
    for row in rows:
        status = row.get("status") or "-"
        action = row.get("action") or "-"
        chat_id = row.get("chat_id") or "-"
        target = row.get("target_user_id") or "-"
        created_at = row.get("created_at") or "-"
        error_type = row.get("error_type")
        line = f"#{row.get('id')} | {status} | {action} | grupo {chat_id} | alvo {target} | {created_at}"
        if error_type:
            line += f" | erro {error_type}"
        lines.append(line)
    return "\n".join(lines)


def _security_text() -> str:
    status = security_status()
    rate = rate_limit_status()
    tasks = list_tasks()
    reason = get_security_reason() or "-"
    lines = [
        "Tigrão — segurança",
        "",
        f"Modo: {status.get('mode')}",
        f"Motivo: {reason}",
        f"Panic stop habilitado: {status.get('panic_stop_server')}",
        f"Rate limit: {'ativo' if rate.get('enabled') else 'inativo'} ({rate.get('buckets')} buckets)",
        f"Tasks em background: {task_count()}",
    ]
    signals = status.get("signals") or {}
    if signals:
        lines.append("")
        lines.append("Sinais recentes:")
        for name, count in list(dict(signals).items())[:8]:
            lines.append(f"- {name}: {count}")
    if tasks:
        lines.append("")
        lines.append("Tasks:")
        for row in tasks[:5]:
            lines.append(f"- {row.get('name')} · {row.get('age_seconds', 0):.1f}s")
    lines.append("")
    lines.append("Ações de segurança são Owner-only.")
    return "\n".join(lines)


def _audit_events_text() -> str:
    rows = list_audit_events(limit=10)
    if not rows:
        return "Tigrão — audit log\n\nNenhum evento registrado."
    lines = ["Tigrão — audit log", "", "Últimos eventos:"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} | {row.get('category')}:{row.get('action')} | {row.get('status')} | "
            f"ator {row.get('actor_user_id') or '-'} | grupo {row.get('chat_id') or '-'}"
        )
        if row.get("reason"):
            reason = str(row.get("reason"))
            if len(reason) > 120:
                reason = reason[:117] + "..."
            lines.append(f"  motivo: {reason}")
    return "\n".join(lines)


def _moderators_text() -> str:
    session = get_session()
    if not session.selected_chat_id:
        return error_text(
            "Nenhum grupo selecionado",
            "Escolha um grupo antes de gerenciar moderadores.",
            "Use Escolher grupo e volte para Moderadores.",
        )
    rows = list_active_chat_grants(int(session.selected_chat_id))
    lines = [
        "Tigrão — moderadores",
        "",
        f"Grupo: {_session_group_label()}",
        "",
    ]
    if not rows:
        lines.append("Nenhum grant ativo neste grupo.")
    else:
        lines.append("Grants ativos:")
        for row in rows[:40]:
            lines.append(f"- {row['user_id']}: {row['permission']}")
        if len(rows) > 40:
            lines.append(f"... +{len(rows) - 40} grants")
    lines.extend([
        "",
        "Conceder: envie user_id permission, user_id *:mod, user_id *:radio ou user_id *:all.",
        "Compatibilidade: user_id * concede/revoga pacote completo de moderação.",
        "Permissões radio.* liberam partes do painel /radio sem liberar /owner.",
        "Permissões Owner-only não podem ser delegadas.",
    ])
    return "\n".join(lines)


def _parse_moderator_permission_input(raw: str) -> tuple[int, list[str]]:
    parts = (raw or "").split()
    if len(parts) != 2:
        raise ValueError("Use: user_id permission  — ou: user_id *:mod / *:radio / *:all")
    user_id = parse_user_id(parts[0])
    token = parts[1].strip()
    if token == "*":
        return user_id, list(moderation_full_permissions())
    if token == "*:mod":
        return user_id, list(moderation_full_permissions())
    if token == "*:radio":
        return user_id, list(radio_full_permissions())
    if token == "*:all":
        return user_id, list(DELEGABLE_GRANT_PERMISSIONS)
    if token not in DELEGABLE_GRANT_PERMISSIONS:
        raise ValueError(f"Permissão não delegável ou desconhecida: {token}")
    return user_id, [token]


async def _sync_target_commands_after_rbac(bot, *, actor_user_id: int, target_user_id: int, chat_id: int, action: str) -> dict[str, object]:
    """Sincroniza menu nativo após grant/revoke sem bloquear RBAC.

    O menu do Telegram é UX; a autorização verdadeira continua no banco.
    """
    try:
        result = await sync_user_command_scope(bot, target_user_id)
        log_audit_event(
            category="commands",
            action=f"sync_after_{action}",
            status="success" if result.get("ok") else "error",
            actor_user_id=actor_user_id,
            chat_id=chat_id,
            target_user_id=target_user_id,
            payload=result,
        )
        return result
    except Exception as exc:
        logger.warning(
            "COMMAND_SCOPE_SYNC_AFTER_RBAC_FAILED | action=%s | target_user_id=%s | %s: %s",
            action,
            target_user_id,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        try:
            log_audit_event(
                category="commands",
                action=f"sync_after_{action}",
                status="error",
                actor_user_id=actor_user_id,
                chat_id=chat_id,
                target_user_id=target_user_id,
                reason=type(exc).__name__,
                payload={"error": str(exc)[:1000]},
            )
        except Exception:
            logger.debug("COMMAND_SCOPE_SYNC_AUDIT_FAILED", exc_info=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "user_id": target_user_id}


async def _edit_private_panel(callback: CallbackQuery, text: str, reply_markup) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
            upsert_panel(
                actor_user_id=callback.from_user.id,
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                panel_type="tigrao",
            )
        except Exception:
            sent = await callback.message.answer(text, reply_markup=reply_markup)
            upsert_panel(
                actor_user_id=callback.from_user.id,
                chat_id=sent.chat.id,
                message_id=sent.message_id,
                panel_type="tigrao",
            )
    await callback.answer()


async def _send_or_update_entry_panel(message: Message) -> None:
    if not message.from_user:
        return
    await cleanup_ephemeral_messages(message.bot, message.from_user.id)
    user_id = message.from_user.id
    is_root = is_root_user(user_id)
    can_delegate = is_moderator_user(user_id)
    can_radio = is_root or has_any_radio_permission(message.from_user.id)
    sent = await message.answer(
        entry_text(is_root=is_root, can_delegate=can_delegate, can_radio=can_radio),
        reply_markup=entry_keyboard(is_root=is_root, can_delegate=can_delegate, can_radio=can_radio),
    )
    upsert_panel(
        actor_user_id=user_id,
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        panel_type="tigrao_entry",
    )


async def _send_or_update_owner_panel(message: Message) -> None:
    if not message.from_user or not is_root_user(message.from_user.id):
        return
    await cleanup_ephemeral_messages(message.bot, message.from_user.id)
    sent = await message.answer(owner_home_text(), reply_markup=owner_home_keyboard())
    upsert_panel(
        actor_user_id=message.from_user.id,
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        panel_type="owner",
    )


async def _send_or_update_radio_panel(message: Message) -> None:
    if not message.from_user or not _actor_can_open_radio(message.from_user.id):
        return
    await cleanup_ephemeral_messages(message.bot, message.from_user.id)
    sent = await message.answer(radio_home_text(), reply_markup=await _radio_keyboard_for_actor_async(message.bot, message.from_user.id))
    upsert_panel(
        actor_user_id=message.from_user.id,
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        panel_type="radio",
    )


async def _send_or_update_home_panel(message: Message) -> None:
    """Compatibilidade: mantém o nome antigo como painel Owner."""
    await _send_or_update_owner_panel(message)

async def _remember_ephemeral_message(message: Message, reason: str, actor_user_id: int | None = None) -> None:
    owner_id = actor_user_id or (message.from_user.id if message.from_user else None)
    if owner_id is not None:
        remember_ephemeral(
            actor_user_id=owner_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reason=reason,
        )


async def _delete_private_input(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        await _remember_ephemeral_message(message, "private_input_cleanup")


def _need_group_text() -> str:
    return error_text(
        "Nenhum grupo selecionado",
        "Você precisa escolher o grupo antes de usar esta ação.",
        "Toque em Escolher grupo e selecione ou digite o chat_id.",
    )


def _is_root_callback(callback: CallbackQuery) -> bool:
    return bool(callback.from_user and is_root_user(callback.from_user.id))


def _actor_can_open_radio(user_id: int | None) -> bool:
    return bool(user_id and (is_root_user(user_id) or has_any_radio_permission(user_id)))


def _radio_selected_chat_id() -> int | None:
    chat_id = get_session().selected_chat_id
    return int(chat_id) if chat_id is not None else None


def _bot_capabilities_from_rights(rights: BotRights | None) -> set[str]:
    if rights is None or not rights.is_admin:
        return set()
    caps: set[str] = {"admin"}
    if rights.can_delete_messages:
        caps.add("delete")
    if rights.can_restrict_members:
        caps.add("restrict")
    if rights.can_pin_messages:
        caps.add("pin")
    if rights.can_manage_tags:
        caps.add("tags")
    if rights.can_change_info:
        caps.add("change_info")
    if rights.can_invite_users:
        caps.add("invite")
    if rights.can_manage_topics:
        caps.add("topics")
    return caps


def _bot_rights_summary(rights: BotRights | None) -> str:
    if rights is None:
        return "Direitos do bot: nenhum grupo selecionado."
    if rights.error:
        return f"Direitos do bot: não verificados ({rights.error})."
    if not rights.is_admin:
        return f"Direitos do bot: status {rights.status}; ações administrativas indisponíveis."
    caps = _bot_capabilities_from_rights(rights)
    labels = []
    for cap, label in (
        ("delete", "apagar"),
        ("restrict", "ban/mute"),
        ("pin", "fixar"),
        ("tags", "tags"),
        ("change_info", "governança"),
        ("invite", "convites"),
    ):
        if cap in caps:
            labels.append(label)
    return "Direitos do bot: " + (", ".join(labels) if labels else "admin sem poderes relevantes")


async def _selected_bot_rights(bot) -> BotRights | None:
    chat_id = get_session().selected_chat_id
    if chat_id is None:
        return None
    try:
        return await get_bot_rights(bot, int(chat_id))
    except Exception as exc:
        logger.warning("BOT_RIGHTS_PANEL_LOOKUP_FAILED | chat_id=%s | %s: %s", chat_id, type(exc).__name__, exc)
        return None


async def _selected_bot_capabilities(bot) -> set[str] | None:
    rights = await _selected_bot_rights(bot)
    if rights is None:
        return None
    return _bot_capabilities_from_rights(rights)


async def _rights_aware_section_text(bot, title: str, detail: str) -> str:
    rights = await _selected_bot_rights(bot)
    return _section_text(title, detail) + "\n\n" + _bot_rights_summary(rights)


async def _radio_keyboard_for_actor_async(bot, user_id: int | None):
    return radio_keyboard(
        allowed_permissions=_radio_allowed_permissions(user_id),
        is_root=is_root_user(user_id),
        has_selected_chat=_radio_selected_chat_id() is not None,
        bot_capabilities=await _selected_bot_capabilities(bot),
    )


def _capability_label(capability: str) -> str:
    return {
        "admin": "bot precisa ser administrador",
        "delete": "can_delete_messages",
        "restrict": "can_restrict_members",
        "pin": "can_pin_messages",
        "tags": "can_manage_tags",
        "change_info": "can_change_info",
        "invite": "can_invite_users",
        "topics": "can_manage_topics",
    }.get(capability, capability)


def _actor_can_radio_permission(user_id: int | None, permission: str, chat_id: int | None = None) -> bool:
    if is_root_user(user_id):
        return True
    if not user_id or permission not in RADIO_GRANT_PERMISSIONS:
        return False
    if chat_id is None:
        return False
    return has_permission(user_id, chat_id, permission)


def _radio_permission_for_draft(kind: str, *, pin: bool) -> str:
    if pin:
        return "radio.pin"
    if kind == "media":
        return "radio.post_media"
    return "radio.post_text"


def _callback_can_use_radio(callback: CallbackQuery, permission: str | None = None, *, require_chat: bool = False) -> bool:
    user_id = callback.from_user.id if callback.from_user else None
    if not _actor_can_open_radio(user_id):
        return False
    if permission is None:
        return True
    chat_id = _radio_selected_chat_id()
    if require_chat and chat_id is None:
        return False
    return _actor_can_radio_permission(user_id, permission, chat_id)


def _radio_allowed_permissions(user_id: int | None) -> set[str]:
    if is_root_user(user_id):
        return set(RADIO_GRANT_PERMISSIONS)
    chat_id = _radio_selected_chat_id()
    if not user_id or chat_id is None:
        return set()
    return {permission for permission in RADIO_GRANT_PERMISSIONS if has_permission(user_id, chat_id, permission)}


def _radio_keyboard_for_actor(user_id: int | None):
    return radio_keyboard(
        allowed_permissions=_radio_allowed_permissions(user_id),
        is_root=is_root_user(user_id),
        has_selected_chat=_radio_selected_chat_id() is not None,
    )


def _radio_template_page_rows(page: int) -> tuple[list[dict], bool]:
    rows = list_templates(limit=RADIO_PAGE_SIZE + 1, offset=page * RADIO_PAGE_SIZE)
    return rows[:RADIO_PAGE_SIZE], len(rows) > RADIO_PAGE_SIZE


def _radio_history_page_rows(chat_id: int | None, page: int) -> tuple[list[dict], bool]:
    rows = list_post_history(chat_id=chat_id, limit=RADIO_PAGE_SIZE + 1, offset=page * RADIO_PAGE_SIZE)
    return rows[:RADIO_PAGE_SIZE], len(rows) > RADIO_PAGE_SIZE


def _radio_schedule_page_rows(chat_id: int | None, page: int) -> tuple[list[dict], bool]:
    rows = list_schedules(chat_id=chat_id, limit=RADIO_PAGE_SIZE + 1, offset=page * RADIO_PAGE_SIZE)
    return rows[:RADIO_PAGE_SIZE], len(rows) > RADIO_PAGE_SIZE


async def _answer_bad_callback(callback: CallbackQuery, exc: Exception) -> None:
    try:
        log_audit_event(
            category="callback",
            action="parse_error",
            status="blocked",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"data": callback.data, "error": str(exc)},
        )
    except Exception:
        logger.exception("CALLBACK_PARSE_AUDIT_FAILED")
    await callback.answer("Callback inválido ou expirado.", show_alert=True)


def _radio_broadcast_allowed_chat_ids(user_id: int | None) -> list[int] | None:
    """Retorna None para Owner (todos os grupos gerenciados) ou lista restrita.

    Delegados com `radio.broadcast` só enviam para grupos onde possuem esse
    grant explícito. Isso evita que uma permissão em um grupo permita broadcast
    global acidental.
    """
    if is_root_user(user_id):
        return None
    if not user_id:
        return []
    chat_ids: list[int] = []
    for group in list_managed_groups(limit=500):
        try:
            chat_id = int(group["chat_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if int(group.get("enabled") or 0) != 1:
            continue
        if has_permission(user_id, chat_id, "radio.broadcast"):
            chat_ids.append(chat_id)
    return chat_ids


def _callback_can_broadcast_radio(callback: CallbackQuery) -> bool:
    user_id = callback.from_user.id if callback.from_user else None
    allowed = _radio_broadcast_allowed_chat_ids(user_id)
    return allowed is None or bool(allowed)


async def _edit_radio_panel(callback: CallbackQuery, text: str, reply_markup) -> None:
    if not _callback_can_use_radio(callback):
        await callback.answer("Sem permissão para abrir o Radio.", show_alert=True)
        return
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
            upsert_panel(
                actor_user_id=callback.from_user.id,
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                panel_type="radio",
            )
        except Exception:
            sent = await callback.message.answer(text, reply_markup=reply_markup)
            upsert_panel(
                actor_user_id=callback.from_user.id,
                chat_id=sent.chat.id,
                message_id=sent.message_id,
                panel_type="radio",
            )
    await callback.answer()


def _radio_access_denied_text(permission: str) -> str:
    return error_text(
        "Permissão Radio ausente",
        f"Esta ação exige {permission} no grupo selecionado.",
        "Peça ao Owner para conceder a permissão no painel Moderadores.",
    )


def _governance_summary(action: str, chat_id: int, payload: dict) -> str:
    if action == "governance_set_title":
        return f"Grupo: {_group_label_for_chat(chat_id)}\nAção: alterar nome\nNovo nome: {payload.get('title', '')}"
    if action == "governance_set_description":
        desc = str(payload.get("description", ""))
        preview = "(apagar descrição)" if desc.strip() == "." else f"{len(desc)} caracteres"
        return f"Grupo: {_group_label_for_chat(chat_id)}\nAção: alterar descrição\nConteúdo: {preview}"
    if action == "governance_link_direct":
        return f"Grupo: {_group_label_for_chat(chat_id)}\nAção: gerar link direto de convite"
    if action == "governance_link_approval":
        return f"Grupo: {_group_label_for_chat(chat_id)}\nAção: gerar link com aprovação"
    return f"Grupo: {_group_label_for_chat(chat_id)}\nAção: {action}"


def _prepare_governance_confirmation(action: str, chat_id: int, payload: dict) -> None:
    set_action(action, waiting_for="governance_confirm", **payload)


def _audit_governance(
    *,
    action: str,
    status: str,
    actor_user_id: int | None,
    chat_id: int,
    reason: str | None = None,
    payload: dict | None = None,
) -> None:
    try:
        log_audit_event(
            category="governance",
            action=action,
            status=status,
            actor_user_id=actor_user_id,
            chat_id=chat_id,
            reason=reason,
            payload=payload or {},
        )
    except Exception:
        logger.exception("TIGRAO_GOVERNANCE_AUDIT_FAILED | action=%s | chat_id=%s", action, chat_id)


def _governance_lock_name(chat_id: int, action: str) -> str:
    return f"governance:{int(chat_id)}:{str(action)}"



def _radio_preview_text(draft: dict) -> str:
    kind = str(draft.get("kind") or "")
    target_chat_id = int(draft.get("target_chat_id"))
    pin = bool(int(draft.get("pin") or 0))
    expires_at = str(draft.get("expires_at") or "")
    draft_id = str(draft.get("id") or "")
    if kind == "text":
        text_value = str(draft.get("text") or "")
        preview = text_value if len(text_value) <= 900 else text_value[:897] + "..."
        preview = html.escape(preview)
        kind_label = "texto"
        content = f"Prévia do texto:\n<blockquote>{preview}</blockquote>"
    else:
        kind_label = "mídia"
        content = "Prévia da mídia recebida no privado do bot."
    return (
        "Radio — prévia de rascunho\n\n"
        f"Rascunho: {draft_id[:8]}\n"
        f"Tipo: {kind_label}\n"
        f"Grupo destino: {_group_label_for_chat(target_chat_id)}\n"
        f"Fixar: {'sim' if pin else 'não'}\n"
        f"Expira em: {expires_at}\n\n"
        f"{content}\n\n"
        "Confirme para publicar no grupo ou cancele para descartar."
    )


def _radio_current_draft_id() -> str | None:
    draft_id = get_session().payload.get("radio_draft_id")
    return str(draft_id) if draft_id else None


def _radio_template_preview(template: dict) -> str:
    body = str(template.get("body") or "")
    preview = body[:900]
    if len(body) > 900:
        preview += "\n..."
    return (
        "Radio — template\n\n"
        f"ID: {template.get('id')}\n"
        f"Nome: {html.escape(str(template.get('name') or 'sem nome'))}\n\n"
        "<blockquote>"
        f"{html.escape(preview)}"
        "</blockquote>"
    )


def _radio_history_text(chat_id: int | None = None, *, page: int = 0, rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else list_post_history(chat_id=chat_id, limit=RADIO_PAGE_SIZE, offset=page * RADIO_PAGE_SIZE)
    scope = _group_label_for_chat(chat_id) if chat_id is not None else "todos os grupos"
    if not rows:
        return f"Radio — histórico\n\nSem postagens registradas na página {page + 1} para {scope}."
    lines = [f"Radio — histórico\n\nPágina {page + 1}. Últimas postagens para {scope}:"]
    for row in rows:
        pin = "fixado" if int(row.get("pin") or 0) else "não fixado"
        template = f" template={row.get('template_id')}" if row.get("template_id") else ""
        msg = f" msg={row.get('telegram_message_id')}" if row.get("telegram_message_id") else ""
        reason = f" / {row.get('reason')}" if row.get("reason") else ""
        lines.append(
            f"- {row.get('created_at')} — {row.get('kind')} {pin}{template}{msg} — {row.get('status')}{reason}"
        )
    return "\n".join(lines)


def _radio_schedules_text(chat_id: int | None = None, *, page: int = 0, rows: list[dict] | None = None) -> str:
    schedules = rows if rows is not None else list_schedules(chat_id=chat_id, limit=RADIO_PAGE_SIZE, offset=page * RADIO_PAGE_SIZE)
    scope = _group_label_for_chat(chat_id) if chat_id is not None else "todos os grupos"
    if not schedules:
        return (
            "Radio — agendamentos\n\n"
            f"Nenhum agendamento encontrado na página {page + 1} para {scope}.\n\n"
            "Para criar, selecione um grupo e use: template_id intervalo_min pin(0/1)."
        )
    lines = [f"Radio — agendamentos\n\nPágina {page + 1}. Últimos agendamentos para {scope}:"]
    for row in schedules:
        status = "ativo" if int(row.get("enabled") or 0) else "desativado"
        pin = "fixado" if int(row.get("pin") or 0) else "não fixado"
        minutes = int(row.get("interval_seconds") or 0) // 60
        lines.append(
            f"- id={row.get('id')} template={row.get('template_id')} "
            f"{status}, {pin}, a cada {minutes} min, próximo={row.get('next_due_at')}, último={row.get('last_status') or '-'}"
        )
    return "\n".join(lines)


def _radio_quiet_text(chat_id: int | None) -> str:
    if chat_id is None:
        return "Radio — janela de silêncio\n\nSelecione um grupo antes de configurar janela de silêncio."
    policy = get_group_policy(chat_id)
    if not policy or not policy.get("quiet_from") or not policy.get("quiet_to"):
        return (
            "Radio — janela de silêncio\n\n"
            f"Grupo: {_group_label_for_chat(chat_id)}\n"
            "Nenhuma janela configurada.\n\n"
            "Formato: HH:MM-HH:MM +00:00\n"
            "Exemplo: 23:00-08:00 -03:00"
        )
    offset = format_utc_offset(int(policy.get("utc_offset_minutes") or 0))
    active = "sim" if is_quiet_now(chat_id) else "não"
    return (
        "Radio — janela de silêncio\n\n"
        f"Grupo: {_group_label_for_chat(chat_id)}\n"
        f"Janela: {policy.get('quiet_from')}-{policy.get('quiet_to')} {offset}\n"
        f"Ativa agora: {active}"
    )


def _parse_schedule_input(raw: str) -> tuple[int, int, bool]:
    parts = str(raw or "").strip().split()
    if len(parts) not in {2, 3}:
        raise ValueError("use: template_id intervalo_min pin(0/1)")
    template_id = int(parts[0])
    interval_minutes = int(parts[1])
    pin = bool(int(parts[2])) if len(parts) == 3 else False
    if interval_minutes < 1:
        raise ValueError("intervalo mínimo: 1 minuto")
    return template_id, interval_minutes * 60, pin


def _parse_quiet_input(raw: str) -> tuple[str | None, str | None, int]:
    text = str(raw or "").strip()
    if text.lower() in {"off", "desativar", "desligar", "0"}:
        return None, None, 0
    parts = text.split()
    if not parts:
        raise ValueError("use HH:MM-HH:MM +00:00 ou off")
    interval = parts[0]
    if "-" not in interval:
        raise ValueError("janela deve ser HH:MM-HH:MM")
    quiet_from, quiet_to = interval.split("-", 1)
    offset = parse_utc_offset_minutes(parts[1]) if len(parts) > 1 else 0
    return quiet_from, quiet_to, offset


def _radio_draft_hash(draft: dict) -> str:
    if draft.get("kind") == "text":
        return message_hash(str(draft.get("text") or ""))
    return message_hash(f"media:{draft.get('source_chat_id')}:{draft.get('source_message_id')}:{int(draft.get('pin') or 0)}")


async def _radio_answer_draft_preview(message: Message, draft_id: str, *, reason: str) -> None:
    draft = get_draft(draft_id)
    if not draft:
        clear_action()
        await message.answer(error_text("Rascunho não encontrado", "Não consegui recuperar o rascunho criado.", "Abra /radio e tente novamente."), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
        return
    set_action("radio_confirm_draft", radio_draft_id=draft_id)
    try:
        log_audit_event(
            category="radio",
            action="draft_created",
            status="success",
            actor_user_id=message.from_user.id if message.from_user else None,
            chat_id=int(draft["target_chat_id"]),
            payload={
                "draft_id": draft_id,
                "kind": draft.get("kind"),
                "pin": bool(int(draft.get("pin") or 0)),
                "reason": reason,
            },
        )
    except Exception:
        logger.exception("RADIO_DRAFT_AUDIT_FAILED draft=%s", draft_id)
    sent = await message.answer(_radio_preview_text(draft), reply_markup=radio_draft_confirm_keyboard())
    if message.from_user:
        await _remember_ephemeral_message(sent, "radio_draft_preview", actor_user_id=message.from_user.id)


async def _radio_execute_draft(bot, draft: dict) -> int:
    target = int(draft["target_chat_id"])
    pin = bool(int(draft.get("pin") or 0))
    if draft.get("kind") == "text":
        sent = await _with_telegram_retry(
            lambda: bot.send_message(chat_id=target, text=str(draft.get("text") or "")),
            label="radio_send_text_draft",
        )
        if pin:
            await _with_telegram_retry(
                lambda: bot.pin_chat_message(
                    chat_id=target,
                    message_id=sent.message_id,
                    disable_notification=True,
                ),
                label="radio_pin_text_draft",
            )
        return int(sent.message_id)
    copied_id = await copy_message(
        bot,
        target_chat_id=target,
        from_chat_id=int(draft["source_chat_id"]),
        message_id=int(draft["source_message_id"]),
        pin=pin,
    )
    return int(copied_id)



def _is_owner_waiting_text(message: Message) -> bool:
    if is_owner_private_message(message) and get_session().waiting_for in TEXT_WAITING_STATES:
        return True
    return bool(
        message.chat.type == "private"
        and message.from_user
        and _actor_can_open_radio(message.from_user.id)
        and get_session().waiting_for in RADIO_TEXT_WAITING_STATES
    )


def _is_owner_waiting_media(message: Message) -> bool:
    if is_owner_private_message(message) and get_session().waiting_for == "outbound_media":
        return True
    return bool(
        message.chat.type == "private"
        and message.from_user
        and _actor_can_open_radio(message.from_user.id)
        and get_session().waiting_for in RADIO_MEDIA_WAITING_STATES
    )


async def _execute_simple_action(bot, action: str, chat_id: int, user_id: int, payload: dict) -> str | None:
    if action == "ban":
        await ban_user(bot, chat_id, user_id)
        return None
    if action == "unban":
        await unban_user(bot, chat_id, user_id)
        return None
    if action == "unmute":
        await unmute_user(bot, chat_id, user_id)
        return None
    if action == "mute":
        await mute_user(bot, chat_id, user_id, payload["duration"])
        return None
    if action == "approve":
        await approve_join_request(bot, chat_id, user_id)
        return None
    if action == "reset":
        return await reset_entry(bot, chat_id, user_id)
    raise ValueError(f"ação ainda não executável: {action}")


@router.message(Command("tigrao"))
async def tigrao_entry(message: Message) -> None:
    if not (message.chat.type == "private" and message.from_user and is_moderator_user(message.from_user.id)):
        return
    await _send_or_update_entry_panel(message)


@router.message(Command("owner"))
async def owner_home(message: Message) -> None:
    if not (message.chat.type == "private" and message.from_user and is_root_user(message.from_user.id)):
        return
    await _send_or_update_owner_panel(message)


@router.message(Command("radio"))
async def radio_home(message: Message) -> None:
    if not (message.chat.type == "private" and message.from_user and _actor_can_open_radio(message.from_user.id)):
        return
    await _send_or_update_radio_panel(message)


@router.message(F.text, _is_owner_waiting_text)
async def tigrao_private_text(message: Message) -> None:
    # Sprint 7 (T01): se o fluxo waiting expirou (>15min sem atividade),
    # limpa o estado e avisa em vez de processar input antigo.
    if consume_if_expired():
        await message.answer(
            error_text(
                "Sessão expirada",
                "O fluxo anterior expirou por inatividade (15 min).",
                "Use /tigrao para abrir o painel novamente.",
            )
        )
        return

    session = get_session()

    if session.waiting_for in {"moderator_grant", "moderator_revoke"}:
        if not message.from_user or not is_root_user(message.from_user.id):
            await message.answer(error_text("Acesso negado", "Somente o Owner pode gerenciar moderadores.", "Use o painel com uma conta Owner."))
            return
        if not session.selected_chat_id:
            clear_action()
            await message.answer(_need_group_text(), reply_markup=home_keyboard())
            return
        try:
            target_user_id, permissions = _parse_moderator_permission_input(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Entrada inválida", str(exc), "Use o formato indicado no painel."), reply_markup=moderators_keyboard())
            return
        if is_root_user(target_user_id):
            await message.answer(error_text("Operação bloqueada", "O Owner não recebe nem perde grants por painel.", "Escolha outro usuário."), reply_markup=moderators_keyboard())
            return
        chat_id = int(session.selected_chat_id)
        if session.waiting_for == "moderator_grant":
            grant_permissions(
                user_id=target_user_id,
                chat_id=chat_id,
                permissions=permissions,
                granted_by_user_id=message.from_user.id,
                notes="panel:moderators",
            )
            log_audit_event(
                category="rbac",
                action="panel_grant",
                status="success",
                actor_user_id=message.from_user.id,
                chat_id=chat_id,
                target_user_id=target_user_id,
                payload={"permissions": permissions},
            )
            action_label = "concedidas"
        else:
            revoke_permissions(user_id=target_user_id, chat_id=chat_id, permissions=permissions)
            log_audit_event(
                category="rbac",
                action="panel_revoke",
                status="success",
                actor_user_id=message.from_user.id,
                chat_id=chat_id,
                target_user_id=target_user_id,
                payload={"permissions": permissions},
            )
            action_label = "revogadas"
        sync_result = await _sync_target_commands_after_rbac(
            message.bot,
            actor_user_id=message.from_user.id,
            target_user_id=target_user_id,
            chat_id=chat_id,
            action="grant" if action_label == "concedidas" else "revoke",
        )
        await _delete_private_input(message)
        clear_action()
        sync_line = "ok" if sync_result.get("ok") else "falhou"
        sent = await message.answer(
            success_text(
                "Moderador atualizado",
                f"Grupo: {_group_label_for_chat(chat_id)}\nUsuário: {target_user_id}\nPermissões {action_label}: {', '.join(permissions)}\nMenu nativo: {sync_line}",
            ),
            reply_markup=moderators_keyboard(),
        )
        await _remember_ephemeral_message(sent, "moderator_grant_result", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "radio_template_body":
        if not message.from_user or not _actor_can_radio_permission(message.from_user.id, "radio.templates.manage", session.selected_chat_id):
            await message.answer(error_text("Acesso negado", "Sem permissão radio.templates.manage para criar templates.", "Peça ao Owner para conceder acesso no grupo selecionado."))
            return
        raw = message.text or ""
        if "\n" not in raw.strip():
            await message.answer(
                error_text(
                    "Template inválido",
                    "Envie no formato: nome na primeira linha e conteúdo nas linhas seguintes.",
                    "Exemplo:\nAviso\nTexto do aviso para o grupo.",
                ),
                reply_markup=radio_templates_keyboard(list_templates()),
            )
            return
        name, body = raw.split("\n", 1)
        try:
            template_id = create_template(name=name, body=body, created_by_user_id=message.from_user.id)
        except ValueError as exc:
            await message.answer(error_text("Template inválido", str(exc), "Ajuste nome/conteúdo e tente novamente."), reply_markup=radio_templates_keyboard(list_templates()))
            return
        await _delete_private_input(message)
        clear_action()
        try:
            log_audit_event(
                category="radio",
                action="template_create",
                status="success",
                actor_user_id=message.from_user.id,
                payload={"template_id": template_id, "name": name.strip()},
            )
        except Exception:
            logger.exception("RADIO_TEMPLATE_CREATE_AUDIT_FAILED template=%s", template_id)
        sent = await message.answer(
            success_text("Template criado", f"ID: {template_id}\nNome: {name.strip()}"),
            reply_markup=radio_templates_keyboard(list_templates()),
        )
        await _remember_ephemeral_message(sent, "radio_template_created", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "radio_schedule_body":
        if not message.from_user or not _actor_can_radio_permission(message.from_user.id, "radio.schedule", session.selected_chat_id):
            await message.answer(error_text("Acesso negado", "Sem permissão radio.schedule para criar agendamentos.", "Peça ao Owner para conceder acesso no grupo selecionado."))
            return
        if not session.selected_chat_id:
            await message.answer(_need_group_text(), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        try:
            template_id, interval_seconds, pin = _parse_schedule_input(message.text or "")
            schedule_id = create_schedule(
                template_id=template_id,
                chat_id=int(session.selected_chat_id),
                interval_seconds=interval_seconds,
                created_by_user_id=message.from_user.id,
                pin=pin,
            )
        except Exception as exc:
            await message.answer(
                error_text(
                    "Agendamento inválido",
                    str(exc),
                    "Use: template_id intervalo_min pin(0/1). Exemplo: 5 120 0",
                ),
                reply_markup=radio_schedules_keyboard(),
            )
            return
        await _delete_private_input(message)
        clear_action()
        try:
            log_audit_event(
                category="radio",
                action="schedule_create",
                status="success",
                actor_user_id=message.from_user.id,
                chat_id=int(session.selected_chat_id),
                payload={"schedule_id": schedule_id, "template_id": template_id, "pin": pin},
            )
        except Exception:
            logger.exception("RADIO_SCHEDULE_CREATE_AUDIT_FAILED schedule=%s", schedule_id)
        sent = await message.answer(
            success_text(
                "Agendamento criado",
                f"ID: {schedule_id}\nGrupo: {_session_group_label()}\nTemplate: {template_id}\nIntervalo: {interval_seconds // 60} min\nFixar: {'sim' if pin else 'não'}",
            ),
            reply_markup=radio_schedules_keyboard(),
        )
        await _remember_ephemeral_message(sent, "radio_schedule_created", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "radio_quiet_policy":
        if not message.from_user or not _actor_can_radio_permission(message.from_user.id, "radio.quiet_hours.manage", session.selected_chat_id):
            await message.answer(error_text("Acesso negado", "Sem permissão radio.quiet_hours.manage para janela de silêncio.", "Peça ao Owner para conceder acesso no grupo selecionado."))
            return
        if not session.selected_chat_id:
            await message.answer(_need_group_text(), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        try:
            quiet_from, quiet_to, offset = _parse_quiet_input(message.text or "")
            set_group_policy(
                chat_id=int(session.selected_chat_id),
                quiet_from=quiet_from,
                quiet_to=quiet_to,
                utc_offset_minutes=offset,
                updated_by_user_id=message.from_user.id,
            )
        except Exception as exc:
            await message.answer(
                error_text(
                    "Janela inválida",
                    str(exc),
                    "Use HH:MM-HH:MM +00:00 ou off. Exemplo: 23:00-08:00 -03:00",
                ),
                reply_markup=radio_quiet_keyboard(),
            )
            return
        await _delete_private_input(message)
        clear_action()
        try:
            log_audit_event(
                category="radio",
                action="quiet_hours_update",
                status="success",
                actor_user_id=message.from_user.id,
                chat_id=int(session.selected_chat_id),
                payload={"quiet_from": quiet_from, "quiet_to": quiet_to, "utc_offset_minutes": offset},
            )
        except Exception:
            logger.exception("RADIO_QUIET_AUDIT_FAILED chat=%s", session.selected_chat_id)
        sent = await message.answer(_radio_quiet_text(int(session.selected_chat_id)), reply_markup=radio_quiet_keyboard())
        await _remember_ephemeral_message(sent, "radio_quiet_updated", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "radio_broadcast_template":
        if not message.from_user or not _actor_can_radio_permission(message.from_user.id, "radio.broadcast", session.selected_chat_id):
            await message.answer(error_text("Acesso negado", "Sem permissão radio.broadcast para broadcast.", "Peça ao Owner para conceder acesso no grupo selecionado."))
            return
        try:
            template_id = int((message.text or "").strip())
        except ValueError:
            await message.answer(error_text("Template inválido", "Envie apenas o ID numérico do template.", "Use o painel Templates para ver IDs."), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        template = get_template(template_id)
        if not template:
            await message.answer(error_text("Template não encontrado", f"ID: {template_id}", "Confira a lista de templates."), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        await _delete_private_input(message)
        set_action("radio_broadcast_confirm", radio_template_id=template_id)
        preview = html.escape(str(template.get("body") or "")[:700])
        if len(str(template.get("body") or "")) > 700:
            preview += "\n..."
        sent = await message.answer(
            "Radio — confirmar envio para todos\n\n"
            f"Template: {template_id} — {html.escape(str(template.get('name') or 'sem nome'))}\n"
            "Destino: todos os grupos gerenciados habilitados.\n"
            "Janela de silêncio e anti-duplicação serão respeitados.\n\n"
            "<blockquote>"
            f"{preview}"
            "</blockquote>",
            reply_markup=radio_broadcast_confirm_keyboard(),
        )
        await _remember_ephemeral_message(sent, "radio_broadcast_confirm", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "chat_id":
        try:
            chat_id = parse_chat_id(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Chat ID inválido", str(exc), "Envie apenas o chat_id numérico, com ou sem hífen."))
            return
        # Sprint 7 (T03-fix2, architect): mesmo check proativo do caminho
        # via botão. Sem isso o caminho manual aceitava qualquer chat_id e
        # só falhava na primeira ação.
        blocking, warn = await _validate_group_access(message.bot, chat_id)
        if blocking:
            await message.answer(blocking, reply_markup=home_keyboard())
            return
        title = _group_label_for_chat(chat_id, "Grupo selecionado manualmente")
        remember_group(chat_id, title)
        set_selected_group(chat_id, title)
        await message.answer(
            success_text("Grupo selecionado", f"Grupo: {title}{warn or ''}"),
            reply_markup=entry_keyboard(is_root=is_root_user(message.from_user.id), can_delegate=is_moderator_user(message.from_user.id), can_radio=has_any_radio_permission(message.from_user.id)),
        )
        return

    if session.waiting_for == "customize_title":
        if not session.selected_chat_id:
            await message.answer(_need_group_text(), reply_markup=home_keyboard())
            return
        if not message.from_user or not is_root_user(message.from_user.id):
            await message.answer(error_text("Acesso negado", "Somente o Owner pode alterar nome do grupo.", "Use uma conta Owner."))
            return
        new_title = (message.text or "").strip()
        if not new_title:
            await message.answer(error_text("Nome vazio", "Não há nome para aplicar.", "Envie um nome válido para o grupo."), reply_markup=governance_keyboard())
            return
        await _delete_private_input(message)
        chat_id = int(session.selected_chat_id)
        _prepare_governance_confirmation("governance_set_title", chat_id, {"title": new_title})
        sent = await message.answer(
            "Tigrão — confirmação de governança\n\n"
            "Esta ação altera a identidade do grupo e é Owner-only.\n\n"
            f"{_governance_summary('governance_set_title', chat_id, {'title': new_title})}\n\n"
            "Confirme novamente para executar.",
            reply_markup=governance_confirm_keyboard(),
        )
        await _remember_ephemeral_message(sent, "governance_confirm", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "customize_bio":
        if not session.selected_chat_id:
            await message.answer(_need_group_text(), reply_markup=home_keyboard())
            return
        if not message.from_user or not is_root_user(message.from_user.id):
            await message.answer(error_text("Acesso negado", "Somente o Owner pode alterar descrição do grupo.", "Use uma conta Owner."))
            return
        new_bio = (message.text or "").strip()
        await _delete_private_input(message)
        chat_id = int(session.selected_chat_id)
        _prepare_governance_confirmation("governance_set_description", chat_id, {"description": new_bio})
        sent = await message.answer(
            "Tigrão — confirmação de governança\n\n"
            "Esta ação altera a descrição do grupo e é Owner-only.\n\n"
            f"{_governance_summary('governance_set_description', chat_id, {'description': new_bio})}\n\n"
            "Confirme novamente para executar.",
            reply_markup=governance_confirm_keyboard(),
        )
        await _remember_ephemeral_message(sent, "governance_confirm", actor_user_id=message.from_user.id)
        return

    if session.waiting_for == "outbound_text":
        if not session.selected_chat_id:
            await message.answer(_need_group_text(), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        required = "radio.pin" if session.payload.get("pin") else "radio.post_text"
        if not message.from_user or not _actor_can_radio_permission(message.from_user.id, "radio.post_text", session.selected_chat_id):
            await message.answer(_radio_access_denied_text("radio.post_text"), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        if session.payload.get("pin") and not _actor_can_radio_permission(message.from_user.id, "radio.pin", session.selected_chat_id):
            await message.answer(_radio_access_denied_text("radio.pin"), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        text_to_send = message.text or ""
        if not text_to_send.strip():
            await message.answer(error_text("Texto vazio", "Não há texto para enviar.", "Envie uma mensagem de texto válida."), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
            return
        await _delete_private_input(message)
        draft_id = create_text_draft(
            actor_user_id=message.from_user.id if message.from_user else OWNER_ID,
            target_chat_id=int(session.selected_chat_id),
            text_value=text_to_send,
            pin=bool(session.payload.get("pin")),
        )
        await _radio_answer_draft_preview(message, draft_id, reason="text_input")
        return

    if session.waiting_for == "message_link":
        try:
            link_chat_id, message_id = parse_message_link(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Link inválido", str(exc), "Envie um link de mensagem do Telegram."))
            return
        try:
            await delete_message(message.bot, link_chat_id, message_id)
            log_action(chat_id=int(link_chat_id) if isinstance(link_chat_id, int) else None, action="delete_by_link", status="success")
            clear_action()
            await message.answer(success_text("Mensagem apagada", f"Origem: {link_chat_id}\nMensagem: {message_id}"), reply_markup=messages_keyboard())
        except TelegramForbiddenError as exc:
            log_action(chat_id=int(link_chat_id) if isinstance(link_chat_id, int) else None, action="delete_by_link", status="error", error_type=type(exc).__name__, error_message=str(exc))
            clear_action()
            await message.answer(error_text("Permissão insuficiente", "O Telegram recusou a remoção da mensagem.", "Confira se o bot é administrador e pode apagar mensagens."), reply_markup=messages_keyboard())
        except Exception as exc:
            log_action(chat_id=int(link_chat_id) if isinstance(link_chat_id, int) else None, action="delete_by_link", status="error", error_type=type(exc).__name__, error_message=str(exc))
            clear_action()
            await message.answer(error_text("Falha ao apagar", f"{type(exc).__name__}: {exc}", "Confira o link e as permissões do bot."), reply_markup=messages_keyboard())
        return

    if session.waiting_for == "user_id":
        try:
            user_id = parse_user_id(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("User ID inválido", str(exc), "Envie apenas o user_id numérico, sem hífen."))
            return
        session.payload["target_user_id"] = user_id
        # Sprint 7 (T01-fix): garante refresh quando NÃO é mute (cai no else)
        if session.selected_action == "mute":
            session.waiting_for = "duration"
            touch_session()  # Sprint 7 (T01-fix): refresh updated_at em transition
            await message.answer(
                "Tigrão — duração do mute\n\n"
                f"Grupo: {_session_group_label()}\n"
                f"Usuário: {user_id}\n\n"
                "Envie a duração. Exemplos:\n"
                "10m, 2h, 3d ou i para indefinido."
            )
            return
        session.waiting_for = None
        touch_session()  # Sprint 7 (T01-fix): refresh updated_at em transition
        await message.answer(_confirm_text(), reply_markup=confirm_keyboard())
        return

    if session.waiting_for == "duration":
        try:
            duration = parse_duration(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Duração inválida", str(exc), "Use valores como 10m, 2h, 3d ou i."))
            return
        if duration == "desmutar":
            await message.answer(error_text("Duração inválida", "x é usado para desmutar, não para mutar.", "Use 10m, 2h, 3d ou i."))
            return
        session.payload["duration"] = duration
        session.payload["duration_label"] = str(message.text or "").strip()
        session.waiting_for = None
        touch_session()  # Sprint 7 (T01-fix): refresh updated_at em transition
        await message.answer(_confirm_text(), reply_markup=confirm_keyboard())
        return

    # Sprint X1 (TR3): Reaction Moderation — handlers de texto
    if session.waiting_for == "rmod_link":
        try:
            link_chat_id, link_msg_id = parse_message_link(message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Link inválido", str(exc), "Cole um link de mensagem do Telegram (t.me/grupo/123 ou t.me/c/123/456)."))
            return
        session.payload["link_chat_id"] = link_chat_id
        session.payload["link_msg_id"] = link_msg_id
        if session.selected_action == "rmod_del_user_msg":
            # Sprint X3: em vez de pedir @username (que falha quando o
            # bot nunca interagiu com o user), busca a lista de quem
            # reagiu nessa msg (últimas 24h) e mostra como botões.
            # Se o link aponta pra outro chat e a lista vier vazia
            # (msg antiga ou bot não viu reactions), cai no fallback
            # de texto manual.
            reactors = []
            try:
                if isinstance(link_chat_id, int):
                    reactors = reaction_audit_service.list_message_reactors(
                        chat_id=link_chat_id, message_id=int(link_msg_id),
                    )
            except Exception:
                logger.exception("RMOD_PICKER_QUERY_FAILED chat=%s msg=%s", link_chat_id, link_msg_id)
            if reactors:
                nonce = _new_picker_nonce()
                session.payload["reactors"] = reactors
                session.payload["picker_nonce"] = nonce
                session.waiting_for = None
                touch_session()
                await message.answer(
                    "Tigrão — escolha o reactor\n\n"
                    f"Mensagem: {link_chat_id} / {link_msg_id}\n"
                    f"Reactors detectados (últimas 24h): {len(reactors)}\n\n"
                    "Toque na pessoa cuja reaction deve ser apagada.",
                    reply_markup=rmod_reactors_picker_keyboard(reactors, nonce),
                )
                return
            # Fallback: sem dados no audit → pede manual.
            session.waiting_for = "rmod_user"
            touch_session()
            await message.answer(
                "Tigrão — apagar reaction de 1 pessoa\n\n"
                f"Mensagem: {link_chat_id} / {link_msg_id}\n\n"
                "Não encontrei reactions rastreadas dessa msg nas últimas 24h "
                "(o bot só vê reactions feitas após estar admin com message_reaction ligado).\n\n"
                "Envie agora o user_id numérico OU @username da pessoa."
            )
            return
        # rmod_del_all_msg → direto pra confirmação
        session.waiting_for = None
        touch_session()
        await message.answer(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
        return

    if session.waiting_for == "rmod_user":
        try:
            target_user_id, target_label = await resolve_user_target(message.bot, message.text or "")
        except ValueError as exc:
            await message.answer(error_text("Entrada inválida", str(exc), "Envie user_id numérico ou @username."))
            return
        except RuntimeError as exc:
            await message.answer(error_text("Não foi possível resolver", str(exc), "Confira o @username ou use o user_id numérico."))
            return
        # Hard-block moderadores: nenhum moderador autorizado (owner ou 2º
        # co-moderador) pode ser alvo de moderação de reactions/mute.
        if is_moderator_user(target_user_id):
            await message.answer(error_text("Operação bloqueada", "Você não pode moderar um moderador.", "Cancele e escolha outro alvo."))
            return
        session.payload["target_user_id"] = target_user_id
        session.payload["target_label"] = target_label
        # Discrimina próximo passo por ação selecionada:
        # - mute_react → escolher duração (teclado)
        # - del_user_msg / del_user_chat → direto pra confirmação
        if session.selected_action == "rmod_mute_react":
            session.waiting_for = None
            touch_session()
            await message.answer(
                "Tigrão — duração do silêncio de reactions\n\n"
                f"Grupo: {_session_group_label()}\n"
                f"Alvo: {target_label} ({target_user_id})\n\n"
                "Escolha por quanto tempo o alvo ficará sem poder reagir.",
                reply_markup=rmod_duration_keyboard(),
            )
            return
        # del_user_msg ou del_user_chat
        session.waiting_for = None
        touch_session()
        await message.answer(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
        return


@router.message(F.photo | F.video | F.document | F.animation | F.sticker | F.audio | F.voice | F.video_note, _is_owner_waiting_media)
async def tigrao_private_media(message: Message) -> None:
    # Sprint 7 (T01): mesmo guard de expiração do handler de texto.
    if consume_if_expired():
        await message.answer(
            error_text(
                "Sessão expirada",
                "O fluxo anterior expirou por inatividade (15 min).",
                "Use /radio para abrir o painel novamente.",
            )
        )
        return
    session = get_session()
    if not session.selected_chat_id:
        await message.answer(_need_group_text(), reply_markup=_radio_keyboard_for_actor(message.from_user.id if message.from_user else None))
        return
    pin = bool(session.payload.get("pin"))
    await _delete_private_input(message)
    draft_id = create_media_draft(
        actor_user_id=message.from_user.id if message.from_user else OWNER_ID,
        target_chat_id=int(session.selected_chat_id),
        source_chat_id=int(message.chat.id),
        source_message_id=int(message.message_id),
        pin=pin,
    )
    await _radio_answer_draft_preview(message, draft_id, reason="media_input")


@router.callback_query(F.data == "radio:draft:confirm")
async def radio_draft_confirm(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    draft_id = _radio_current_draft_id()
    if not draft_id:
        await callback.answer("Nenhum rascunho ativo.", show_alert=True)
        return
    draft = get_draft(draft_id)
    if not draft:
        clear_action()
        if callback.message:
            await callback.message.edit_text(error_text("Rascunho não encontrado", "O rascunho não existe mais.", "Abra /radio e tente novamente."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    if int(draft.get("actor_user_id") or 0) != int(callback.from_user.id):
        await callback.answer("Este rascunho pertence a outro usuário.", show_alert=True)
        return
    if str(draft.get("status") or "") != "pending" or is_draft_expired(draft):
        clear_action()
        if callback.message:
            await callback.message.edit_text(error_text("Rascunho expirado", "O rascunho não está mais pendente.", "Crie um novo rascunho pelo /radio."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    is_pinned_draft = bool(int(draft.get("pin") or 0))
    base_permission = "radio.post_media" if draft.get("kind") == "media" else "radio.post_text"
    required_permission = "radio.pin" if is_pinned_draft else base_permission
    actor_id = callback.from_user.id if callback.from_user else None
    if not _actor_can_radio_permission(actor_id, base_permission, int(draft["target_chat_id"])):
        await callback.answer("Permissão Radio ausente.", show_alert=True)
        if callback.message:
            await callback.message.edit_text(_radio_access_denied_text(base_permission), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        return
    if is_pinned_draft and not _actor_can_radio_permission(actor_id, "radio.pin", int(draft["target_chat_id"])):
        await callback.answer("Permissão Radio ausente.", show_alert=True)
        if callback.message:
            await callback.message.edit_text(_radio_access_denied_text("radio.pin"), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        return
    action = "send_text_pin" if draft.get("kind") == "text" and int(draft.get("pin") or 0) else "send_text"
    if draft.get("kind") == "media":
        action = "send_media_pin" if int(draft.get("pin") or 0) else "send_media"
    template_id = get_session().payload.get("radio_template_id")
    content_hash = _radio_draft_hash(draft)
    duplicate = find_recent_duplicate(chat_id=int(draft["target_chat_id"]), message_hash_value=content_hash)
    if duplicate:
        mark_error(draft_id, error="duplicate_recent")
        await callback.answer("Postagem duplicada recente bloqueada.", show_alert=True)
        log_audit_event(
            category="radio",
            action="draft_dedupe_block",
            status="blocked",
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            payload={"draft_id": draft_id, "duplicate_event_id": duplicate.get("event_id")},
        )
        record_post_history(
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            kind=str(draft.get("kind") or "unknown"),
            pin=bool(int(draft.get("pin") or 0)),
            template_id=int(template_id) if template_id else None,
            draft_id=draft_id,
            message_hash_value=content_hash,
            status="blocked",
            reason="duplicate_recent",
        )
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text(
                    "Postagem duplicada bloqueada",
                    "Conteúdo idêntico já foi enviado recentemente para este grupo.",
                    "Altere o conteúdo ou aguarde antes de enviar novamente.",
                ),
                reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None),
            )
        return
    try:
        sent_message_id = await _radio_execute_draft(callback.bot, draft)
        mark_sent(draft_id, sent_message_id=sent_message_id)
        record_post_history(
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            kind=str(draft.get("kind") or "unknown"),
            pin=bool(int(draft.get("pin") or 0)),
            template_id=int(template_id) if template_id else None,
            draft_id=draft_id,
            message_hash_value=content_hash,
            telegram_message_id=sent_message_id,
            status="success",
        )
        log_action(chat_id=int(draft["target_chat_id"]), action=action, status="success")
        log_audit_event(
            category="radio",
            action="draft_send",
            status="success",
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            target_message_id=sent_message_id,
            payload={
                "draft_id": draft_id,
                "kind": draft.get("kind"),
                "pin": bool(int(draft.get("pin") or 0)),
            },
        )
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                success_text(
                    "Postagem enviada",
                    f"Grupo: {_group_label_for_chat(draft['target_chat_id'])}\nMensagem enviada com sucesso.",
                ),
                reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None),
            )
        await callback.answer("Enviado.")
    except TelegramForbiddenError as exc:
        mark_error(draft_id, error=str(exc))
        record_post_history(
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            kind=str(draft.get("kind") or "unknown"),
            pin=bool(int(draft.get("pin") or 0)),
            template_id=int(template_id) if template_id else None,
            draft_id=draft_id,
            message_hash_value=content_hash,
            status="error",
            reason=type(exc).__name__,
        )
        log_action(chat_id=int(draft["target_chat_id"]), action=action, status="error", error_type=type(exc).__name__, error_message=str(exc))
        log_audit_event(
            category="radio",
            action="draft_send",
            status="error",
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            reason=type(exc).__name__,
            payload={"draft_id": draft_id, "error": str(exc)},
        )
        clear_action()
        if callback.message:
            await callback.message.edit_text(error_text("Permissão insuficiente", "O Telegram recusou a postagem ou fixação.", "Confira se o bot pode enviar e, quando necessário, fixar no grupo."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
    except Exception as exc:
        mark_error(draft_id, error=f"{type(exc).__name__}: {exc}")
        record_post_history(
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            kind=str(draft.get("kind") or "unknown"),
            pin=bool(int(draft.get("pin") or 0)),
            template_id=int(template_id) if template_id else None,
            draft_id=draft_id,
            message_hash_value=content_hash,
            status="error",
            reason=type(exc).__name__,
        )
        log_action(chat_id=int(draft["target_chat_id"]), action=action, status="error", error_type=type(exc).__name__, error_message=str(exc))
        log_audit_event(
            category="radio",
            action="draft_send",
            status="error",
            actor_user_id=callback.from_user.id,
            chat_id=int(draft["target_chat_id"]),
            reason=type(exc).__name__,
            payload={"draft_id": draft_id, "error": str(exc)},
        )
        clear_action()
        if callback.message:
            await callback.message.edit_text(error_text("Falha ao enviar", f"{type(exc).__name__}: {exc}", "Confira grupo, conteúdo e permissões do bot."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()


@router.callback_query(F.data == "radio:draft:cancel")
async def radio_draft_cancel(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    draft_id = _radio_current_draft_id()
    if draft_id:
        try:
            mark_cancelled(draft_id)
            log_audit_event(
                category="radio",
                action="draft_cancel",
                status="success",
                actor_user_id=callback.from_user.id if callback.from_user else None,
                payload={"draft_id": draft_id},
            )
        except Exception:
            logger.exception("RADIO_DRAFT_CANCEL_AUDIT_FAILED draft=%s", draft_id)
    clear_action()
    if callback.message:
        await callback.message.edit_text(success_text("Rascunho cancelado", "Nada foi enviado ao grupo."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
    await callback.answer("Cancelado.")



@router.callback_query(F.data == "tigrao:entry")
async def tigrao_entry_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not (is_moderator_user(callback.from_user.id) or has_any_radio_permission(callback.from_user.id)):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    is_root = is_root_user(callback.from_user.id)
    can_delegate = is_moderator_user(callback.from_user.id)
    can_radio = is_root or has_any_radio_permission(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text(
            entry_text(is_root=is_root, can_delegate=can_delegate, can_radio=can_radio),
            reply_markup=entry_keyboard(is_root=is_root, can_delegate=can_delegate, can_radio=can_radio),
        )
        upsert_panel(
            actor_user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            panel_type="tigrao_entry",
        )
    await callback.answer()


@router.callback_query(F.data == "owner:home")
async def owner_home_callback(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode abrir este painel.", show_alert=True)
        return
    await _edit_private_panel(callback, owner_home_text(), owner_home_keyboard())


@router.callback_query(F.data == "tigrao:home")
async def tigrao_home_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_moderator_user(callback.from_user.id):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    await _edit_private_panel(callback, delegate_home_text(), delegate_home_keyboard())


@router.callback_query(F.data == "radio:home")
async def radio_home_callback(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback):
        await callback.answer("Sem permissão para abrir o Radio.", show_alert=True)
        return
    await _edit_radio_panel(callback, radio_home_text(), await _radio_keyboard_for_actor_async(callback.bot, callback.from_user.id))


@router.callback_query(F.data == "radio:templates")
@router.callback_query(F.data.startswith("radio:templates:page:"))
async def radio_templates(callback: CallbackQuery) -> None:
    if not (_callback_can_use_radio(callback, "radio.templates.use") or _callback_can_use_radio(callback, "radio.templates.manage")):
        await callback.answer("Sem permissão para templates do Radio.", show_alert=True)
        return
    try:
        page = 0 if callback.data == "radio:templates" else page_number(callback.data, prefix="radio:templates:page:", default=0)
    except CallbackParseError as exc:
        await _answer_bad_callback(callback, exc)
        return
    rows, has_next = _radio_template_page_rows(page)
    can_manage = _callback_can_use_radio(callback, "radio.templates.manage")
    await _edit_radio_panel(
        callback,
        f"Radio — templates\n\nPágina {page + 1}. Crie ou use modelos reutilizáveis de postagem. Ao usar um template, ele vira rascunho e ainda exige confirmação.",
        radio_templates_keyboard(rows, page=page, has_next=has_next, can_manage=can_manage),
    )

@router.callback_query(F.data == "radio:templates:create")
async def radio_template_create(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.templates.manage", require_chat=True):
        await callback.answer("Sem permissão para criar templates.", show_alert=True)
        return
    set_action("radio_template_create", waiting_for="radio_template_body")
    if callback.message:
        await callback.message.edit_text(
            "Radio — criar template\n\n"
            "Envie agora em uma única mensagem:\n\n"
            "nome do template\n"
            "conteúdo do template\n\n"
            "Exemplo:\n"
            "Aviso semanal\n"
            "Hoje temos programação especial no grupo."
        )
    await callback.answer()

@router.callback_query(F.data.startswith("radio:template:use:"))
async def radio_template_use(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.templates.use", require_chat=True):
        await callback.answer("Sem permissão para usar templates.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    try:
        template_id = trailing_int(callback.data, prefix="radio:template:use:", name="template_id")
    except CallbackParseError as exc:
        await _answer_bad_callback(callback, exc)
        return
    template = get_template(template_id)
    if not template:
        await callback.answer("Template não encontrado.", show_alert=True)
        return
    draft_id = create_text_draft(
        actor_user_id=callback.from_user.id,
        target_chat_id=int(session.selected_chat_id),
        text_value=str(template.get("body") or ""),
        pin=False,
    )
    session.payload["radio_template_id"] = template_id
    set_action("radio_confirm_draft", radio_draft_id=draft_id, radio_template_id=template_id)
    try:
        log_audit_event(
            category="radio",
            action="template_use",
            status="success",
            actor_user_id=callback.from_user.id,
            chat_id=int(session.selected_chat_id),
            payload={"template_id": template_id, "draft_id": draft_id},
        )
    except Exception:
        logger.exception("RADIO_TEMPLATE_USE_AUDIT_FAILED template=%s draft=%s", template_id, draft_id)
    if callback.message:
        await callback.message.edit_text(_radio_preview_text(get_draft(draft_id)), reply_markup=radio_draft_confirm_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("radio:template:delete:"))
async def radio_template_delete(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.templates.manage", require_chat=True):
        await callback.answer("Sem permissão para apagar templates.", show_alert=True)
        return
    try:
        template_id = trailing_int(callback.data, prefix="radio:template:delete:", name="template_id")
    except CallbackParseError as exc:
        await _answer_bad_callback(callback, exc)
        return
    ok = delete_template(template_id)
    try:
        log_audit_event(
            category="radio",
            action="template_delete",
            status="success" if ok else "not_found",
            actor_user_id=callback.from_user.id,
            payload={"template_id": template_id},
        )
    except Exception:
        logger.exception("RADIO_TEMPLATE_DELETE_AUDIT_FAILED template=%s", template_id)
    await _edit_radio_panel(
        callback,
        success_text("Template apagado" if ok else "Template não encontrado", f"ID: {template_id}"),
        radio_templates_keyboard(list_templates()),
    )

@router.callback_query(F.data == "radio:history")
@router.callback_query(F.data.startswith("radio:history:page:"))
async def radio_history(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.history.read", require_chat=True):
        await callback.answer("Sem permissão para ver histórico do Radio.", show_alert=True)
        return
    try:
        page = 0 if callback.data == "radio:history" else page_number(callback.data, prefix="radio:history:page:", default=0)
    except CallbackParseError as exc:
        await _answer_bad_callback(callback, exc)
        return
    session = get_session()
    chat_id = int(session.selected_chat_id) if session.selected_chat_id else None
    rows, has_next = _radio_history_page_rows(chat_id, page)
    await _edit_radio_panel(callback, _radio_history_text(chat_id, page=page, rows=rows), radio_history_keyboard(page=page, has_next=has_next))

@router.callback_query(F.data == "radio:schedules")
@router.callback_query(F.data.startswith("radio:schedules:page:"))
async def radio_schedules(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.schedule", require_chat=True):
        await callback.answer("Sem permissão para agendamentos do Radio.", show_alert=True)
        return
    try:
        page = 0 if callback.data == "radio:schedules" else page_number(callback.data, prefix="radio:schedules:page:", default=0)
    except CallbackParseError as exc:
        await _answer_bad_callback(callback, exc)
        return
    session = get_session()
    chat_id = int(session.selected_chat_id) if session.selected_chat_id else None
    rows, has_next = _radio_schedule_page_rows(chat_id, page)
    await _edit_radio_panel(callback, _radio_schedules_text(chat_id, page=page, rows=rows), radio_schedules_keyboard(page=page, has_next=has_next, can_create=True))

@router.callback_query(F.data == "radio:schedules:create")
async def radio_schedule_create(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.schedule", require_chat=True):
        await callback.answer("Sem permissão para criar agendamento.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    set_action("radio_schedule_create", waiting_for="radio_schedule_body")
    if callback.message:
        await callback.message.edit_text(
            "Radio — criar agendamento\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie no formato:\n"
            "template_id intervalo_min pin(0/1)\n\n"
            "Exemplo:\n"
            "5 120 0\n\n"
            "Isso envia o template 5 a cada 120 minutos, sem fixar."
        )
    await callback.answer()

@router.callback_query(F.data == "radio:schedules:run")
async def radio_schedules_run(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.schedule", require_chat=True):
        await callback.answer("Sem permissão para processar agendamentos.", show_alert=True)
        return
    result = await run_due_schedules(callback.bot)
    try:
        log_audit_event(
            category="radio",
            action="schedules_manual_run",
            status="success",
            actor_user_id=callback.from_user.id,
            payload=result,
        )
    except Exception:
        logger.exception("RADIO_SCHEDULE_MANUAL_RUN_AUDIT_FAILED")
    await _edit_radio_panel(
        callback,
        success_text(
            "Agendamentos processados",
            f"Enviados: {result.get('sent', 0)}\nPulados/bloqueados: {result.get('skipped', 0)}\nErros: {result.get('error', 0)}",
        ),
        radio_schedules_keyboard(),
    )

@router.callback_query(F.data == "radio:quiet")
async def radio_quiet(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.quiet_hours.manage", require_chat=True):
        await callback.answer("Sem permissão para janela de silêncio.", show_alert=True)
        return
    session = get_session()
    chat_id = int(session.selected_chat_id) if session.selected_chat_id else None
    await _edit_radio_panel(callback, _radio_quiet_text(chat_id), radio_quiet_keyboard())

@router.callback_query(F.data == "radio:quiet:set")
async def radio_quiet_set(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.quiet_hours.manage", require_chat=True):
        await callback.answer("Sem permissão para configurar janela de silêncio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    set_action("radio_quiet", waiting_for="radio_quiet_policy")
    if callback.message:
        await callback.message.edit_text(
            "Radio — configurar janela de silêncio\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie no formato:\n"
            "HH:MM-HH:MM +00:00\n\n"
            "Exemplo para horário de Brasília:\n"
            "23:00-08:00 -03:00\n\n"
            "Para desligar, envie: off"
        )
    await callback.answer()

@router.callback_query(F.data == "radio:quiet:off")
async def radio_quiet_off(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.quiet_hours.manage", require_chat=True):
        await callback.answer("Sem permissão para desativar janela de silêncio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    set_group_policy(
        chat_id=int(session.selected_chat_id),
        quiet_from=None,
        quiet_to=None,
        utc_offset_minutes=0,
        updated_by_user_id=callback.from_user.id,
    )
    try:
        log_audit_event(
            category="radio",
            action="quiet_hours_disable",
            status="success",
            actor_user_id=callback.from_user.id,
            chat_id=int(session.selected_chat_id),
        )
    except Exception:
        logger.exception("RADIO_QUIET_OFF_AUDIT_FAILED")
    await _edit_radio_panel(callback, _radio_quiet_text(int(session.selected_chat_id)), radio_quiet_keyboard())

@router.callback_query(F.data == "radio:broadcast")
async def radio_broadcast(callback: CallbackQuery) -> None:
    if not _callback_can_broadcast_radio(callback):
        await callback.answer("Sem permissão para broadcast do Radio.", show_alert=True)
        return
    set_action("radio_broadcast", waiting_for="radio_broadcast_template")
    if callback.message:
        await callback.message.edit_text(
            "Radio — enviar para todos os grupos gerenciados\n\n"
            "Envie o ID numérico do template que será enviado.\n"
            "O envio respeita janela de silêncio e anti-duplicação por grupo.\n\n"
            "A próxima tela exigirá confirmação."
        )
    await callback.answer()

@router.callback_query(F.data == "radio:broadcast:confirm")
async def radio_broadcast_confirm(callback: CallbackQuery) -> None:
    if not _callback_can_broadcast_radio(callback):
        await callback.answer("Sem permissão para confirmar broadcast.", show_alert=True)
        return
    template_id = get_session().payload.get("radio_template_id")
    if not template_id:
        await callback.answer("Nenhum broadcast pendente.", show_alert=True)
        return
    try:
        result = await broadcast_template_to_managed_groups(
            callback.bot,
            template_id=int(template_id),
            actor_user_id=callback.from_user.id,
            pin=False,
            chat_ids=_radio_broadcast_allowed_chat_ids(callback.from_user.id if callback.from_user else None),
        )
    except Exception as exc:
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text("Falha no broadcast", f"{type(exc).__name__}: {exc}", "Confira template e grupos gerenciados."),
                reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None),
            )
        await callback.answer()
        return
    clear_action()
    if callback.message:
        await callback.message.edit_text(
            success_text(
                "Broadcast concluído",
                f"Total: {result.get('total', 0)}\nSucesso: {result.get('success', 0)}\nPulados/bloqueados: {result.get('skipped', 0)}\nErros: {result.get('error', 0)}\nLock ativo: {result.get('locked', 0)}",
            ),
            reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None),
        )
    await callback.answer("Broadcast concluído.")

@router.callback_query(F.data == "radio:broadcast:cancel")
async def radio_broadcast_cancel(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    clear_action()
    if callback.message:
        await callback.message.edit_text(success_text("Broadcast cancelado", "Nada foi enviado aos grupos."), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
    await callback.answer("Cancelado.")

@router.callback_query(F.data.startswith("tigrao:rights:missing:"))
async def tigrao_rights_missing(callback: CallbackQuery) -> None:
    capability = (callback.data or "").rsplit(":", 1)[-1]
    await callback.answer(
        f"Ação indisponível: o bot não possui {_capability_label(capability)} no grupo selecionado.",
        show_alert=True,
    )


@router.callback_query(F.data == "tigrao:groups")
async def tigrao_groups(callback: CallbackQuery) -> None:
    if not callback.from_user or not (
        is_root_user(callback.from_user.id)
        or has_any_grant(callback.from_user.id)
        or has_any_radio_permission(callback.from_user.id)
    ):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    managed, discovered_count, inaccessible_count = _group_panel_counts()
    session = get_session()
    current = get_managed_group(session.selected_chat_id) if session.selected_chat_id else None
    if callback.message:
        await callback.message.edit_text(
            _section_text(
                "grupos",
                "Escolha um grupo gerenciado. Grupos apenas vistos ficam separados como descobertos.",
            ),
            reply_markup=groups_keyboard(
                current_group=current,
                managed_groups=managed,
                discovered_count=discovered_count,
                inaccessible_count=inaccessible_count,
            ),
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:groups:refresh")
async def tigrao_groups_refresh(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_root_user(callback.from_user.id):
        await callback.answer("Somente o Owner pode atualizar status.", show_alert=True)
        return
    result = await refresh_managed_group_rights(callback.bot, limit=100)
    managed, discovered_count, inaccessible_count = _group_panel_counts()
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — grupos\n\n"
            "Status dos grupos gerenciados atualizado.\n\n"
            f"Total: {result.get('total', 0)}\n"
            f"Admin: {result.get('admin', 0)}\n"
            f"Musical-only: {result.get('musical_only', 0)}\n"
            f"Erro: {result.get('error', 0)}",
            reply_markup=groups_keyboard(
                managed_groups=managed,
                discovered_count=discovered_count,
                inaccessible_count=inaccessible_count,
            ),
        )
    await callback.answer("Status atualizado.")


@router.callback_query(F.data == "tigrao:groups:discovered")
async def tigrao_groups_discovered(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_root_user(callback.from_user.id):
        await callback.answer("Somente o Owner pode ver descobertos.", show_alert=True)
        return
    managed_ids = {int(g["chat_id"]) for g in list_managed_groups(limit=500)}
    discovered = [g for g in list_groups(limit=100) if int(g.get("chat_id")) not in managed_ids]
    lines = ["Tigrão — grupos descobertos", "", "Grupos vistos que ainda não são gerenciados:", ""]
    if not discovered:
        lines.append("Nenhum grupo descoberto fora da lista gerenciada.")
    else:
        for group in discovered[:30]:
            lines.append(f"- {group_display_name(group.get('title'), 'Grupo')}")
    if callback.message:
        await callback.message.edit_text("\n".join(lines), reply_markup=groups_keyboard(managed_groups=[g for g in list_managed_groups(limit=100) if int(g.get('enabled') or 0) == 1]))
    await callback.answer()


@router.callback_query(F.data == "tigrao:groups:inaccessible")
async def tigrao_groups_inaccessible(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_root_user(callback.from_user.id):
        await callback.answer("Somente o Owner pode ver diagnóstico.", show_alert=True)
        return
    await callback.answer("Use Segurança > Diagnóstico direitos todos para detalhes técnicos.", show_alert=True)


@router.callback_query(F.data == "tigrao:group:manual")
async def tigrao_group_manual(callback: CallbackQuery) -> None:
    if not callback.from_user or not (is_root_user(callback.from_user.id) or has_any_grant(callback.from_user.id) or has_any_radio_permission(callback.from_user.id)):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    set_action("select_group", waiting_for="chat_id")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — escolher grupo\n\n"
            "Envie agora o chat_id numérico do grupo.\n"
            "Essa entrada manual é técnica e só será usada internamente."
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tigrao:group:"))
async def tigrao_group_select(callback: CallbackQuery) -> None:
    if not callback.from_user or not (is_root_user(callback.from_user.id) or has_any_grant(callback.from_user.id) or has_any_radio_permission(callback.from_user.id)):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    if callback.data == "tigrao:group:manual":
        return
    try:
        chat_id = parse_chat_id(callback.data.rsplit(":", 1)[-1])
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    # Sprint 7 (T03): check proativo de permissão antes de selecionar.
    # Evita "selecionar → escolher ação → enviar user_id → erro permissão".
    blocking, perm_warning = await _validate_group_access(callback.bot, chat_id)
    if blocking:
        if callback.message:
            await callback.message.edit_text(blocking, reply_markup=entry_keyboard(is_root=is_root_user(callback.from_user.id), can_delegate=is_moderator_user(callback.from_user.id), can_radio=has_any_radio_permission(callback.from_user.id)))
        await callback.answer()
        return

    title = _group_label_for_chat(chat_id)
    set_selected_group(chat_id, title)
    if callback.message:
        await callback.message.edit_text(
            success_text("Grupo selecionado", f"Grupo: {title}{perm_warning or ''}"),
            reply_markup=entry_keyboard(is_root=is_root_user(callback.from_user.id), can_delegate=is_moderator_user(callback.from_user.id), can_radio=has_any_radio_permission(callback.from_user.id)),
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:user_actions")
async def tigrao_user_actions(callback: CallbackQuery) -> None:
    await _edit_private_panel(
        callback,
        await _rights_aware_section_text(callback.bot, "ações de usuário", "Ações que exigem grupo selecionado e, em geral, apenas o user_id do alvo."),
        user_actions_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)),
    )


@router.callback_query(F.data.startswith("tigrao:action:"))
async def tigrao_prepare_user_action(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    action = (callback.data or "").rsplit(":", 1)[-1]
    if action not in ACTION_LABELS:
        await callback.answer("Ação inválida.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action(action, waiting_for="user_id")
    if callback.message:
        await callback.message.edit_text(
            f"Tigrão — {ACTION_LABELS[action]}\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora apenas o user_id do alvo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:confirm")
async def tigrao_confirm(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    chat_id = session.selected_chat_id
    action = session.selected_action
    target_user_id = session.payload.get("target_user_id")
    if not chat_id or not action or not target_user_id:
        if callback.message:
            await callback.message.edit_text(
                error_text("Confirmação inválida", "Faltam dados para confirmar a ação.", "Volte ao painel e recomece o fluxo."),
                reply_markup=home_keyboard(),
            )
        await callback.answer()
        return
    if action == "mute" and "duration" not in session.payload:
        if callback.message:
            await callback.message.edit_text(
                error_text("Duração ausente", "Falta informar a duração do mute.", "Recomece a ação de mutar usuário."),
                reply_markup=user_actions_keyboard(),
            )
        await callback.answer()
        return
    if action not in SIMPLE_EXECUTABLE_ACTIONS and action != "mute":
        if callback.message:
            await callback.message.edit_text(
                error_text("Ação ainda não habilitada", f"A ação {ACTION_LABELS.get(action, action)} será ligada em etapa separada.", "Use uma ação já habilitada."),
                reply_markup=user_actions_keyboard(),
            )
        await callback.answer()
        return

    await callback.answer("Executando ação...")
    if callback.message:
        await callback.message.edit_text(
            _execution_text(action, chat_id, target_user_id, session.payload),
            reply_markup=None,
        )

    try:
        extra = await _execute_simple_action(callback.bot, action, int(chat_id), int(target_user_id), session.payload)
        log_action(chat_id=int(chat_id), action=action, target_user_id=int(target_user_id), status="success")
        details = f"Grupo: {_group_label_for_chat(chat_id)}\nAção: {ACTION_LABELS[action]}\nUsuário: {target_user_id}\nStatus: concluído com sucesso"
        if session.payload.get("duration_label"):
            details += f"\nDuração: {session.payload['duration_label']}"
        if extra:
            details += f"\nLink direto: {extra}"
        clear_action()
        if callback.message:
            await callback.message.edit_text(success_text("Ação executada", details), reply_markup=user_actions_keyboard())
    except TelegramForbiddenError as exc:
        log_action(chat_id=int(chat_id), action=action, target_user_id=int(target_user_id), status="error", error_type=type(exc).__name__, error_message=str(exc))
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text(
                    "Permissão insuficiente",
                    f"O Telegram recusou a ação. Erro: {type(exc).__name__}: {exc}",
                    "Confira se o bot é administrador do grupo e tem a permissão necessária.",
                ),
                reply_markup=user_actions_keyboard(),
            )
    except Exception as exc:
        log_action(chat_id=int(chat_id), action=action, target_user_id=int(target_user_id), status="error", error_type=type(exc).__name__, error_message=str(exc))
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text("Falha ao executar", f"{type(exc).__name__}: {exc}", "Confira grupo, user_id e permissões do bot."),
                reply_markup=user_actions_keyboard(),
            )


@router.callback_query(F.data == "tigrao:cancel")
async def tigrao_cancel(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    clear_action()
    if callback.message:
        await callback.message.edit_text("Tigrão — ação cancelada.", reply_markup=home_keyboard())
    await callback.answer()


@router.callback_query(F.data == "tigrao:links")
async def tigrao_links(callback: CallbackQuery) -> None:
    await _edit_private_panel(
        callback,
        await _rights_aware_section_text(callback.bot, "links", "Geração de links de entrada para o grupo selecionado."),
        links_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)),
    )


@router.callback_query(F.data.startswith("tigrao:link:"))
async def tigrao_create_link(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    link_type = (callback.data or "").rsplit(":", 1)[-1]
    if link_type == "direct":
        action = "governance_link_direct"
    elif link_type == "approval":
        action = "governance_link_approval"
    else:
        await callback.answer("Tipo de link inválido.", show_alert=True)
        return
    chat_id = int(session.selected_chat_id)
    _prepare_governance_confirmation(action, chat_id, {})
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — confirmação de governança\n\n"
            "Esta ação altera acesso/entrada do grupo e é Owner-only.\n\n"
            f"{_governance_summary(action, chat_id, {})}\n\n"
            "Confirme novamente para executar.",
            reply_markup=governance_confirm_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:messages")
async def tigrao_messages(callback: CallbackQuery) -> None:
    await _edit_private_panel(
        callback,
        await _rights_aware_section_text(callback.bot, "mensagens", "Use esta seção somente para apagar mensagens por link."),
        messages_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)),
    )


@router.callback_query(F.data == "tigrao:customize")
async def tigrao_customize(callback: CallbackQuery) -> None:
    # Compatibilidade com callbacks antigos: personalização/postagens agora
    # pertencem ao painel Radio.
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode abrir o Radio.", show_alert=True)
        return
    await _edit_private_panel(callback, radio_home_text(), radio_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)))


@router.callback_query(F.data == "tigrao:customize:title")
async def tigrao_customize_title(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action("customize_title", waiting_for="customize_title")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — alterar nome\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora o novo nome do grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:customize:bio")
async def tigrao_customize_bio(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action("customize_bio", waiting_for="customize_bio")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — alterar bio\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora a nova bio/descrição do grupo.\n"
            "Para apagar a bio, envie apenas um ponto: ."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:message:send")
async def tigrao_send_text(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.post_text", require_chat=True):
        await callback.answer("Sem permissão para enviar texto pelo Radio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action("send_text", waiting_for="outbound_text", pin=False)
    if callback.message:
        await callback.message.edit_text(
            "Radio — enviar mensagem\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora o texto que será publicado no grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:message:pin")
async def tigrao_send_text_pin(callback: CallbackQuery) -> None:
    if not (_callback_can_use_radio(callback, "radio.post_text", require_chat=True) and _callback_can_use_radio(callback, "radio.pin", require_chat=True)):
        await callback.answer("Sem permissão para enviar texto fixado pelo Radio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action("send_text_pin", waiting_for="outbound_text", pin=True)
    if callback.message:
        await callback.message.edit_text(
            "Radio — enviar e fixar\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora o texto que será publicado e fixado no grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:message:media")
async def tigrao_send_media(callback: CallbackQuery) -> None:
    if not _callback_can_use_radio(callback, "radio.post_media", require_chat=True):
        await callback.answer("Sem permissão para enviar mídia pelo Radio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    set_action("send_media", waiting_for="outbound_media")
    if callback.message:
        await callback.message.edit_text(
            "Radio — enviar mídia\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora a foto, vídeo, documento, sticker ou outra mídia que será copiada para o grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:message:media_pin")
async def tigrao_send_media_pin(callback: CallbackQuery) -> None:
    if not (_callback_can_use_radio(callback, "radio.post_media", require_chat=True) and _callback_can_use_radio(callback, "radio.pin", require_chat=True)):
        await callback.answer("Sem permissão para enviar mídia fixada pelo Radio.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=_radio_keyboard_for_actor(callback.from_user.id if callback.from_user else None))
        await callback.answer()
        return
    set_action("send_media_pin", waiting_for="outbound_media", pin=True)
    if callback.message:
        await callback.message.edit_text(
            "Radio — enviar mídia e fixar\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Envie agora a foto, vídeo, documento, sticker ou outra mídia que será copiada e fixada no grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:message:delete_link")
async def tigrao_delete_by_link(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    set_action("delete_by_link", waiting_for="message_link")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — apagar por link\n\n"
            "Envie agora o link da mensagem que deve ser apagada.\n\n"
            "Exemplos:\n"
            "https://t.me/c/1234567890/55\n"
            "https://t.me/nomedogrupo/55"
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:ddx")
async def tigrao_ddx(callback: CallbackQuery) -> None:
    await _edit_private_panel(callback, _section_text("filtros DDX", "Configuração futura dos filtros de remoção automática por texto."), ddx_keyboard())


@router.callback_query(F.data.in_({"tigrao:logs", "tigrao:logs:refresh"}))
async def tigrao_logs(callback: CallbackQuery) -> None:
    await _edit_private_panel(callback, _logs_text(), logs_keyboard())


@router.callback_query(F.data == "tigrao:moderators")
async def tigrao_moderators(callback: CallbackQuery) -> None:
    if not is_root_user(callback.from_user.id if callback.from_user else None):
        await callback.answer("Somente o Owner pode gerenciar moderadores.", show_alert=True)
        return
    await _edit_private_panel(callback, _moderators_text(), moderators_keyboard())


@router.callback_query(F.data == "tigrao:moderators:list")
async def tigrao_moderators_list(callback: CallbackQuery) -> None:
    if not is_root_user(callback.from_user.id if callback.from_user else None):
        await callback.answer("Somente o Owner pode gerenciar moderadores.", show_alert=True)
        return
    await _edit_private_panel(callback, _moderators_text(), moderators_keyboard())


@router.callback_query(F.data == "tigrao:moderators:grant")
async def tigrao_moderators_grant(callback: CallbackQuery) -> None:
    if not is_root_user(callback.from_user.id if callback.from_user else None):
        await callback.answer("Somente o Owner pode conceder permissões.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        await _edit_private_panel(callback, _need_group_text(), home_keyboard())
        return
    set_action("moderator_grant", waiting_for="moderator_grant")
    await _edit_private_panel(
        callback,
        "Tigrão — conceder permissão\n\n"
        f"Grupo: {_session_group_label()}\n\n"
        "Envie: <code>user_id permission</code>\n"
        "Ou: <code>user_id *:mod</code>, <code>user_id *:radio</code> ou <code>user_id *:all</code>.\n"
        "Compatibilidade: <code>user_id *</code> concede pacote de moderação.\n\n"
        "Exemplos:\n"
        "<code>123456 moderation.delete</code>\n"
        "<code>123456 radio.post_text</code>\n"
        "<code>123456 *:radio</code>",
        moderators_keyboard(),
    )


@router.callback_query(F.data == "tigrao:moderators:revoke")
async def tigrao_moderators_revoke(callback: CallbackQuery) -> None:
    if not is_root_user(callback.from_user.id if callback.from_user else None):
        await callback.answer("Somente o Owner pode revogar permissões.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        await _edit_private_panel(callback, _need_group_text(), home_keyboard())
        return
    set_action("moderator_revoke", waiting_for="moderator_revoke")
    await _edit_private_panel(
        callback,
        "Tigrão — revogar permissão\n\n"
        f"Grupo: {_session_group_label()}\n\n"
        "Envie: <code>user_id permission</code>\n"
        "Ou: <code>user_id *:mod</code>, <code>user_id *:radio</code> ou <code>user_id *:all</code>.\n"
        "Compatibilidade: <code>user_id *</code> revoga pacote de moderação.",
        moderators_keyboard(),
    )


@router.callback_query(F.data == "tigrao:security")
async def tigrao_security(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode acessar segurança.", show_alert=True)
        return
    await _edit_private_panel(callback, _security_text(), security_keyboard())


@router.callback_query(F.data == "tigrao:security:audit")
async def tigrao_security_audit(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode ver auditoria de segurança.", show_alert=True)
        return
    await _edit_private_panel(callback, _audit_events_text(), security_keyboard())


@router.callback_query(F.data == "tigrao:security:check")
async def tigrao_security_check(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode rodar checks de segurança.", show_alert=True)
        return
    try:
        result = await run_security_check(callback.bot)
        await send_security_alert(
            callback.bot,
            title="manual_security_check",
            detail="Check manual executado pelo Owner.",
            severity="info",
            payload={"result": str(result)[:500]},
            dedupe_key="manual_security_check",
        )
        await _edit_private_panel(callback, _security_text(), security_keyboard())
    except Exception as exc:
        await _edit_private_panel(
            callback,
            error_text("Falha no check de segurança", f"{type(exc).__name__}: {exc}", "Veja logs do servidor."),
            security_keyboard(),
        )






@router.callback_query(F.data == "tigrao:sessions:diag")
async def tigrao_sessions_diag(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode diagnosticar sessões.", show_alert=True)
        return
    try:
        log_audit_event(
            category="sessions",
            action="diagnostics",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "tigrao": tigrao_session_diagnostics().get("total"),
                "btb": btb_session_diagnostics().get("total"),
            },
        )
    except Exception:
        logger.debug("SESSION_DIAGNOSTICS_AUDIT_FAILED", exc_info=True)
    await _edit_private_panel(callback, _format_session_diagnostics(), security_keyboard())


@router.callback_query(F.data == "tigrao:sessions:cleanup")
async def tigrao_sessions_cleanup(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode limpar sessões.", show_alert=True)
        return
    removed_tigrao = tigrao_cleanup_expired_sessions()
    removed_btb = btb_cleanup_expired_sessions()
    try:
        log_audit_event(
            category="sessions",
            action="cleanup_expired",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"tigrao_removed": removed_tigrao, "btb_removed": removed_btb},
        )
    except Exception:
        logger.debug("SESSION_CLEANUP_AUDIT_FAILED", exc_info=True)
    await _edit_private_panel(
        callback,
        success_text(
            "Sessões expiradas limpas",
            f"Tigrão removidas: {removed_tigrao}\nBTB removidas: {removed_btb}",
        ),
        security_keyboard(),
    )


@router.callback_query(F.data == "tigrao:sessions:persisted")
async def tigrao_sessions_persisted(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode diagnosticar sessões persistidas.", show_alert=True)
        return
    rows = list_private_sessions(limit=100)
    lines = ["Sessões persistidas SQLite", "", f"Total: {len(rows)}"]
    for row in rows[:30]:
        lines.append(
            f"- {row.get('namespace')} user={row.get('user_id')} updated={row.get('updated_at')} expires={row.get('expires_at') or '-'}"
        )
    if len(rows) > 30:
        lines.append(f"... +{len(rows) - 30} omitidas")
    if not rows:
        lines.append("- nenhuma sessão persistida")
    await _edit_private_panel(callback, "\n".join(lines), security_keyboard())


@router.callback_query(F.data == "tigrao:locks:diag")
async def tigrao_locks_diag(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode diagnosticar locks.", show_alert=True)
        return
    rows = list_operational_locks()
    lines = ["Locks operacionais", "", f"Total: {len(rows)}"]
    for row in rows[:30]:
        lines.append(
            f"- {row.get('lock_name')} owner={row.get('owner')} expires_at={row.get('expires_at')}"
        )
    if len(rows) > 30:
        lines.append(f"... +{len(rows) - 30} omitidos")
    if not rows:
        lines.append("- nenhum lock ativo")
    await _edit_private_panel(callback, "\n".join(lines), security_keyboard())


@router.callback_query(F.data == "tigrao:locks:cleanup")
async def tigrao_locks_cleanup(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode limpar locks.", show_alert=True)
        return
    removed_locks = cleanup_expired_operational_locks()
    removed_sessions = cleanup_expired_private_sessions()
    try:
        log_audit_event(
            category="locks",
            action="cleanup_expired",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"locks_removed": removed_locks, "sessions_removed": removed_sessions},
        )
    except Exception:
        logger.debug("LOCKS_CLEANUP_AUDIT_FAILED", exc_info=True)
    await _edit_private_panel(
        callback,
        success_text(
            "Locks/sessões expirados limpos",
            f"Locks removidos: {removed_locks}\nSessões persistidas removidas: {removed_sessions}",
        ),
        security_keyboard(),
    )


@router.callback_query(F.data == "tigrao:commands:resync")
async def tigrao_commands_resync(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode ressincronizar menus.", show_alert=True)
        return
    try:
        result = await sync_active_grant_command_scopes(callback.bot, include_root=True)
        log_audit_event(
            category="commands",
            action="resync_active_grants",
            status="success" if int(result.get("error", 0)) == 0 else "partial",
            actor_user_id=callback.from_user.id,
            payload={
                "total": result.get("total"),
                "ok": result.get("ok"),
                "error": result.get("error"),
            },
        )
    except Exception as exc:
        logger.exception("COMMAND_SCOPE_RESYNC_FAILED")
        try:
            log_audit_event(
                category="commands",
                action="resync_active_grants",
                status="error",
                actor_user_id=callback.from_user.id if callback.from_user else None,
                reason=type(exc).__name__,
                payload={"error": str(exc)[:1000]},
            )
        except Exception:
            logger.debug("COMMAND_SCOPE_RESYNC_AUDIT_FAILED", exc_info=True)
        await _edit_private_panel(
            callback,
            error_text(
                "Falha ao ressincronizar menus",
                f"{type(exc).__name__}: {exc}",
                "Permissões não foram alteradas. Tente novamente mais tarde.",
            ),
            security_keyboard(),
        )
        return
    await _edit_private_panel(
        callback,
        success_text(
            "Menus ressincronizados",
            f"Total: {result.get('total', 0)}\nSucesso: {result.get('ok', 0)}\nFalhas: {result.get('error', 0)}",
        ),
        security_keyboard(),
    )




@router.callback_query(F.data == "tigrao:rights:refresh_selected")
async def tigrao_rights_refresh_selected(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode atualizar direitos do bot.", show_alert=True)
        return
    chat_id = get_session().selected_chat_id
    if not chat_id:
        await _edit_private_panel(
            callback,
            error_text(
                "Nenhum grupo selecionado",
                "Selecione um grupo antes de atualizar os direitos reais do bot.",
                "Use Escolher grupo no painel.",
            ),
            security_keyboard(),
        )
        return
    try:
        rights = await get_bot_rights(callback.bot, int(chat_id), force_refresh=True)
        log_audit_event(
            category="bot_rights",
            action="refresh_selected",
            status="success" if not rights.error else "error",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            chat_id=int(chat_id),
            reason=rights.error,
            payload={"rights": format_bot_rights(rights)},
        )
    except Exception as exc:
        logger.exception("BOT_RIGHTS_REFRESH_SELECTED_FAILED | chat_id=%s", chat_id)
        try:
            log_audit_event(
                category="bot_rights",
                action="refresh_selected",
                status="error",
                actor_user_id=callback.from_user.id if callback.from_user else None,
                chat_id=int(chat_id),
                reason=type(exc).__name__,
                payload={"error": str(exc)[:1000]},
            )
        except Exception:
            logger.debug("BOT_RIGHTS_REFRESH_SELECTED_AUDIT_FAILED", exc_info=True)
        await _edit_private_panel(
            callback,
            error_text("Falha ao atualizar direitos", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _edit_private_panel(
        callback,
        success_text("Direitos do bot atualizados", format_bot_rights(rights)),
        security_keyboard(),
    )


@router.callback_query(F.data == "tigrao:rights:diagnostics")
async def tigrao_rights_diagnostics(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode diagnosticar direitos do bot.", show_alert=True)
        return
    try:
        result = await refresh_managed_group_rights(callback.bot, limit=50)
        log_audit_event(
            category="bot_rights",
            action="refresh_managed_groups",
            status="success" if int(result.get("error", 0)) == 0 else "partial",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "total": result.get("total"),
                "admin": result.get("admin"),
                "musical_only": result.get("musical_only"),
                "error": result.get("error"),
            },
        )
    except Exception as exc:
        logger.exception("BOT_RIGHTS_DIAGNOSTICS_FAILED")
        try:
            log_audit_event(
                category="bot_rights",
                action="refresh_managed_groups",
                status="error",
                actor_user_id=callback.from_user.id if callback.from_user else None,
                reason=type(exc).__name__,
                payload={"error": str(exc)[:1000]},
            )
        except Exception:
            logger.debug("BOT_RIGHTS_DIAGNOSTICS_AUDIT_FAILED", exc_info=True)
        await _edit_private_panel(
            callback,
            error_text("Falha no diagnóstico de direitos", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _edit_private_panel(
        callback,
        format_rights_refresh_report(result, max_rows=20),
        security_keyboard(),
    )





async def _send_owner_jsonl_export(callback: CallbackQuery, *, filename: str, data: bytes, caption: str) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria.", show_alert=True)
        return
    payload = data or b""
    if callback.message:
        await callback.message.answer_document(
            BufferedInputFile(payload, filename=filename),
            caption=caption,
        )
    await callback.answer("Export gerado.")


async def _send_owner_signed_export(callback: CallbackQuery, *, export: SignedExport, caption: str) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer_document(
            BufferedInputFile(export.gzip_bytes, filename=export.compressed_filename),
            caption=caption,
        )
        await callback.message.answer_document(
            BufferedInputFile(export.manifest_bytes, filename=export.manifest_filename),
            caption=(
                "Manifesto SHA-256 do export. "
                f"Registros: {export.record_count}. "
                f"gzip_sha256: {export.gzip_sha256}"
            ),
        )
    await callback.answer("Export assinado gerado.")


async def _send_owner_encrypted_export(callback: CallbackQuery, *, export: EncryptedSignedExport, caption: str) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria criptografada.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer_document(
            BufferedInputFile(export.ciphertext_bytes, filename=export.encrypted_filename),
            caption=caption,
        )
        await callback.message.answer_document(
            BufferedInputFile(export.manifest_bytes, filename=export.manifest_filename),
            caption=(
                "Manifesto do export criptografado. "
                f"Registros: {export.record_count}. "
                f"ciphertext_sha256: {export.ciphertext_sha256}"
            ),
        )
    await callback.answer("Export criptografado gerado.")


@router.callback_query(F.data == "tigrao:audit:export")
async def tigrao_audit_export(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria.", show_alert=True)
        return
    try:
        data = export_audit_events_jsonl(limit=AUDIT_EXPORT_LIMIT)
        log_audit_event(
            category="audit_export",
            action="export_audit_events",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"limit": AUDIT_EXPORT_LIMIT, "bytes": len(data)},
        )
    except Exception as exc:
        logger.exception("AUDIT_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar auditoria", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_jsonl_export(
        callback,
        filename="tr3-audit-events.jsonl",
        data=data,
        caption=f"Export de audit_events. Limite: {AUDIT_EXPORT_LIMIT}. Registros em JSONL.",
    )


@router.callback_query(F.data == "tigrao:critical:export")
async def tigrao_critical_export(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar operações críticas.", show_alert=True)
        return
    try:
        data = export_critical_operations_jsonl(limit=CRITICAL_OPERATION_EXPORT_LIMIT)
        log_audit_event(
            category="audit_export",
            action="export_critical_operations",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"limit": CRITICAL_OPERATION_EXPORT_LIMIT, "bytes": len(data)},
        )
    except Exception as exc:
        logger.exception("CRITICAL_OPERATIONS_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar operações", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_jsonl_export(
        callback,
        filename="tr3-critical-operations.jsonl",
        data=data,
        caption=f"Export de critical_operations. Limite: {CRITICAL_OPERATION_EXPORT_LIMIT}. Registros em JSONL.",
    )


@router.callback_query(F.data == "tigrao:audit:export:signed")
async def tigrao_audit_export_signed(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria assinada.", show_alert=True)
        return
    try:
        data = export_audit_events_jsonl(limit=AUDIT_EXPORT_LIMIT)
        export = create_signed_jsonl_export(
            source="audit_events",
            base_filename="tr3-audit-events.jsonl",
            data=data,
            extra={"limit": AUDIT_EXPORT_LIMIT},
        )
        log_audit_event(
            category="audit_export",
            action="export_audit_events_signed",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "limit": AUDIT_EXPORT_LIMIT,
                "records": export.record_count,
                "raw_bytes": len(export.raw_bytes),
                "gzip_bytes": len(export.gzip_bytes),
                "raw_sha256": export.raw_sha256,
                "gzip_sha256": export.gzip_sha256,
                "manifest_filename": export.manifest_filename,
                "key_id": AUDIT_EXPORT_ENCRYPTION_KEY_ID,
            },
        )
    except Exception as exc:
        logger.exception("SIGNED_AUDIT_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar auditoria assinada", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_signed_export(
        callback,
        export=export,
        caption=f"Export audit_events JSONL.GZ assinado. Registros: {export.record_count}. SHA-256 no manifesto.",
    )


@router.callback_query(F.data == "tigrao:critical:export:signed")
async def tigrao_critical_export_signed(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar operações críticas assinadas.", show_alert=True)
        return
    try:
        data = export_critical_operations_jsonl(limit=CRITICAL_OPERATION_EXPORT_LIMIT)
        export = create_signed_jsonl_export(
            source="critical_operations",
            base_filename="tr3-critical-operations.jsonl",
            data=data,
            extra={"limit": CRITICAL_OPERATION_EXPORT_LIMIT},
        )
        log_audit_event(
            category="audit_export",
            action="export_critical_operations_signed",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "limit": CRITICAL_OPERATION_EXPORT_LIMIT,
                "records": export.record_count,
                "raw_bytes": len(export.raw_bytes),
                "gzip_bytes": len(export.gzip_bytes),
                "raw_sha256": export.raw_sha256,
                "gzip_sha256": export.gzip_sha256,
                "manifest_filename": export.manifest_filename,
                "key_id": AUDIT_EXPORT_ENCRYPTION_KEY_ID,
            },
        )
    except Exception as exc:
        logger.exception("SIGNED_CRITICAL_OPERATIONS_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar operações assinadas", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_signed_export(
        callback,
        export=export,
        caption=f"Export critical_operations JSONL.GZ assinado. Registros: {export.record_count}. SHA-256 no manifesto.",
    )


@router.callback_query(F.data == "tigrao:audit:export:encrypted")
async def tigrao_audit_export_encrypted(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar auditoria criptografada.", show_alert=True)
        return
    try:
        data = export_audit_events_jsonl(limit=AUDIT_EXPORT_LIMIT)
        signed = create_signed_jsonl_export(
            source="audit_events",
            base_filename="tr3-audit-events.jsonl",
            data=data,
            extra={"limit": AUDIT_EXPORT_LIMIT, "encrypted": True},
        )
        export = create_encrypted_signed_export(
            signed_export=signed,
            secret=AUDIT_EXPORT_ENCRYPTION_KEY,
            key_id=AUDIT_EXPORT_ENCRYPTION_KEY_ID,
            extra={
                "limit": AUDIT_EXPORT_LIMIT,
                "keyring": keyring_public_summary(
                    current_key_id=AUDIT_EXPORT_ENCRYPTION_KEY_ID,
                    extra_keyring_raw=AUDIT_EXPORT_DECRYPTION_KEYS,
                ),
            },
        )
        log_audit_event(
            category="audit_export",
            action="export_audit_events_encrypted",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "limit": AUDIT_EXPORT_LIMIT,
                "records": export.record_count,
                "ciphertext_bytes": len(export.ciphertext_bytes),
                "ciphertext_sha256": export.ciphertext_sha256,
                "plaintext_gzip_sha256": export.plaintext_gzip_sha256,
                "manifest_filename": export.manifest_filename,
            },
        )
    except EncryptionNotConfigured as exc:
        await _edit_private_panel(
            callback,
            error_text(
                "Criptografia não configurada",
                str(exc),
                "Configure TR3_AUDIT_EXPORT_ENCRYPTION_KEY para habilitar export criptografado.",
            ),
            security_keyboard(),
        )
        return
    except Exception as exc:
        logger.exception("ENCRYPTED_AUDIT_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar auditoria criptografada", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_encrypted_export(
        callback,
        export=export,
        caption=f"Export audit_events JSONL.GZ.ENC. Registros: {export.record_count}. Manifesto inclui SHA-256 e metadados AES-GCM.",
    )


@router.callback_query(F.data == "tigrao:critical:export:encrypted")
async def tigrao_critical_export_encrypted(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode exportar operações críticas criptografadas.", show_alert=True)
        return
    try:
        data = export_critical_operations_jsonl(limit=CRITICAL_OPERATION_EXPORT_LIMIT)
        signed = create_signed_jsonl_export(
            source="critical_operations",
            base_filename="tr3-critical-operations.jsonl",
            data=data,
            extra={"limit": CRITICAL_OPERATION_EXPORT_LIMIT, "encrypted": True},
        )
        export = create_encrypted_signed_export(
            signed_export=signed,
            secret=AUDIT_EXPORT_ENCRYPTION_KEY,
            key_id=AUDIT_EXPORT_ENCRYPTION_KEY_ID,
            extra={
                "limit": CRITICAL_OPERATION_EXPORT_LIMIT,
                "keyring": keyring_public_summary(
                    current_key_id=AUDIT_EXPORT_ENCRYPTION_KEY_ID,
                    extra_keyring_raw=AUDIT_EXPORT_DECRYPTION_KEYS,
                ),
            },
        )
        log_audit_event(
            category="audit_export",
            action="export_critical_operations_encrypted",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "limit": CRITICAL_OPERATION_EXPORT_LIMIT,
                "records": export.record_count,
                "ciphertext_bytes": len(export.ciphertext_bytes),
                "ciphertext_sha256": export.ciphertext_sha256,
                "plaintext_gzip_sha256": export.plaintext_gzip_sha256,
                "manifest_filename": export.manifest_filename,
            },
        )
    except EncryptionNotConfigured as exc:
        await _edit_private_panel(
            callback,
            error_text(
                "Criptografia não configurada",
                str(exc),
                "Configure TR3_AUDIT_EXPORT_ENCRYPTION_KEY para habilitar export criptografado.",
            ),
            security_keyboard(),
        )
        return
    except Exception as exc:
        logger.exception("ENCRYPTED_CRITICAL_OPERATIONS_EXPORT_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha ao exportar operações criptografadas", f"{type(exc).__name__}: {exc}", "Confira logs e tente novamente."),
            security_keyboard(),
        )
        return
    await _send_owner_encrypted_export(
        callback,
        export=export,
        caption=f"Export critical_operations JSONL.GZ.ENC. Registros: {export.record_count}. Manifesto inclui SHA-256 e metadados AES-GCM.",
    )


@router.callback_query(F.data == "tigrao:audit:cleanup")
async def tigrao_audit_cleanup_confirm(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode limpar auditoria.", show_alert=True)
        return
    await _edit_private_panel(
        callback,
        "Limpeza segura de auditoria\n\n"
        f"Audit events mais antigos que {AUDIT_RETENTION_DAYS} dias serão removidos.\n"
        f"Operações críticas finalizadas mais antigas que {CRITICAL_OPERATION_RETENTION_DAYS} dias serão removidas.\n\n"
        "Operações críticas em status intent são preservadas por padrão.\n"
        "Recomendado exportar antes da limpeza.",
        audit_cleanup_confirm_keyboard(),
    )


@router.callback_query(F.data == "tigrao:audit:cleanup:confirm")
async def tigrao_audit_cleanup_execute(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode limpar auditoria.", show_alert=True)
        return
    try:
        audit_deleted = cleanup_audit_events_older_than(AUDIT_RETENTION_DAYS)
        critical_deleted = cleanup_critical_operations_older_than(CRITICAL_OPERATION_RETENTION_DAYS, keep_pending=True)
        log_audit_event(
            category="audit_retention",
            action="cleanup_old_records",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={
                "audit_retention_days": AUDIT_RETENTION_DAYS,
                "critical_operation_retention_days": CRITICAL_OPERATION_RETENTION_DAYS,
                "audit_deleted": audit_deleted,
                "critical_deleted": critical_deleted,
            },
        )
    except Exception as exc:
        logger.exception("AUDIT_RETENTION_CLEANUP_FAILED")
        await _edit_private_panel(
            callback,
            error_text("Falha na limpeza de auditoria", f"{type(exc).__name__}: {exc}", "Nenhuma permissão foi alterada."),
            security_keyboard(),
        )
        return
    await _edit_private_panel(
        callback,
        success_text(
            "Limpeza concluída",
            f"audit_events removidos: {audit_deleted}\ncritical_operations removidas: {critical_deleted}\n"
            f"Retenção audit_events: {AUDIT_RETENTION_DAYS} dias\nRetenção operações: {CRITICAL_OPERATION_RETENTION_DAYS} dias",
        ),
        security_keyboard(),
    )


@router.callback_query(F.data == "tigrao:critical:ops")
async def tigrao_critical_operations(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode ver operações críticas.", show_alert=True)
        return
    rows = list_critical_operations(limit=10)
    try:
        log_audit_event(
            category="critical_operations",
            action="list_recent",
            status="success",
            actor_user_id=callback.from_user.id if callback.from_user else None,
            payload={"count": len(rows)},
        )
    except Exception:
        logger.debug("CRITICAL_OPERATIONS_LIST_AUDIT_FAILED", exc_info=True)
    await _edit_private_panel(callback, format_critical_operations(rows, limit=10), security_keyboard())


@router.callback_query(F.data.startswith("tigrao:critical:replay:"))
async def tigrao_critical_replay_packet(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode gerar pacote de replay.", show_alert=True)
        return
    operation_id = (callback.data or "").rsplit(":", 1)[-1]
    await _edit_private_panel(callback, replay_packet(operation_id), security_keyboard())

@router.callback_query(F.data.startswith("tigrao:security:mode:"))
async def tigrao_security_mode(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode alterar modo de segurança.", show_alert=True)
        return
    mode = (callback.data or "").rsplit(":", 1)[-1]
    if mode not in {"normal", "alert", "restricted"}:
        await callback.answer("Modo inválido.", show_alert=True)
        return
    actor_id = callback.from_user.id if callback.from_user else None
    operation_id = begin_critical_operation(
        category="security",
        action="set_security_mode",
        operation_key=f"security_mode:{mode}",
        actor_user_id=actor_id,
        lock_name="security_mode",
        intent={"mode": mode, "source": "owner_panel"},
    )
    try:
        set_security_mode(mode, reason=f"manual via painel por {actor_id if actor_id else '-'}")
        await send_security_alert(
            callback.bot,
            title="security_mode_changed",
            detail=f"Modo de segurança alterado manualmente para {mode}.",
            severity=mode,
            payload={"actor_user_id": actor_id, "operation_id": operation_id},
            dedupe_key="security_mode_changed",
        )
        finish_critical_operation(operation_id, status="success", result={"mode": mode})
    except Exception as exc:
        finish_critical_operation(operation_id, status="error", result={"error": str(exc)[:1000]}, reason=type(exc).__name__)
        await _edit_private_panel(
            callback,
            error_text("Falha ao alterar modo", f"{type(exc).__name__}: {exc}", "Confira configuração de panic."),
            security_keyboard(),
        )
        return
    await _edit_private_panel(callback, _security_text() + f"\n\nOperação crítica: {operation_id}", security_keyboard())


@router.callback_query(F.data == "tigrao:governance")
async def tigrao_governance(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode acessar governança.", show_alert=True)
        return
    await _edit_private_panel(
        callback,
        await _rights_aware_section_text(
            callback.bot,
            "governança do grupo",
            "Ações estruturais Owner-only. Exigem grupo selecionado e confirmação dupla.",
        ),
        governance_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)),
    )


@router.callback_query(F.data == "tigrao:governance:title")
async def tigrao_governance_title(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode alterar nome do grupo.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        await _edit_private_panel(callback, _need_group_text(), home_keyboard())
        return
    set_action("governance_title_input", waiting_for="customize_title")
    await _edit_private_panel(
        callback,
        "Tigrão — governança: alterar nome\n\n"
        f"Grupo: {_session_group_label()}\n\n"
        "Envie o novo nome. Depois haverá confirmação dupla.",
        governance_keyboard(),
    )


@router.callback_query(F.data == "tigrao:governance:description")
async def tigrao_governance_description(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode alterar descrição do grupo.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        await _edit_private_panel(callback, _need_group_text(), home_keyboard())
        return
    set_action("governance_description_input", waiting_for="customize_bio")
    await _edit_private_panel(
        callback,
        "Tigrão — governança: alterar descrição\n\n"
        f"Grupo: {_session_group_label()}\n\n"
        "Envie a nova descrição. Para apagar, envie apenas ponto: .\n"
        "Depois haverá confirmação dupla.",
        governance_keyboard(),
    )


@router.callback_query(F.data.in_({"tigrao:governance:link_direct", "tigrao:governance:link_approval"}))
async def tigrao_governance_link(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode gerar links de governança.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        await _edit_private_panel(callback, _need_group_text(), home_keyboard())
        return
    action = "governance_link_direct" if callback.data.endswith("link_direct") else "governance_link_approval"
    chat_id = int(session.selected_chat_id)
    _prepare_governance_confirmation(action, chat_id, {})
    await _edit_private_panel(
        callback,
        "Tigrão — confirmação de governança\n\n"
        "Esta ação altera acesso/entrada do grupo e é Owner-only.\n\n"
        f"{_governance_summary(action, chat_id, {})}\n\n"
        "Confirme novamente para executar.",
        governance_confirm_keyboard(),
    )


@router.callback_query(F.data == "tigrao:governance:cancel")
async def tigrao_governance_cancel(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    clear_action()
    await _edit_private_panel(callback, "Tigrão — governança cancelada.", governance_keyboard())


@router.callback_query(F.data == "tigrao:governance:confirm")
async def tigrao_governance_confirm(callback: CallbackQuery) -> None:
    if not _is_root_callback(callback):
        await callback.answer("Somente o Owner pode confirmar governança.", show_alert=True)
        return
    session = get_session()
    chat_id = session.selected_chat_id
    action = session.selected_action
    if not chat_id or not action or not str(action).startswith("governance_") or session.waiting_for != "governance_confirm":
        await _edit_private_panel(
            callback,
            error_text("Confirmação inválida", "Faltam dados ou a sessão de governança expirou.", "Recomece pelo painel de governança."),
            governance_keyboard(),
        )
        return

    payload = dict(session.payload)
    actor_id = callback.from_user.id if callback.from_user else None
    lock_name = _governance_lock_name(int(chat_id), str(action))
    operation_id = begin_critical_operation(
        category="governance",
        action=str(action),
        operation_key=f"governance:{int(chat_id)}:{str(action)}",
        actor_user_id=actor_id,
        chat_id=int(chat_id),
        lock_name=lock_name,
        intent={"payload": payload, "summary": _governance_summary(str(action), int(chat_id), payload)},
    )
    lock = acquire_operational_lock(
        lock_name,
        ttl_seconds=OPERATIONAL_LOCK_TTL_SECONDS,
        metadata={"action": str(action), "chat_id": int(chat_id), "actor_user_id": actor_id, "operation_id": operation_id},
    )
    if not lock.acquired:
        finish_critical_operation(
            operation_id,
            status="blocked",
            result={"lock_owner": lock.owner, "expires_at": lock.expires_at},
            reason="operational_lock_busy",
        )
        _audit_governance(
            action=str(action),
            status="blocked",
            actor_user_id=actor_id,
            chat_id=int(chat_id),
            reason="operational_lock_busy",
            payload={"lock_owner": lock.owner, "expires_at": lock.expires_at, "operation_id": operation_id},
        )
        await _edit_private_panel(
            callback,
            error_text(
                "Governança em execução",
                "Outra operação estrutural para este grupo está em andamento.",
                "Aguarde a conclusão ou a expiração do lock operacional.",
            ),
            governance_keyboard(),
        )
        return
    await callback.answer("Executando governança...")
    try:
        result_text = ""
        result_payload: dict = {"operation_id": operation_id}
        if action == "governance_set_title":
            title = str(payload.get("title") or "").strip()
            await set_group_title(callback.bot, int(chat_id), title)
            result_text = f"Novo nome: {title}"
            result_payload["title"] = title
        elif action == "governance_set_description":
            description = str(payload.get("description") or "")
            await set_group_description(callback.bot, int(chat_id), description)
            result_text = f"Caracteres: {len(description)}"
            result_payload["description_length"] = len(description)
        elif action == "governance_link_direct":
            invite_link = await create_direct_link(callback.bot, int(chat_id))
            result_text = f"Link: {invite_link}"
            result_payload["invite_link_created"] = True
        elif action == "governance_link_approval":
            invite_link = await create_approval_link(callback.bot, int(chat_id))
            result_text = f"Link: {invite_link}"
            result_payload["invite_link_created"] = True
        else:
            finish_critical_operation(operation_id, status="error", result={"action": str(action)}, reason="invalid_action")
            await _edit_private_panel(callback, error_text("Ação inválida", f"{action}", "Recomece pelo painel."), governance_keyboard())
            return

        log_action(chat_id=int(chat_id), action=action, status="success")
        _audit_governance(
            action=action,
            status="success",
            actor_user_id=actor_id,
            chat_id=int(chat_id),
            payload={**payload, "operation_id": operation_id},
        )
        finish_critical_operation(operation_id, status="success", result=result_payload)
        clear_action()
        await _edit_private_panel(
            callback,
            success_text("Governança executada", f"Grupo: {_group_label_for_chat(chat_id)}\nAção: {action}\n{result_text}\nOperação crítica: {operation_id}"),
            governance_keyboard(),
        )
    except Exception as exc:
        log_action(chat_id=int(chat_id), action=str(action), status="error", error_type=type(exc).__name__, error_message=str(exc))
        _audit_governance(
            action=str(action),
            status="error",
            actor_user_id=actor_id,
            chat_id=int(chat_id),
            reason=f"{type(exc).__name__}: {exc}",
            payload={**payload, "operation_id": operation_id},
        )
        finish_critical_operation(operation_id, status="error", result={"error": str(exc)[:1000]}, reason=type(exc).__name__)
        clear_action()
        await _edit_private_panel(
            callback,
            error_text("Falha na governança", f"{type(exc).__name__}: {exc}", "Confira direitos do bot e tente novamente."),
            governance_keyboard(),
        )
    finally:
        release_operational_lock(lock_name, owner=lock.owner)



# Sprint X1 (TR3): Reaction Moderation — callbacks
@router.callback_query(F.data == "tigrao:rmod")
async def tigrao_rmod(callback: CallbackQuery) -> None:
    await _edit_private_panel(
        callback,
        await _rights_aware_section_text(
            callback.bot,
            "moderar reactions",
            "Apague reactions individuais ou todas de uma mensagem, ou silencie quem reagiu.\n"
            "Apagar por link depende do grupo do link; silenciar usa o grupo selecionado.",
        ),
        reactions_mod_keyboard(bot_capabilities=await _selected_bot_capabilities(callback.bot)),
    )


@router.callback_query(F.data == "tigrao:rmod:del_user_msg")
async def tigrao_rmod_del_user_msg(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    set_action("rmod_del_user_msg", waiting_for="rmod_link")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — apagar reaction de 1 pessoa (msg)\n\n"
            "Cole agora o link da mensagem.\n\n"
            "Exemplos:\n"
            "https://t.me/c/1234567890/55\n"
            "https://t.me/nomedogrupo/55"
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:rmod:del_user_chat")
async def tigrao_rmod_del_user_chat(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    # Sprint X3: tenta mostrar picker de reactors recentes do chat
    # antes de pedir @username. Se nada rastreado, cai no fluxo texto.
    reactors = []
    try:
        reactors = reaction_audit_service.list_chat_recent_reactors(
            chat_id=int(session.selected_chat_id),
        )
    except Exception:
        logger.exception("RMOD_PICKER_CHAT_QUERY_FAILED chat=%s", session.selected_chat_id)
    if reactors:
        nonce = _new_picker_nonce()
        set_action("rmod_del_user_chat", waiting_for=None, reactors=reactors, picker_nonce=nonce)
        if callback.message:
            try:
                await callback.message.edit_text(
                    "Tigrão — apagar reactions de 1 pessoa (grupo inteiro)\n\n"
                    f"Grupo: {_session_group_label()}\n"
                    f"Reactors recentes (últimas 24h): {len(reactors)}\n\n"
                    "Toque na pessoa cujas reactions devem ser apagadas no grupo todo.",
                    reply_markup=rmod_reactors_picker_keyboard(reactors, nonce),
                )
            except TelegramBadRequest:
                # Mensagem antiga/não editável → manda nova.
                await callback.message.answer(
                    f"Tigrão — escolha o reactor ({len(reactors)} recentes)",
                    reply_markup=rmod_reactors_picker_keyboard(reactors, nonce),
                )
        await callback.answer()
        return
    set_action("rmod_del_user_chat", waiting_for="rmod_user")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — apagar reactions de 1 pessoa (grupo inteiro)\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Sem reactors rastreados nas últimas 24h.\n"
            "Envie agora o user_id numérico OU @username do alvo.\n"
            "Vai apagar até 10000 reactions RECENTES dessa pessoa em TODAS as mensagens deste grupo."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:rmod:del_all_msg")
async def tigrao_rmod_del_all_msg(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    set_action("rmod_del_all_msg", waiting_for="rmod_link")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — apagar TODAS reactions desta msg\n\n"
            "Cole agora o link da mensagem.\n\n"
            "Atenção: vai tentar remover todas as reactions desta mensagem (incluindo as do próprio bot).\n"
            "Observação: na Bot API atual o escopo por mensagem pode ter mudado — se a chamada falhar, use a opção 'Apagar reactions de 1 pessoa (grupo)' por usuário."
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:rmod:mute_react")
async def tigrao_rmod_mute_react(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if not session.selected_chat_id:
        if callback.message:
            await callback.message.edit_text(_need_group_text(), reply_markup=home_keyboard())
        await callback.answer()
        return
    # Sprint X3: picker antes de pedir @username.
    reactors = []
    try:
        reactors = reaction_audit_service.list_chat_recent_reactors(
            chat_id=int(session.selected_chat_id),
        )
    except Exception:
        logger.exception("RMOD_PICKER_MUTE_QUERY_FAILED chat=%s", session.selected_chat_id)
    if reactors:
        nonce = _new_picker_nonce()
        set_action("rmod_mute_react", waiting_for=None, reactors=reactors, picker_nonce=nonce)
        if callback.message:
            try:
                await callback.message.edit_text(
                    "Tigrão — silenciar reactor\n\n"
                    f"Grupo: {_session_group_label()}\n"
                    f"Reactors recentes (últimas 24h): {len(reactors)}\n\n"
                    "Toque na pessoa que vai perder a permissão de reagir.",
                    reply_markup=rmod_reactors_picker_keyboard(reactors, nonce),
                )
            except TelegramBadRequest:
                await callback.message.answer(
                    f"Tigrão — silenciar reactor ({len(reactors)} recentes)",
                    reply_markup=rmod_reactors_picker_keyboard(reactors, nonce),
                )
        await callback.answer()
        return
    set_action("rmod_mute_react", waiting_for="rmod_user")
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — silenciar reactor\n\n"
            f"Grupo: {_session_group_label()}\n\n"
            "Sem reactors rastreados nas últimas 24h.\n"
            "Envie agora o user_id numérico OU @username do alvo.\n"
            "Apenas a permissão de reagir será removida; o resto fica preservado."
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tigrao:rmod:dur:"))
async def tigrao_rmod_duration(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    if session.selected_action != "rmod_mute_react":
        await callback.answer("Fluxo inválido.", show_alert=True)
        return
    raw = (callback.data or "").rsplit(":", 1)[-1]
    try:
        duration = parse_duration(raw)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    session.payload["duration"] = duration
    session.payload["duration_label"] = raw
    touch_session()
    if callback.message:
        try:
            await callback.message.edit_text(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
        except TelegramBadRequest:
            await callback.message.answer(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("tigrao:rmod:pick:"))
async def tigrao_rmod_pick(callback: CallbackQuery) -> None:
    """Sprint X3: escolhe reactor a partir do picker.

    callback_data: `tigrao:rmod:pick:<nonce>:<user_id>`
    - Valida nonce vs session.payload['picker_nonce']: clique em
      picker antigo (após owner abrir outro fluxo) é rejeitado.
    - user_id é identidade imutável; lookup na lista de reactors
      só serve pra recuperar o label amigável.
    Avança o fluxo: mute → escolher duração; del_* → confirmação.
    """
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    action = session.selected_action or ""
    if action not in {"rmod_del_user_msg", "rmod_del_user_chat", "rmod_mute_react"}:
        await callback.answer("Fluxo inválido.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    # ['tigrao','rmod','pick',nonce,user_id] → exatamente 5 partes
    if len(parts) != 5:
        await callback.answer("Callback malformado. Reabra o fluxo.", show_alert=True)
        return
    nonce, user_id_raw = parts[3], parts[4]
    expected_nonce = session.payload.get("picker_nonce")
    if not expected_nonce or nonce != expected_nonce:
        await callback.answer(
            "Esse picker é de um fluxo antigo. Reabra o menu Moderar Reactions.",
            show_alert=True,
        )
        return
    try:
        target_user_id = int(user_id_raw)
    except ValueError:
        await callback.answer("user_id inválido no callback.", show_alert=True)
        return
    if is_moderator_user(target_user_id):
        await callback.answer("Você não pode moderar um moderador.", show_alert=True)
        return
    reactors = session.payload.get("reactors") or []
    reactor = next((r for r in reactors if int(r.get("user_id", 0)) == target_user_id), None)
    if reactor is None:
        await callback.answer("Seleção fora da lista atual.", show_alert=True)
        return
    target_label = (
        reactor.get("user_name")
        or (f"@{reactor['user_username']}" if reactor.get("user_username") else None)
        or str(target_user_id)
    )
    session.payload["target_user_id"] = target_user_id
    session.payload["target_label"] = target_label
    # Invalida o picker (qualquer clique posterior em outro botão dessa
    # mesma keyboard cai no nonce-mismatch) e libera memória da lista.
    session.payload.pop("reactors", None)
    session.payload.pop("picker_nonce", None)
    touch_session()
    if action == "rmod_mute_react":
        if callback.message:
            try:
                await callback.message.edit_text(
                    "Tigrão — duração do silêncio de reactions\n\n"
                    f"Grupo: {_session_group_label()}\n"
                    f"Alvo: {target_label} ({target_user_id})\n\n"
                    "Escolha por quanto tempo o alvo ficará sem poder reagir.",
                    reply_markup=rmod_duration_keyboard(),
                )
            except TelegramBadRequest:
                await callback.message.answer(
                    f"Alvo: {target_label} ({target_user_id}) — escolha a duração:",
                    reply_markup=rmod_duration_keyboard(),
                )
        await callback.answer()
        return
    # del_user_msg ou del_user_chat → confirmação direta
    if callback.message:
        try:
            await callback.message.edit_text(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
        except TelegramBadRequest:
            await callback.message.answer(_rmod_confirm_text(), reply_markup=rmod_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("tigrao:rmod:manual"))
async def tigrao_rmod_manual(callback: CallbackQuery) -> None:
    """Sprint X3: fallback do picker — pede user_id/@username em texto.

    callback_data: `tigrao:rmod:manual:<nonce>` (nonce bind ao picker
    ativo). Rejeita cliques em pickers antigos pra evitar que um botão
    stale altere o fluxo atual.

    Reaproveita o handler `rmod_user` existente (waiting_for='rmod_user').
    Mantém compat com cenários onde o reactor não está no audit (msg
    antiga, reactions pré-deploy do bot como admin, etc).
    """
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    action = session.selected_action or ""
    if action not in {"rmod_del_user_msg", "rmod_del_user_chat", "rmod_mute_react"}:
        await callback.answer("Fluxo inválido.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    # ['tigrao','rmod','manual',nonce] → 4 partes
    if len(parts) != 4:
        await callback.answer("Callback malformado. Reabra o fluxo.", show_alert=True)
        return
    nonce = parts[3]
    expected_nonce = session.payload.get("picker_nonce")
    if not expected_nonce or nonce != expected_nonce:
        await callback.answer(
            "Esse botão é de um fluxo antigo. Reabra o menu Moderar Reactions.",
            show_alert=True,
        )
        return
    session.payload.pop("reactors", None)
    session.payload.pop("picker_nonce", None)
    session.waiting_for = "rmod_user"
    touch_session()
    if callback.message:
        try:
            await callback.message.edit_text(
                "Tigrão — digitar alvo manualmente\n\n"
                f"Grupo: {_session_group_label()}\n\n"
                "Envie agora o user_id numérico OU @username do alvo.\n"
                "Dica: @username só resolve se o bot já interagiu com a pessoa antes."
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "Tigrão — envie agora o user_id numérico OU @username do alvo."
            )
    await callback.answer()


@router.callback_query(F.data == "tigrao:rmod:cancel")
async def tigrao_rmod_cancel(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    clear_action()
    if callback.message:
        await callback.message.edit_text(
            "Tigrão — moderação de reactions cancelada.",
            reply_markup=reactions_mod_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "tigrao:rmod:confirm")
async def tigrao_rmod_confirm(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    session = get_session()
    action = session.selected_action or ""
    p = dict(session.payload)
    bot = callback.bot

    if action not in {"rmod_del_user_msg", "rmod_del_user_chat", "rmod_del_all_msg", "rmod_mute_react"}:
        await callback.answer("Fluxo inválido.", show_alert=True)
        return

    await callback.answer("Executando ação...")
    if callback.message:
        await callback.message.edit_text(
            f"Tigrão — executando {ACTION_LABELS.get(action, action)}...",
            reply_markup=None,
        )

    chat_id_for_log: int | None = None
    target_for_log: int | None = None

    try:
        if action == "rmod_del_user_msg":
            link_chat_id = p.get("link_chat_id")
            link_msg_id = p.get("link_msg_id")
            target_user_id = p.get("target_user_id")
            if link_chat_id is None or link_msg_id is None or target_user_id is None:
                raise RuntimeError("dados incompletos no payload")
            chat_id_for_log = link_chat_id if isinstance(link_chat_id, int) else None
            target_for_log = int(target_user_id)
            await delete_message_reaction(bot, link_chat_id, int(link_msg_id), int(target_user_id))
            details = (
                f"Mensagem: {link_chat_id} / {link_msg_id}\n"
                f"Alvo: {p.get('target_label')} ({target_user_id})\n"
                "Reaction da pessoa nessa mensagem removida."
            )
            title = "Reaction removida"

        elif action == "rmod_del_user_chat":
            chat_id = session.selected_chat_id
            target_user_id = p.get("target_user_id")
            if not chat_id or target_user_id is None:
                raise RuntimeError("dados incompletos no payload")
            chat_id_for_log = int(chat_id)
            target_for_log = int(target_user_id)
            await delete_all_message_reactions(
                bot, int(chat_id), user_id=int(target_user_id)
            )
            details = (
                f"Grupo: {_group_label_for_chat(chat_id)}\n"
                f"Alvo: {p.get('target_label')} ({target_user_id})\n"
                "Até 10000 reactions recentes desta pessoa no grupo foram removidas."
            )
            title = "Reactions da pessoa removidas"

        elif action == "rmod_del_all_msg":
            link_chat_id = p.get("link_chat_id")
            link_msg_id = p.get("link_msg_id")
            if link_chat_id is None or link_msg_id is None:
                raise RuntimeError("dados incompletos no payload")
            chat_id_for_log = link_chat_id if isinstance(link_chat_id, int) else None

            # Bot API 10.0: deleteAllMessageReactions NÃO aceita message_id;
            # ela remove até 10000 reactions recentes de um user/chat ator no
            # chat inteiro. Para limpar uma mensagem específica, iteramos os
            # reactors conhecidos pelo reaction_audit e usamos
            # deleteMessageReaction(chat_id, message_id, user_id).
            if not isinstance(link_chat_id, int):
                raise RuntimeError(
                    "limpeza por mensagem exige chat_id numérico; use um link t.me/c/... recente"
                )
            reactors = reaction_audit_service.list_message_reactors(
                int(link_chat_id), int(link_msg_id)
            )
            if not reactors:
                raise RuntimeError(
                    "nenhum reactor conhecido para esta mensagem nas últimas 24h"
                )
            removed_count = 0
            for reactor in reactors:
                await delete_message_reaction(
                    bot, int(link_chat_id), int(link_msg_id), int(reactor["user_id"])
                )
                removed_count += 1
            details = (
                f"Mensagem: {link_chat_id} / {link_msg_id}\n"
                f"Reactions removidas de {removed_count} reactor(es) conhecido(s)."
            )
            title = "Reactions da mensagem removidas"

        else:  # rmod_mute_react
            chat_id = session.selected_chat_id
            target_user_id = p.get("target_user_id")
            duration = p.get("duration")
            if not chat_id or target_user_id is None or duration is None:
                raise RuntimeError("dados incompletos no payload")
            chat_id_for_log = int(chat_id)
            target_for_log = int(target_user_id)
            await mute_reactions(bot, int(chat_id), int(target_user_id), duration)
            details = (
                f"Grupo: {_group_label_for_chat(chat_id)}\n"
                f"Alvo: {p.get('target_label')} ({target_user_id})\n"
                f"Duração: {p.get('duration_label')}\n"
                "Permissão de reagir removida (outras permissões preservadas)."
            )
            title = "Reactor silenciado"

        log_action(chat_id=chat_id_for_log, action=action, target_user_id=target_for_log, status="success")
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                success_text(title, details),
                reply_markup=reactions_mod_keyboard(),
            )

    except TelegramForbiddenError as exc:
        log_action(chat_id=chat_id_for_log, action=action, target_user_id=target_for_log,
                   status="error", error_type=type(exc).__name__, error_message=str(exc))
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text(
                    "Permissão insuficiente",
                    f"O Telegram recusou a ação. Erro: {type(exc).__name__}: {exc}",
                    "Confira se o bot é administrador e tem can_delete_messages / can_restrict_members.",
                ),
                reply_markup=reactions_mod_keyboard(),
            )
    except TelegramBadRequest as exc:
        log_action(chat_id=chat_id_for_log, action=action, target_user_id=target_for_log,
                   status="error", error_type=type(exc).__name__, error_message=str(exc))
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text(
                    "Telegram recusou a operação",
                    f"{type(exc).__name__}: {exc}",
                    "Possíveis causas: mensagem não existe, reaction já removida, user não está no grupo, ou método não suportado para reactions de terceiros.",
                ),
                reply_markup=reactions_mod_keyboard(),
            )
    except Exception as exc:
        log_action(chat_id=chat_id_for_log, action=action, target_user_id=target_for_log,
                   status="error", error_type=type(exc).__name__, error_message=str(exc))
        clear_action()
        if callback.message:
            await callback.message.edit_text(
                error_text("Falha ao executar", f"{type(exc).__name__}: {exc}", "Confira o link/alvo e as permissões do bot."),
                reply_markup=reactions_mod_keyboard(),
            )


@router.callback_query(F.data == "tigrao:close")
async def tigrao_close(callback: CallbackQuery) -> None:
    if not is_owner_callback(callback):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text("Tigrão — painel fechado.")
    await callback.answer()
