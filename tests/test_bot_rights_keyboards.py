from __future__ import annotations

from app.moderation_tigrao.keyboards import (
    governance_keyboard,
    messages_keyboard,
    radio_keyboard,
    reactions_mod_keyboard,
    user_actions_keyboard,
)


def _keyboard_text(markup) -> str:
    return str(markup)


def test_radio_pin_buttons_are_marked_unavailable_without_pin_right():
    markup = radio_keyboard(
        allowed_permissions={"radio.post_text", "radio.pin", "radio.post_media"},
        is_root=False,
        has_selected_chat=True,
        bot_capabilities=set(),
    )
    text = _keyboard_text(markup)
    assert "tigrao:rights:missing:pin" in text
    assert "tigrao:message:send" in text


def test_radio_pin_buttons_are_available_with_pin_right():
    markup = radio_keyboard(
        allowed_permissions={"radio.post_text", "radio.pin"},
        is_root=False,
        has_selected_chat=True,
        bot_capabilities={"pin"},
    )
    text = _keyboard_text(markup)
    assert "tigrao:message:pin" in text
    assert "tigrao:rights:missing:pin" not in text


def test_user_actions_signal_missing_restrict_and_invite():
    markup = user_actions_keyboard(bot_capabilities=set())
    text = _keyboard_text(markup)
    assert "tigrao:rights:missing:restrict" in text
    assert "tigrao:rights:missing:invite" in text


def test_messages_signal_missing_delete():
    markup = messages_keyboard(bot_capabilities=set())
    assert "tigrao:rights:missing:delete" in _keyboard_text(markup)


def test_reactions_signal_missing_delete_and_restrict():
    markup = reactions_mod_keyboard(bot_capabilities=set())
    text = _keyboard_text(markup)
    assert "tigrao:rights:missing:delete" in text
    assert "tigrao:rights:missing:restrict" in text


def test_governance_signals_missing_change_info_and_invite():
    markup = governance_keyboard(bot_capabilities=set())
    text = _keyboard_text(markup)
    assert "tigrao:rights:missing:change_info" in text
    assert "tigrao:rights:missing:invite" in text
