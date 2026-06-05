from pathlib import Path


def test_phase47_interface_has_header_group_summary_and_shortcuts():
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()
    painel = (root / "app/equalizador/painel.py").read_text()
    mesa = (root / "app/equalizador/mesa.py").read_text()

    assert 'id="palco_header_select"' in router
    assert 'id="grupo_resumo"' in router
    assert 'id="grupo_membros"' in router
    assert 'Criação</td>' not in router
    assert '/mesa_ajuda' in router
    assert 'person-link' in router
    assert 'foto_disponivel' in painel
    assert 'getChatMemberCount' in painel
    assert 'contato_url' in painel
    assert 'contato_url' in mesa


def test_phase47_photo_proxy_does_not_expose_bot_token_to_frontend():
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/equalizador/router.py").read_text()

    assert '/api/palcos/{grp_ref}/foto' in router
    assert 'https://api.telegram.org/file/bot' in router
    assert 'loadPalcoPhoto' in router
    assert 'settings.TELEGRAM_BOT_TOKEN' in router


def test_phase47_home_shows_bot_summary_and_no_creation_row():
    router = Path('app/equalizador/router.py').read_text()
    assert '/equalizador/api/bot/resumo' in router
    assert '/equalizador/api/bot/foto' in router
    assert 'Usuários conhecidos' in router
    assert 'Criação</td>' not in router
