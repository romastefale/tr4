from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = ROOT / "app" / "bot" / "telegram.py"
SETUP = ROOT / "app" / "bot" / "setup_commands.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase37_hidden_commands_cover_message_member_invite_and_maestro_actions() -> None:
    text = read(TELEGRAM)
    for command in [
        'Command("mesa_ajuda")',
        'Command("mesa_apagar")',
        'Command("mesa_fixar")',
        'Command("mesa_desfixar")',
        'Command("mesa_silenciar")',
        'Command("mesa_liberar")',
        'Command("mesa_remover")',
        'Command("mesa_reintegrar")',
        'Command("mesa_silencio")',
        'Command("mesa_silencio_off")',
    ]:
        assert command in text


def test_phase37_hidden_commands_reuse_equalizador_security_services() -> None:
    text = read(TELEGRAM)
    assert 'executar_ajuste' in text
    assert 'executar_transmissao' in text
    assert 'executar_modo_silencio' in text
    assert 'executar_modo_silencio_desativar' in text
    assert 'canal_is_allowed' in text
    assert 'mesa_operation_lock' in text
    assert '_hidden_require_canal' in text
    assert 'CONFIRMAR AJUSTE | texto' in text


def test_phase37_hidden_commands_stay_private_and_unlisted() -> None:
    telegram = read(TELEGRAM)
    setup = read(SETUP)
    assert 'message.chat.type == "private"' in telegram
    assert 'TR4_EQUALIZADOR_MAESTRO_IDS_SET' in telegram
    for public_forbidden in [
        'mesa_ajuda', 'mesa_apagar', 'mesa_fixar', 'mesa_desfixar',
        'mesa_silenciar', 'mesa_liberar', 'mesa_remover', 'mesa_reintegrar',
        'mesa_silencio', 'mesa_silencio_off',
    ]:
        assert public_forbidden not in setup


def test_phase37_hidden_message_and_target_inputs_accept_refs_or_manual_resolution() -> None:
    text = read(TELEGRAM)
    assert '_hidden_message_ref_from_input' in text
    assert 'value.startswith("msg_")' in text
    assert 'parse_telegram_message_link' in text
    assert '_hidden_target_ref_from_input' in text
    assert 'value.startswith("usr_")' in text
    assert 'resolve_alvo_manual' in text
