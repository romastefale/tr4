from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = (ROOT / "app" / "bot" / "owner_manual_register.py").read_text(encoding="utf-8")
LASTFM_SERVICE = (ROOT / "app" / "services" / "lastfm.py").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
TR4_DOC = (ROOT / "TR4_MUSIC_ONLY.md").read_text(encoding="utf-8")


def test_owner_manual_register_user_visible_messages_are_neutral():
    user_visible_region = OWNER.split("await message.answer(", 1)[1]
    assert "lastfm_profiles" not in user_visible_region
    assert "spotify_tokens" not in user_visible_region
    assert "perfil_musical" in user_visible_region
    assert "conexao_musical" in user_visible_region


def test_lastfm_validation_error_is_neutral():
    assert 'raise ValueError("perfil musical inválido")' in LASTFM_SERVICE
    assert 'raise ValueError("username Last fm inválido")' not in LASTFM_SERVICE


def test_metadata_and_main_doc_do_not_use_lastfm_with_dot():
    assert "Last.fm" not in PYPROJECT
    assert "Last.fm" not in TR4_DOC
