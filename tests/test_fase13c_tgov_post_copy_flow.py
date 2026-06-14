from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TGOV = (ROOT / "app/bot/tgov_owner.py").read_text(encoding="utf-8")


def test_tgov_native_post_copy_flow_uses_copy_message_preview_and_publish() -> None:
    assert 'callback_data="tgov:ask:post_copy"' in TGOV
    assert 'awaiting == "post_copy"' in TGOV
    assert 'message.bot.copy_message' in TGOV
    assert 'callback.message.bot.copy_message' in TGOV
    assert 'method": "copyMessage"' in TGOV
    assert 'mensagens.copiar_post' in TGOV


def test_tgov_native_post_copy_flow_confirms_and_can_pin_silently() -> None:
    assert 'Prévia copiada acima. Confirma publicar esta cópia no grupo selecionado?' in TGOV
    assert 'callback_data="tgov:post:send"' in TGOV
    assert 'callback_data="tgov:post:send_pin_silent"' in TGOV
    assert 'callback.message.bot.pin_chat_message' in TGOV
    assert 'disable_notification=True' in TGOV
    assert 'required_right="can_pin_messages"' in TGOV
