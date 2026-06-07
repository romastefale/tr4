from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"
MESA = ROOT / "app" / "equalizador" / "mesa.py"


def test_member_ui_has_safe_controls_and_result_area():
    text = ROUTER.read_text()
    assert 'id="silencio_duracao"' in text
    assert 'id="remover_revogar"' in text
    assert 'id="membro_resultado"' in text
    assert "setMembroResult" in text
    assert "revogar_mensagens" in text


def test_member_actions_return_public_member_state():
    text = MESA.read_text()
    assert 'response["membro"]' in text
    assert '"silenciado"' in text
    assert '"liberado"' in text
    assert '"removido"' in text
    assert '"reintegrado"' in text
    assert "mark_alvo_status" in text


def test_member_targets_store_last_known_status_without_exposing_ids():
    text = MESA.read_text()
    assert "telegram_status TEXT" in text
    assert "ALTER TABLE eq_alvos ADD COLUMN telegram_status TEXT" in text
    assert '"situacao"' in text
    assert "getChatMember" in text
    assert "Alvo é administrador" in text
    assert "Alvo automatizado" in text
