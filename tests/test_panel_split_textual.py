from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tigrao_owner_radio_commands_exist():
    router = (ROOT / "app/moderation_tigrao/router.py").read_text(encoding="utf-8")
    assert '@router.message(Command("tigrao"))' in router
    assert '@router.message(Command("owner"))' in router
    assert '@router.message(Command("radio"))' in router


def test_home_owner_delegate_radio_keyboards_are_split():
    keyboards = (ROOT / "app/moderation_tigrao/keyboards.py").read_text(encoding="utf-8")
    assert "def entry_keyboard" in keyboards
    assert "def owner_home_keyboard" in keyboards
    assert "def delegate_home_keyboard" in keyboards
    assert "def radio_keyboard" in keyboards

    owner_block = keyboards.split("def owner_home_keyboard", 1)[1].split("def delegate_home_keyboard", 1)[0]
    delegate_block = keyboards.split("def delegate_home_keyboard", 1)[1].split("def home_keyboard", 1)[0]
    radio_block = keyboards.split("def radio_keyboard", 1)[1].split("def customize_keyboard", 1)[0]

    assert '"Personalização"' not in owner_block
    assert '"Governança"' not in delegate_block
    assert '"Segurança"' not in delegate_block
    assert '"Moderadores"' not in delegate_block
    assert '"Alterar nome"' not in radio_block
    assert '"Alterar bio"' not in radio_block
    assert '"Tag de membro"' not in radio_block
