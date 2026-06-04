from __future__ import annotations

from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def _button(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    """Cria um InlineKeyboardButton.

    `style` (Bot API 10.0): "danger" / "success" / "primary". Suportado
    nativamente por aiogram 3.27 — sem necessidade de fallback.
    """
    kwargs: dict = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def _copy_button(text: str, value: str) -> InlineKeyboardButton:
    """Botão de copiar texto pra área de transferência (Bot API 10.0)."""
    return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value), style="primary")


def _capability_allowed(capabilities: set[str] | None, capability: str) -> bool:
    """None preserva compatibilidade: sem snapshot, não filtra."""
    return capabilities is None or capability in capabilities


def _missing_capability_button(label: str, capability: str) -> InlineKeyboardButton:
    return _button(f"Indisponível: {label}", f"tigrao:rights:missing:{capability}", "danger")


def _capability_button(
    label: str,
    callback_data: str,
    capability: str,
    capabilities: set[str] | None,
    style: str | None = "primary",
) -> InlineKeyboardButton:
    if _capability_allowed(capabilities, capability):
        return _button(label, callback_data, style)
    return _missing_capability_button(label, capability)


def _back_close_rows() -> list[list[InlineKeyboardButton]]:
    return [[_button("Voltar", "tigrao:home", "primary"), _button("Fechar", "tigrao:close", "danger")]]


def entry_keyboard(*, is_root: bool, can_delegate: bool, can_radio: bool) -> InlineKeyboardMarkup:
    """Painel de entrada do /tigrao.

    O /tigrao não é mais o painel de moderação completo. Ele vira um
    roteador privado para os painéis disponíveis ao usuário.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if is_root:
        rows.append([_button("Painel Owner", "owner:home", "primary")])
    if can_delegate:
        rows.append([_button("Moderação delegada", "tigrao:home", "primary")])
    if can_radio:
        rows.append([_button("Radio", "radio:home", "primary")])
    rows.append([_button("Fechar", "tigrao:close", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_home_keyboard() -> InlineKeyboardMarkup:
    """Painel Owner: moderação avançada, governança e segurança.

    Personalização/postagens ficam fora daqui e entram no painel Radio.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Escolher grupo", "tigrao:groups", "primary")],
            [_button("Ações de usuário", "tigrao:user_actions", "primary"), _button("Links", "tigrao:links", "primary")],
            [_button("Filtros DDX", "tigrao:ddx", "primary"), _button("Mensagens", "tigrao:messages", "primary")],
            [_button("Moderar Reactions", "tigrao:rmod", "primary")],
            [_button("Moderadores", "tigrao:moderators", "primary"), _button("Governança", "tigrao:governance", "primary")],
            [_button("Segurança", "tigrao:security", "primary"), _button("Logs", "tigrao:logs", "primary")],
            [_button("Entrada /tigrao", "tigrao:entry", "primary"), _button("Fechar", "tigrao:close", "danger")],
        ]
    )


