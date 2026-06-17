from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_radiofm_uses_only_own_transient_bot_messages():
    radiofm = read("app/bot/radiofm.py")

    assert "apaga somente essa mensagem própria" in radiofm
    assert "Não apaga comando do usuário" in radiofm
    assert "async def _safe_delete_bot_message" in radiofm
    assert "await bot.delete_message" in radiofm
    assert "message.delete(" not in radiofm
    assert "delete_message(message.chat.id" not in radiofm
    assert "delete_message(chat_id=message.chat.id" not in radiofm


def test_radiofm_edits_flow_message_for_search_list_and_preparation():
    radiofm = read("app/bot/radiofm.py")

    assert "async def _set_flow_message" in radiofm
    assert "await bot.edit_message_text" in radiofm
    assert 'await message.answer("Escolha a faixa:"' not in radiofm
    assert 'text="Buscando música..."' in radiofm
    assert 'text="Escolha a faixa:"' in radiofm
    assert 'text="Preparando card..."' in radiofm
    assert "reply_markup=keyboard" in radiofm


def test_radiofm_deletes_transient_after_final_card_only():
    radiofm = read("app/bot/radiofm.py")

    assert "flow_chat_id" in radiofm
    assert "flow_msg_id" in radiofm
    assert "# Music-only clean: apaga somente a mensagem transitória do próprio bot." in radiofm
    assert "_safe_delete_bot_message(bot, flow_chat_id, flow_msg_id)" in radiofm
    helper_block = radiofm.split("async def _safe_delete_bot_message", 1)[1].split("async def _resolve_spotify_output", 1)[0]
    assert "command_msg_id" not in helper_block


def test_release_validator_covers_radiofm_transient_contract():
    validator = read("scripts/validate_tr4_release.py")

    assert "check_radiofm_own_transient_flow_contract" in validator
    assert "radiofm não possui helper de edição" in validator
    assert "radiofm ainda envia lista como nova mensagem permanente" in validator
    assert "radiofm não apaga a mensagem transitória própria" in validator
