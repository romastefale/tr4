from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_public_nowp_route_reuses_existing_playing_payload():
    assert '@router.post("/api/public/nowp")' in ROUTER
    assert 'build_playing_payload_for_user' in ROUTER
    assert 'music_service.get_current_or_last_played(identity.user_id)' in ROUTER


def test_public_nowp_confirms_group_membership_before_sending():
    assert 'getChatMember' in ROUTER
    assert 'Você não está neste grupo.' in ROUTER
    assert 'sendPhoto' in ROUTER or 'sendMessage' in ROUTER
