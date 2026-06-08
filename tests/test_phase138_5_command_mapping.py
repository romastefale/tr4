from pathlib import Path

ROUTER = Path('app/equalizador/router.py')
TELEGRAM = Path('app/bot/telegram.py')


def test_phase138_5_buttons_send_command_name_not_ui_result_payload():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'type:"public_command_copy"' in src
    assert 'command:"/"+command' in src
    assert 'group_ref:selectedGroup||""' in src
    assert 'result_title:' not in src
    assert 'result_text:' not in src
    assert 'result_image:' not in src
    assert 'result_filename:' not in src


def test_phase138_5_senddata_is_primary_execution_path():
    src = ROUTER.read_text(encoding='utf-8')
    senddata_index = src.index('player_senddata_attempt')
    backend_index = src.index('/equalizador/api/public/send-command-copy')
    assert senddata_index < backend_index
    assert 'Executando /"+command+" na DM do bot.' in src
    assert 'Enviar no bot' in src


def test_phase138_5_backend_fallback_ignores_rendered_ui_text():
    src = ROUTER.read_text(encoding='utf-8')
    route = src[src.index('@router.post("/api/public/send-command-copy")'):src.index('@router.post("/api/public/nowp")')]
    assert 'Regra da fase 138.5' in route
    assert 'payload.get("result_title")' not in route
    assert 'payload.get("result_text")' not in route
    assert 'payload.get("result_image")' not in route
    assert 'public_music_command(command' in route


def test_phase138_5_web_app_data_dispatches_existing_commands():
    src = TELEGRAM.read_text(encoding='utf-8')
    assert 'Fase 138.5: cada botão do Mini App executa o comando real já existente.' in src
    assert 'allowed = {"playing", "weekfm", "monthfm", "songcharts", "nowp", "tcanvas", "tstory", "tly", "tnow"}' in src
    assert 'await _weekfm_handler(message)' in src
    assert 'await _monthfm_handler(message)' in src
    assert 'await _tcanvas_handler(message)' in src
    assert 'await _tstory_handler(message)' in src
    assert 'await _tly_handler(message)' in src
    assert 'await _tnow_handler(message)' in src


def test_phase138_5_songcharts_uses_existing_renderer_for_group_dm_copy():
    src = TELEGRAM.read_text(encoding='utf-8')
    assert 'from app.bot.songcharts import _is_chat_admin, _members_in_chat, _render_and_send' in src
    assert 'await _render_and_send(' in src
    assert 'target_chat_id=message.chat.id' in src
    assert 'pin=False' in src
