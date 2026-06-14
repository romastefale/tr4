from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def test_music_broadcast_uses_send_message_permission_channel():
    text = _router_text()
    assert '"broadcast.musical.webapp": "mensagens.enviar"' in text


def test_blocked_operational_view_falls_back_to_messages_not_internal_summary():
    text = _router_text()
    assert 'id = "mesa_view";' not in text
    assert 'id = moderatorPanelViews.has("mensagens_view") ? "mensagens_view" : "radio_view";' in text


def test_moderator_panel_still_has_only_three_visible_tabs_by_marker():
    text = _router_text()
    assert 'data-moderator-tab="1"><strong>Mensagens</strong>' in text
    assert 'data-moderator-tab="1"><strong>Pessoas</strong>' in text
    assert 'data-moderator-tab="1"><strong>Música</strong>' in text
