from pathlib import Path

ROUTER = Path('app/equalizador/router.py')


def test_phase138_3_no_wrapper_text_is_sent():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'Cópia enviada pelo Mini App tigraoRADIO' not in src
    assert 'Enviei uma cópia no chat do bot' not in src


def test_phase138_3_no_longer_trusts_ui_rendered_result_payload():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'result_title:' not in src
    assert 'result_text:' not in src
    assert 'result_image:' not in src
    assert 'result_filename:' not in src


def test_phase138_3_backend_fallback_executes_command_from_trusted_backend():
    src = ROUTER.read_text(encoding='utf-8')
    route = src[src.index('@router.post("/api/public/send-command-copy")'):src.index('@router.post("/api/public/nowp")')]
    assert 'public_music_command(command' in route
    assert 'result.get("text")' in route
    assert '_bot_api("sendPhoto"' in route
    assert '_bot_api("sendMessage"' in route


def test_phase138_3_client_sends_only_command_and_group_ref():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'type:"public_command_copy"' in src
    assert 'command:"/"+command' in src
    assert 'group_ref:selectedGroup||""' in src
    assert 'Executando /"+command+" na DM do bot.' in src
