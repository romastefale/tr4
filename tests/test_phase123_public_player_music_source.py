from pathlib import Path


def test_public_player_uses_music_service_before_connection_hint():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    start = text.index("async def _public_track_for_user")
    end = text.index("@router.get("/api/public/status")", start)
    body = text[start:end]
    assert "music_service.get_current_or_last_played" in body
    assert "is_user_connected" in body
    assert body.index("music_service.get_current_or_last_played") < body.index("is_user_connected")
    assert "music_service_sem_faixa" in body
