from pathlib import Path


def test_public_functional_diagnostics_endpoint_exists():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert '@router.get("/api/public/diagnostico")' in text
    assert 'menu_fixo' in text
    assert 'consulta_grupos_lenta' in text
    assert 'getChatMember' not in text[text.index('def _public_cached_groups'):text.index('async def _public_groups_for_user')]


def test_public_preview_reuses_playing_payload():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert '@router.get("/api/public/playing-preview")' in text
    assert 'build_playing_payload_for_user' in text
