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


def test_groups_keyboard_hides_chat_ids_but_keeps_callback_data():
    from app.moderation_tigrao.keyboards import groups_keyboard

    markup = groups_keyboard(
        managed_groups=[
            {"chat_id": -1003818494866, "title": "_ e tigraoRADIO"},
            {"chat_id": -1003818494999, "title": "_ e tigraoRADIO"},
        ],
        discovered_count=1,
        inaccessible_count=1,
    )
    button_labels = [button.text for row in markup.inline_keyboard for button in row]
    callback_data = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]

    assert not any("-1003818494866" in label for label in button_labels)
    assert not any("-1003818494999" in label for label in button_labels)
    assert "_ e tigraoRADIO" in button_labels
    assert "_ e tigraoRADIO #2" in button_labels
    assert "tigrao:group:-1003818494866" in callback_data
    assert "tigrao:group:-1003818494999" in callback_data
