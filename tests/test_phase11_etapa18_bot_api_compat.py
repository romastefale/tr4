from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESA = (ROOT / "app" / "equalizador" / "mesa.py").read_text(encoding="utf-8")
MAESTRO = (ROOT / "app" / "equalizador" / "maestro.py").read_text(encoding="utf-8")
MULTIMIDIA = (ROOT / "app" / "equalizador" / "multimidia.py").read_text(encoding="utf-8")


def test_direct_bot_api_uses_current_link_preview_options_for_new_equalizador_calls():
    combined = "\n".join([MESA, MAESTRO, MULTIMIDIA])
    assert "link_preview_options" in combined
    # Avoid the old Bot API parameter in the direct HTTP payloads maintained by Equalizador.
    assert '"disable_web_page_preview"' not in combined


def test_photo_caption_does_not_enable_html_parse_mode_for_governante_text():
    block_start = MESA.index('if ajuste == "mensagens.enviar_foto":')
    block_end = MESA.index('if ajuste in {"mensagens.apagar", "fixados.criar", "fixados.remover"}:')
    block = MESA[block_start:block_end]
    assert 'telegram_payload["caption"] = legenda' in block
    assert '"parse_mode"' not in block


def test_invite_creation_is_backend_forced_to_join_request_without_member_limit():
    block_start = MESA.index('if ajuste == "convites.criar":')
    block_end = MESA.index('raise MesaError("ajuste_indisponivel")', block_start)
    block = MESA[block_start:block_end]
    assert '"creates_join_request": True' in block
    assert '"member_limit"' not in block
