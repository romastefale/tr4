from pathlib import Path
import re


def test_public_player_escapehtml_no_python_triple_quote_breakage():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert '""":"&quot;"' not in text
    assert '""":' not in text
    assert 'function escapeHtml(v)' in text
    assert 'const map = {"&":"&amp;","<":"&lt;",">":"&gt;",' in text
    assert "'\"':\"&quot;\"" in text


def test_public_player_has_runtime_diagnostics_and_preview():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert 'player_js_started' in text
    assert '/equalizador/api/client-error' in text
    assert '/equalizador/api/public/playing-preview' in text
    assert 'window.onerror' in text
    assert 'unhandledrejection' in text
