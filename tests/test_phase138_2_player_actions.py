from pathlib import Path

ROUTER = Path('app/equalizador/router.py')


def test_phase138_2_backend_action_routes_exist():
    src = ROUTER.read_text(encoding='utf-8')
    assert '@router.post("/api/public/download-result")' in src
    assert '@router.get("/api/public/download/{token}")' in src
    assert '@router.post("/api/public/send-command-copy")' in src
    assert 'FileResponse' in src


def test_phase138_2_download_button_uses_backend_for_data_urls():
    src = ROUTER.read_text(encoding='utf-8')
    assert 'async function prepareDownloadUrl' in src
    assert '/equalizador/api/public/download-result' in src
    assert 'player_download_clicked' in src
    assert 'player_download_dispatched' in src
    assert 'tg.downloadFile' in src


def test_phase138_2_send_command_button_uses_telegram_senddata_before_backend_fallback():
    src = ROUTER.read_text(encoding='utf-8')
    senddata_index = src.index('player_senddata_attempt')
    backend_index = src.index('/equalizador/api/public/send-command-copy')
    assert senddata_index < backend_index
    assert 'player_send_command_clicked' in src
    assert 'player_send_command_done' in src
    assert 'player_send_command_backend_failed' in src
