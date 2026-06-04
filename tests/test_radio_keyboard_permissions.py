from __future__ import annotations

from app.moderation_tigrao.keyboards import radio_keyboard


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_radio_keyboard_filters_delegate_without_group():
    texts = _button_texts(radio_keyboard(allowed_permissions={"radio.post_text"}, is_root=False, has_selected_chat=False))
    assert "Escolher grupo" in texts
    assert "Enviar mensagem" not in texts


def test_radio_keyboard_filters_delegate_permissions():
    texts = _button_texts(
        radio_keyboard(
            allowed_permissions={"radio.post_text", "radio.history.read"},
            is_root=False,
            has_selected_chat=True,
        )
    )
    assert "Enviar mensagem" in texts
    assert "Histórico" in texts
    assert "Enviar mídia" not in texts
    assert "Enviar para todos" not in texts


def test_radio_keyboard_owner_sees_all_core_actions():
    texts = _button_texts(radio_keyboard())
    assert "Enviar mensagem" in texts
    assert "Enviar mídia e fixar" in texts
    assert "Enviar para todos" in texts
