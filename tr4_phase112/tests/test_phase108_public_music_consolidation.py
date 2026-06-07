from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase108_public_player_is_public_first_and_operator_panel_is_hidden_by_default():
    assert 'Mini App público do tigraoRADIO' in ROUTER
    assert 'mod-link hidden' in ROUTER
    assert 'if (me.can_open_equalizador) $("modBtn").classList.remove("hidden")' in ROUTER
    assert 'O botão de moderação só aparece para operadores autorizados.' in ROUTER


def test_phase108_player_uses_nowp_language_and_big_publish_button():
    assert 'Publicar atual' in ROUTER
    assert 'publicação via /nowp' in ROUTER
    assert 'trackAvailable' in ROUTER
    assert 'updatePublishState' in ROUTER
