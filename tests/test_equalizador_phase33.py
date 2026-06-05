from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESA = ROOT / "app" / "equalizador" / "mesa.py"
ROUTER = ROOT / "app" / "equalizador" / "router.py"


def test_phase33_backend_enforces_delete_window_and_hides_deleted_refs() -> None:
    text = MESA.read_text(encoding="utf-8")
    assert "def mensagem_fora_da_janela_apagar" in text
    assert "48 * 60 * 60" in text
    assert 'raise MesaTargetError("Mensagem fora da janela de apagamento do Telegram.")' in text
    assert "def mark_mensagem_inativa" in text
    assert "SET habilitado=0" in text
    assert 'if ajuste == "mensagens.apagar" and alvo_ref:' in text


def test_phase33_message_actions_return_public_status_without_message_id() -> None:
    text = MESA.read_text(encoding="utf-8")
    assert 'response["mensagem"]' in text
    assert '"apagada"' in text
    assert '"fixada"' in text
    assert '"fixado_removido"' in text
    assert '"message_id"' not in text[text.find('response["mensagem"]') : text.find('if invite_link:')]


def test_phase33_ui_has_persistent_message_result() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert 'id="mensagem_resultado"' in text
    assert "function setMensagemResult" in text
    assert "Mensagem apagada" in text
    assert "Mensagem fixada" in text
    assert "Fixado removido" in text
    assert "if (data.mensagem) setMensagemResult" in text
