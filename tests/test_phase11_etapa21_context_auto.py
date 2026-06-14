from app.equalizador.security import TelegramWebAppIdentity


def test_identity_can_carry_signed_webapp_context():
    identity = TelegramWebAppIdentity(
        user_id=1,
        user={"id": 1},
        auth_date=123,
        chat={"id": -100123, "type": "supergroup"},
        chat_type="supergroup",
        chat_instance="abc",
        start_param="grp_ABC123DEF",
    )
    assert identity.chat and identity.chat["id"] == -100123
    assert identity.chat_type == "supergroup"
    assert identity.start_param == "grp_ABC123DEF"
