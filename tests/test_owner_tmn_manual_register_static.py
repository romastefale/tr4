from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMN = (ROOT / "app" / "bot" / "owner_manual_register.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
SETUP = (ROOT / "app" / "bot" / "setup_commands.py").read_text(encoding="utf-8")


def test_tmn_command_criado_owner_only():
    assert '@router.message(Command("tmn"))' in TMN
    assert 'is_code_owner' in TMN
    assert 'CommandDef("tmn", "Cadastrar usuário Last.fm manualmente")' in SETUP
    assert 'CommandDef("tmn"' not in SETUP.split('_GROUP_COMMANDS', 1)[1].split('_OWNER_ONLY_COMMANDS', 1)[0]


def test_tmn_limpa_cadastros_antigos_e_insere_lastfm_limpo():
    assert 'db.query(LastfmProfile)' in TMN
    assert '.delete(synchronize_session=False)' in TMN
    assert 'db.query(SpotifyToken)' in TMN
    assert 'lastfm_service.set_username(target_user_id, lastfm_username)' in TMN
    assert '_clean_username(parts[2])' in TMN
    assert 'track_plays' not in TMN
    assert 'track_reactions' not in TMN


def test_tmn_router_registrado_no_startup():
    assert 'from app.bot.owner_manual_register import router as owner_manual_register_router' in MAIN
    assert 'dispatcher.include_router(owner_manual_register_router)' in MAIN


def test_tmn_uso_documentado_no_handler():
    assert '/tmn user_id username_lastfm' in TMN
    assert '/tmn 8505890439 romastefale' in TMN
