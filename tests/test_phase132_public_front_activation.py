from pathlib import Path


def test_public_front_calls_preview_and_has_command_grid():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert 'id="commandGrid"' in text
    assert 'Comandos musicais' in text
    assert '/equalizador/api/public/playing-preview' in text
    assert 'async function loadPlayingPreview()' in text
    assert '@router.get("/api/public/playing-preview")' in text
    assert '@router.get("/api/public/diagnostico")' in text


def test_public_identity_supports_short_session():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    start = text.index('def _public_identity_from_authorization')
    end = text.index('def _group_ref', start)
    block = text[start:end]
    assert 'eqs ' in block
    assert 'validate_equalizador_session' in block
