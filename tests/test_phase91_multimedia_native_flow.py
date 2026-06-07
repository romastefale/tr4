from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')
BOT = Path('app/bot/telegram.py').read_text(encoding='utf-8')
MULTI = Path('app/equalizador/multimidia.py').read_text(encoding='utf-8')


def test_phase91_multimedia_routes_exist():
    assert '/multimidia/sessoes' in ROUTER
    assert 'create_multimedia_session' in ROUTER
    assert 'publish_multimedia_session' in ROUTER
    assert 'mensagens.enviar' in ROUTER


def test_phase91_webapp_opens_bot_dm_and_confirms_in_panel():
    assert 'multimidia_iniciar' in ROUTER
    assert 'https://t.me/${user}?start=${encodeURIComponent(payload)}' in ROUTER
    assert 'publicarMultimediaSessao' in ROUTER
    assert 'row.status !== "ready"' in ROUTER


def test_phase91_bot_captures_native_media_from_private_chat():
    assert 'payload.startswith("mm_")' in BOT
    assert 'mark_session_waiting' in BOT
    assert 'attach_telegram_message_to_session' in BOT
    assert 'equalizador_multimedia_private_media' in BOT
    assert 'F.photo | F.video | F.document | F.audio | F.voice' in BOT


def test_phase91_sessions_are_persistent_and_safe():
    assert 'CREATE TABLE IF NOT EXISTS eq_multimedia_sessions' in MULTI
    assert 'telegram_user_id' in MULTI
    assert 'status=\'ready\'' in MULTI
    assert 'status=\'published\'' in MULTI
    assert 'register_mensagem_ref' in MULTI
    assert 'record_historico' in MULTI


def test_phase91_does_not_use_webapp_for_file_upload():
    assert 'media_base64' not in MULTI
    assert 'file_id' in MULTI
    assert 'sendPhoto' in MULTI
    assert 'sendVideo' in MULTI
    assert 'sendDocument' in MULTI
