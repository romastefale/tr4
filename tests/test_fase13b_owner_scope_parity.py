from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tctl_gets_owner_only_entries_and_direct_link_tools() -> None:
    show = read("app/bot/show_owner.py")
    assert 'InlineKeyboardButton(text="Exceções 24h", callback_data="show:exceptions"), InlineKeyboardButton(text="Entradas", callback_data="show:entries")' in show
    assert 'criar_link_direto_owner' in show
    assert 'executar_pedido_entrada' in show
    assert 'reset_join_request_owner' in show
    assert 'action in {"ent_ap", "ent_rej", "ent_reset"}' in show
    assert 'action == "direct_link"' in show


def test_tgov_owner_command_is_private_only_and_contains_group_identity_send_and_tag() -> None:
    main = read("app/main.py")
    setup = read("app/bot/setup_commands.py")
    tgov = read("app/bot/tgov_owner.py")
    assert 'from app.bot.tgov_owner import router as tgov_owner_router' in main
    assert 'dispatcher.include_router(tgov_owner_router)' in main
    private_block = setup.split("_PRIVATE_COMMANDS", 1)[1]
    public_block = setup.split("_PRIVATE_COMMANDS", 1)[0]
    assert 'CommandDef("tgov", "Owner group governance")' in private_block
    assert 'CommandDef("tgov"' not in public_block
    assert '@router.message(Command("tgov"))' in tgov
    assert 'message.chat.type != "private"' in tgov
    assert 'await message.delete()' in tgov
    for needle in (
        'ajuste="grupo.titulo"',
        'ajuste="grupo.descricao"',
        'ajuste="grupo.foto.remover"',
        'ajuste="mensagens.enviar"',
        'ajuste="mensagens.enviar_foto"',
        'ajuste="membros.tag.definir"',
    ):
        assert needle in tgov


def test_entries_helpers_are_owner_safe_and_direct_link_is_not_join_request() -> None:
    entradas = read("app/equalizador/entradas.py")
    assert 'def reset_join_request_owner' in entradas
    assert 'async def criar_link_direto_owner' in entradas
    assert 'creates_join_request": False' in entradas
    assert 'ajuste="convites.link_direto"' in entradas
    assert 'UPDATE eq_join_requests SET estado=\'pendente\'' in entradas
