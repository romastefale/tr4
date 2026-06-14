from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TGOV = (ROOT / "app/bot/tgov_owner.py").read_text(encoding="utf-8")
MULTIMIDIA = (ROOT / "app/equalizador/multimidia.py").read_text(encoding="utf-8")
BOT = (ROOT / "app/bot/telegram.py").read_text(encoding="utf-8")


def test_tgov_album_uses_copy_messages_and_keeps_silent_pin_option() -> None:
    assert '"copyMessages"' in TGOV
    assert 'media_group_id' in TGOV
    assert 'source_message_ids' in TGOV
    assert 'published_message_ids' in TGOV
    assert 'Publicar e fixar em silêncio' in TGOV
    assert 'disable_notification=True' in TGOV


def test_multimedia_sessions_store_native_source_and_publish_by_copy() -> None:
    for column in ("source_chat_id", "source_message_id", "source_message_ids", "source_media_group_id"):
        assert column in MULTIMIDIA
    assert '"copyMessage"' in MULTIMIDIA
    assert '"copyMessages"' in MULTIMIDIA
    assert '"album": "álbum"' in MULTIMIDIA
    assert 'modo": "copia_nativa"' in MULTIMIDIA


def test_private_multimedia_handler_copies_preview_before_webapp_confirmation() -> None:
    assert 'source_chat_id' in BOT
    assert 'source_message_id' in BOT
    assert 'source_media_group_id' in BOT
    assert 'message.bot.copy_message(chat_id=message.chat.id' in BOT
    assert 'Prévia copiada acima' in BOT