def delegate_home_keyboard() -> InlineKeyboardMarkup:
    """Painel de moderação para membros delegados.

    Não mostra governança, segurança, moderadores ou Radio.
    As permissões continuam sendo checadas por ação.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Escolher grupo", "tigrao:groups", "primary")],
            [_button("Ações de usuário", "tigrao:user_actions", "primary")],
            [_button("Filtros DDX", "tigrao:ddx", "primary"), _button("Mensagens", "tigrao:messages", "primary")],
            [_button("Moderar Reactions", "tigrao:rmod", "primary")],
            [_button("Logs", "tigrao:logs", "primary")],
            [_button("Entrada /tigrao", "tigrao:entry", "primary"), _button("Fechar", "tigrao:close", "danger")],
        ]
    )


def home_keyboard() -> InlineKeyboardMarkup:
    """Compatibilidade: chamadas antigas continuam abrindo o painel Owner."""
    return owner_home_keyboard()


def radio_keyboard(
    *,
    allowed_permissions: set[str] | None = None,
    is_root: bool = True,
    has_selected_chat: bool = True,
    bot_capabilities: set[str] | None = None,
) -> InlineKeyboardMarkup:
    """Painel Radio filtrado por permissão.

    Por compatibilidade, chamada sem argumentos mostra tudo para o Owner.
    Para delegados, o router passa `allowed_permissions` do grupo selecionado.
    """
    allowed = set(allowed_permissions or ())

    def can(permission: str) -> bool:
        return is_root or permission in allowed

    rows: list[list[InlineKeyboardButton]] = [[_button("Escolher grupo", "tigrao:groups", "primary")]]
    if not is_root and not has_selected_chat:
        rows.append([_button("Entrada /tigrao", "tigrao:entry", "primary"), _button("Fechar", "tigrao:close", "danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if can("radio.post_text"):
        rows.append([_button("Enviar mensagem", "tigrao:message:send", "primary")])
    if can("radio.post_text") and can("radio.pin"):
        rows.append([_capability_button("Enviar e fixar", "tigrao:message:pin", "pin", bot_capabilities, "primary")])
    if can("radio.post_media"):
        rows.append([_button("Enviar mídia", "tigrao:message:media", "primary")])
    if can("radio.post_media") and can("radio.pin"):
        rows.append([_capability_button("Enviar mídia e fixar", "tigrao:message:media_pin", "pin", bot_capabilities, "primary")])

    template_row: list[InlineKeyboardButton] = []
    if can("radio.templates.use") or can("radio.templates.manage"):
        template_row.append(_button("Templates", "radio:templates", "primary"))
    if can("radio.history.read"):
        template_row.append(_button("Histórico", "radio:history", "primary"))
    if template_row:
        rows.append(template_row)

    ops_row: list[InlineKeyboardButton] = []
    if can("radio.schedule"):
        ops_row.append(_button("Agendamentos", "radio:schedules", "primary"))
    if can("radio.quiet_hours.manage"):
        ops_row.append(_button("Janela de silêncio", "radio:quiet", "primary"))
    if ops_row:
        rows.append(ops_row)

    if can("radio.broadcast"):
        rows.append([_button("Enviar para todos", "radio:broadcast", "danger")])
    rows.append([_button("Entrada /tigrao", "tigrao:entry", "primary"), _button("Fechar", "tigrao:close", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radio_draft_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmação de rascunho do Radio antes de publicar no grupo."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar envio", "radio:draft:confirm", "success")],
            [_button("Cancelar rascunho", "radio:draft:cancel", "danger")],
            [_button("Voltar ao Radio", "radio:home", "primary")],
        ]
    )


def radio_templates_keyboard(
    templates: list[dict],
    *,
    page: int = 0,
    has_next: bool = False,
    can_manage: bool = True,
) -> InlineKeyboardMarkup:
    """Lista paginada de templates do Radio."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_manage:
        rows.append([_button("Criar template", "radio:templates:create", "primary")])
    for template in templates[:10]:
        template_id = int(template["id"])
        name = str(template.get("name") or template_id)
        label = name if len(name) <= 42 else name[:39] + "..."
        rows.append([_button(label, f"radio:template:use:{template_id}", "primary")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_button("◀ Página anterior", f"radio:templates:page:{page - 1}", "primary"))
    if has_next:
        nav.append(_button("Próxima página ▶", f"radio:templates:page:{page + 1}", "primary"))
    if nav:
        rows.append(nav)
    rows.append([_button("Voltar ao Radio", "radio:home", "primary"), _button("Fechar", "tigrao:close", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radio_template_manage_keyboard(template_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Usar template", f"radio:template:use:{template_id}", "success")],
            [_button("Apagar template", f"radio:template:delete:{template_id}", "danger")],
            [_button("Templates", "radio:templates", "primary"), _button("Voltar ao Radio", "radio:home", "primary")],
        ]
    )


def radio_history_keyboard(*, page: int = 0, has_next: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[_button("Atualizar histórico", f"radio:history:page:{page}", "primary")]]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_button("◀ Página anterior", f"radio:history:page:{page - 1}", "primary"))
    if has_next:
        nav.append(_button("Próxima página ▶", f"radio:history:page:{page + 1}", "primary"))
    if nav:
        rows.append(nav)
    rows.append([_button("Voltar ao Radio", "radio:home", "primary"), _button("Fechar", "tigrao:close", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radio_schedules_keyboard(*, page: int = 0, has_next: bool = False, can_create: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_create:
        rows.append([_button("Criar agendamento", "radio:schedules:create", "primary")])
        rows.append([_button("Rodar devidos agora", "radio:schedules:run", "primary")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_button("◀ Página anterior", f"radio:schedules:page:{page - 1}", "primary"))
    if has_next:
        nav.append(_button("Próxima página ▶", f"radio:schedules:page:{page + 1}", "primary"))
    if nav:
        rows.append(nav)
    rows.append([_button("Voltar ao Radio", "radio:home", "primary"), _button("Fechar", "tigrao:close", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radio_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar envio para todos", "radio:broadcast:confirm", "danger")],
            [_button("Cancelar broadcast", "radio:broadcast:cancel", "primary")],
            [_button("Voltar ao Radio", "radio:home", "primary")],
        ]
    )


def radio_quiet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Configurar janela", "radio:quiet:set", "primary")],
            [_button("Desativar janela", "radio:quiet:off", "danger")],
            [_button("Voltar ao Radio", "radio:home", "primary"), _button("Fechar", "tigrao:close", "danger")],
        ]
    )


def reactions_mod_keyboard(*, bot_capabilities: set[str] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [_capability_button("Apagar reaction de 1 pessoa (msg)", "tigrao:rmod:del_user_msg", "delete", bot_capabilities, "danger")],
        [_capability_button("Apagar reactions de 1 pessoa (grupo)", "tigrao:rmod:del_user_chat", "delete", bot_capabilities, "danger")],
        [_capability_button("Apagar TODAS reactions desta msg", "tigrao:rmod:del_all_msg", "delete", bot_capabilities, "danger")],
        [_capability_button("Silenciar reactor", "tigrao:rmod:mute_react", "restrict", bot_capabilities, "danger")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rmod_reactors_picker_keyboard(reactors: list[dict], nonce: str) -> InlineKeyboardMarkup:
    """Sprint X3: picker de reactors (1 botão por user).

    `reactors` é a lista (já ordenada e truncada pelo service) salva em
    `session.payload['reactors']`. `nonce` é um token curto único por
    render do picker, persistido em `session.payload['picker_nonce']`.

    Callback format: `tigrao:rmod:pick:<nonce>:<user_id>`
    - nonce: invalida cliques em pickers antigos quando um novo é
      aberto (evita resolver pro user errado se o owner ignora um
      picker antigo no histórico e abre outro fluxo).
    - user_id: identidade imutável (não depende de índice).

    Layout: 1 user por linha (apenas nome — emojis das reactions foram
    removidos pela política sem-emoji na interface). Linhas finais com
    fallback "digitar manualmente" e "cancelar". O botão "Voltar" leva
    ao menu rmod (não cancela o fluxo todo).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for r in reactors:
        name = (
            r.get("user_name")
            or (f"@{r['user_username']}" if r.get("user_username") else None)
            or str(r.get("user_id"))
        )
        label = str(name)
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append([_button(label, f"tigrao:rmod:pick:{nonce}:{r['user_id']}", "primary")])
    rows.append([_button("Digitar manualmente", f"tigrao:rmod:manual:{nonce}", "primary")])
    rows.append([_button("Voltar", "tigrao:rmod", "primary"), _button("Cancelar", "tigrao:rmod:cancel", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rmod_duration_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("10 min", "tigrao:rmod:dur:10m", "primary"), _button("1 hora", "tigrao:rmod:dur:1h", "primary")],
        [_button("6 horas", "tigrao:rmod:dur:6h", "primary"), _button("24 horas", "tigrao:rmod:dur:24h", "primary")],
        [_button("7 dias", "tigrao:rmod:dur:7d", "primary"), _button("Indefinido", "tigrao:rmod:dur:i", "danger")],
        [_button("Cancelar", "tigrao:rmod:cancel", "danger")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rmod_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar", "tigrao:rmod:confirm", "success")],
            [_button("Cancelar", "tigrao:rmod:cancel", "danger")],
            [_button("Voltar", "tigrao:rmod", "primary")],
        ]
    )


def groups_keyboard(groups: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups[:10]:
        chat_id = int(group["chat_id"])
        title = str(group.get("title") or chat_id)
        label = title if len(title) <= 40 else title[:37] + "..."
        rows.append([_button(label, f"tigrao:group:{chat_id}", "primary")])
    rows.append([_button("Digitar chat_id", "tigrao:group:manual", "primary")])
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_actions_keyboard(*, bot_capabilities: set[str] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            _capability_button("Banir", "tigrao:action:ban", "restrict", bot_capabilities, "danger"),
            _capability_button("Desbanir", "tigrao:action:unban", "restrict", bot_capabilities, "success"),
        ],
        [
            _capability_button("Mutar", "tigrao:action:mute", "restrict", bot_capabilities, "danger"),
            _capability_button("Desmutar", "tigrao:action:unmute", "restrict", bot_capabilities, "success"),
        ],
        [_capability_button("Aprovar entrada", "tigrao:action:approve", "invite", bot_capabilities, "success")],
        [_capability_button("Resetar entrada", "tigrao:action:reset", "restrict", bot_capabilities, "danger")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audit_cleanup_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar limpeza antiga", "tigrao:audit:cleanup:confirm", "danger")],
            [_button("Cancelar", "tigrao:security", "primary")],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar", "tigrao:confirm", "success")],
            [_button("Cancelar", "tigrao:cancel", "danger")],
            [_button("Voltar", "tigrao:user_actions", "primary")],
        ]
    )


def links_keyboard(*, bot_capabilities: set[str] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [_capability_button("Gerar link direto", "tigrao:link:direct", "invite", bot_capabilities, "primary")],
        [_capability_button("Gerar link com aprovação", "tigrao:link:approval", "invite", bot_capabilities, "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def link_result_keyboard(invite_link: str) -> InlineKeyboardMarkup:
    """Sprint X5: keyboard pós-criação de link com botão Copiar nativo
    (Bot API 10.0 CopyTextButton)."""
    rows: list[list[InlineKeyboardButton]] = [[_copy_button("Copiar link", invite_link)]]
    rows.append([_button("Gerar outro link direto", "tigrao:link:direct", "primary")])
    rows.append([_button("Gerar outro com aprovação", "tigrao:link:approval", "primary")])
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def messages_keyboard(*, bot_capabilities: set[str] | None = None) -> InlineKeyboardMarkup:
    rows = [[_capability_button("Apagar por link", "tigrao:message:delete_link", "delete", bot_capabilities, "danger")]]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def customize_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("Enviar mensagem", "tigrao:message:send", "primary")],
        [_button("Enviar e fixar", "tigrao:message:pin", "primary")],
        [_button("Enviar mídia", "tigrao:message:media", "primary")],
        [_button("Enviar mídia e fixar", "tigrao:message:media_pin", "primary")],
        [_button("Alterar foto do grupo", "tigrao:customize:photo", "primary")],
        [_button("Alterar nome", "tigrao:customize:title", "primary"), _button("Alterar bio", "tigrao:customize:bio", "primary")],
        [_button("Tag de membro", "tigrao:customize:member_tag", "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ddx_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("Adicionar filtro", "tigrao:ddx:add", "primary")],
        [_button("Remover filtro", "tigrao:ddx:remove", "primary")],
        [_button("Listar filtros", "tigrao:ddx:list", "primary")],
        [_button("Desligar DDX", "tigrao:ddx:off", "primary")],
        [_button("Filtros DDX 10min", "tigrao:ddx_soft:menu", "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ddx_soft_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("Adicionar filtro 10min", "tigrao:ddx_soft:add", "primary")],
        [_button("Remover filtro 10min", "tigrao:ddx_soft:remove", "primary")],
        [_button("Listar filtros 10min", "tigrao:ddx_soft:list", "primary")],
        [_button("Desligar DDX 10min", "tigrao:ddx_soft:off", "primary")],
        [_button("Voltar para DDX", "tigrao:ddx", "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def logs_keyboard() -> InlineKeyboardMarkup:
    rows = [[_button("Atualizar logs", "tigrao:logs:refresh", "primary")]]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderators_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("Conceder permissão", "tigrao:moderators:grant", "success")],
        [_button("Revogar permissão", "tigrao:moderators:revoke", "danger")],
        [_button("Listar grants", "tigrao:moderators:list", "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def governance_keyboard(*, bot_capabilities: set[str] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [_capability_button("Alterar nome", "tigrao:governance:title", "change_info", bot_capabilities, "primary")],
        [_capability_button("Alterar descrição", "tigrao:governance:description", "change_info", bot_capabilities, "primary")],
        [_capability_button("Gerar link direto", "tigrao:governance:link_direct", "invite", bot_capabilities, "primary")],
        [_capability_button("Gerar link com aprovação", "tigrao:governance:link_approval", "invite", bot_capabilities, "primary")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def governance_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Confirmar governança", "tigrao:governance:confirm", "success")],
            [_button("Cancelar", "tigrao:governance:cancel", "danger")],
            [_button("Voltar", "tigrao:governance", "primary")],
        ]
    )


def security_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_button("Atualizar status", "tigrao:security", "primary"), _button("Rodar check agora", "tigrao:security:check", "primary")],
        [_button("Modo alerta", "tigrao:security:mode:alert", "primary"), _button("Modo restrito", "tigrao:security:mode:restricted", "danger")],
        [_button("Retomar normal", "tigrao:security:mode:normal", "success")],
        [_button("Ver audit log", "tigrao:security:audit", "primary")],
        [_button("Operações críticas", "tigrao:critical:ops", "primary")],
        [_button("Exportar auditoria", "tigrao:audit:export", "primary"), _button("Exportar operações", "tigrao:critical:export", "primary")],
        [_button("Exportar auditoria .gz", "tigrao:audit:export:signed", "primary"), _button("Exportar operações .gz", "tigrao:critical:export:signed", "primary")],
        [_button("Exportar auditoria .enc", "tigrao:audit:export:encrypted", "primary"), _button("Exportar operações .enc", "tigrao:critical:export:encrypted", "primary")],
        [_button("Limpar auditoria antiga", "tigrao:audit:cleanup", "danger")],
        [_button("Atualizar direitos do grupo", "tigrao:rights:refresh_selected", "primary")],
        [_button("Diagnóstico direitos todos", "tigrao:rights:diagnostics", "primary")],
        [_button("Ressincronizar menus", "tigrao:commands:resync", "primary")],
        [_button("Diagnóstico sessões", "tigrao:sessions:diag", "primary"), _button("Limpar sessões expiradas", "tigrao:sessions:cleanup", "danger")],
        [_button("Sessões persistidas", "tigrao:sessions:persisted", "primary"), _button("Locks operacionais", "tigrao:locks:diag", "primary")],
        [_button("Limpar locks expirados", "tigrao:locks:cleanup", "danger")],
    ]
    rows.extend(_back_close_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)
