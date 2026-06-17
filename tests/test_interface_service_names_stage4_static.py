from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "app" / "bot" / "setup_commands.py").read_text(encoding="utf-8")
TELEGRAM = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")
CONNECTION = (ROOT / "app" / "services" / "connection_check.py").read_text(encoding="utf-8")
MUSIC_RUNNER = (ROOT / "app" / "bot" / "music_command_runner.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_bot_command_descriptions_do_not_expose_service_names():
    commands_block = SETUP.split("def _to_bot_commands", 1)[0]
    assert "Last.fm" not in commands_block
    assert "Last fm" not in commands_block
    assert "Spotify" not in commands_block
    assert "Conectar perfil musical" in commands_block
    assert "Conectar conta musical" in commands_block


def test_start_help_login_logout_lastfm_messages_are_neutral():
    surface = _block(TELEGRAM, "def _start_text", "# Negrito unicode")
    surface += _block(TELEGRAM, '@dp.message(Command("login"))', '@dp.message(Command("lastfmoff"))')
    assert "Last.fm" not in surface
    assert "Last fm" not in surface
    assert "Spotify" not in surface
    assert "@{html.escape(username)}" not in surface
    assert "seu perfil musical" in surface
    assert "/lastfm seu_usuario" in surface


def test_not_connected_messages_explain_commands_without_service_names():
    connection_messages = CONNECTION.split("# Mensagem curta", 1)[1]
    assert "Last.fm" not in connection_messages
    assert "Last fm" not in connection_messages
    assert "Spotify" not in connection_messages
    assert "/lastfm seu_usuario" in connection_messages
    assert "perfil musical" in connection_messages
    assert "Use /lastfm seu_usuario ou /login" in MUSIC_RUNNER


def test_tnow_card_does_not_show_provider_badge():
    assert "last.fm" not in CARD.lower()
    assert "spotify" not in CARD.lower()
