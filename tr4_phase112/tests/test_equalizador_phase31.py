from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"
MESA = ROOT / "app" / "equalizador" / "mesa.py"
TELEGRAM = ROOT / "app" / "bot" / "telegram.py"


def test_phase31_interface_has_manual_inputs_and_persistent_invite_link() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert 'id="mensagem_link_input"' in text
    assert 'id="alvo_manual_input"' in text
    assert 'id="convite_resultado"' in text
    assert 'id="copiar_convite"' in text
    assert 'id="abrir_convite"' in text
    assert 'setConviteResult(data.convite' in text


def test_phase31_router_has_resolver_endpoints_and_dm_result() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert '/api/palcos/{grp_ref}/mensagens/resolver' in text
    assert '/api/palcos/{grp_ref}/alvos/resolver' in text
    assert 'register_mensagem_from_link' in text
    assert 'resolve_alvo_manual' in text
    assert 'send_operator_dm' in text
    assert 'result["dm"] = dm_result' in text


def test_phase31_rate_limit_separates_read_and_action() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert 'def _rate_limit_for(kind: str)' in text
    assert 'return max(base * 6, 120)' in text
    assert 'rate_kind="read"' in text
    assert 'rate_kind="bootstrap"' in text


def test_phase31_mesa_parses_message_link_and_username_resolution() -> None:
    text = MESA.read_text(encoding="utf-8")
    assert 'def parse_telegram_message_link' in text
    assert 'https://t.me/c/<internal_chat>/<message_id>' in text
    assert 'def resolve_alvo_manual' in text
    assert 'Username ainda não reconhecido' in text
    assert 'getChatMember' in text
    assert 'ADD COLUMN username' in text


def test_phase31_hidden_commands_are_private_and_not_public_setup() -> None:
    text = TELEGRAM.read_text(encoding="utf-8")
    assert 'Command("mesa_msg")' in text
    assert 'Command("mesa_alvo")' in text
    assert 'Command("mesa_convite")' in text
    assert 'Command("mesa_tx")' in text
    assert 'message.chat.type == "private"' in text
    assert 'TR4_EQUALIZADOR_MAESTRO_IDS_SET' in text
