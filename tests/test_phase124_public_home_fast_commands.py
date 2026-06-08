from pathlib import Path


def test_public_home_no_getchatmember_loop():
    text = Path("app/equalizador/router.py").read_text()
    start = text.index("async def _public_groups_for_user")
    end = text.index("async def _public_track_for_user", start)
    block = text[start:end]
    assert "getChatMember" not in block
    assert "verificado ao publicar" in block


def test_public_home_exposes_commands_and_uses_music_service():
    text = Path("app/equalizador/router.py").read_text()
    assert "def _public_music_commands()" in text
    assert "commandGrid" in text
    assert "asyncio.wait_for(music_service.get_current_or_last_played" in text
    assert "\"commands\": _public_music_commands()" in text
