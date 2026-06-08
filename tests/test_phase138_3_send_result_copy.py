from pathlib import Path

ROUTER = Path('app/equalizador/router.py')


def test_phase138_3_send_result_copy_does_not_send_wrapper_text():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'Cópia enviada pelo Mini App tigraoRADIO' not in src
    assert 'Enviei uma cópia no chat do bot' not in src
    assert 'Enviei o resultado no chat do bot' in src


def test_phase138_3_send_result_copy_uses_result_title_and_text_only():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'def _clean_public_result_text' in src
    assert 'result_title = _clean_public_result_text' in src
    assert 'result_text = _clean_public_result_text' in src
    assert 'text_lines.append(result_title)' in src
    assert 'text_lines.append(result_text)' in src
    assert 'text_lines = [f"/{command}"' not in src


def test_phase138_3_send_result_copy_can_send_result_image():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'result_image' in src
    assert 'result_filename' in src
    assert '_store_public_data_url' in src
    assert '_absolute_public_url' in src
    assert '_bot_api("sendPhoto"' in src


def test_phase138_3_client_sends_full_result_payload():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'result_image:image' in src
    assert 'result_filename:filename' in src
    assert 'Enviando resultado pelo bot.' in src
    assert 'Resultado enviado pelo bot.' in src


def test_phase138_3_public_commands_have_longer_timeout_than_bootstrap():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'const timeoutMs=opts.timeoutMs||10000' in src
    assert '{timeoutMs:45000}' in src
    assert 'timeoutMs:25000' in src
    assert 'timeoutMs:30000' in src
