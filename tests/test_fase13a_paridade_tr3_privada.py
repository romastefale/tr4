from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tmod_private_fsm_gains_tr3_core_parity_actions() -> None:
    router = read("app/fsm_tigrao/router.py")
    keyboards = read("app/fsm_tigrao/keyboards.py")
    assert "desfixar" in router
    assert '"desfixar": "fixados.remover"' in router
    assert '"liberar": "membros.liberar"' in router
    assert '"reintegrar": "membros.reintegrar"' in router
    assert '"apagar_banir": "apagar mensagem e banir autor"' in router
    assert 'action == "apagar_banir"' in router
    assert "Apagar + banir" in keyboards
    assert "Liberar autor" in keyboards
    assert "Reintegrar autor" in keyboards
    assert "Desfixar" in keyboards


def test_author_and_message_requirements_are_explicit() -> None:
    router = read("app/fsm_tigrao/router.py")
    assert 'def _requires_author(action: str) -> bool:' in router
    assert 'return action in {"banir", "silenciar", "liberar", "reintegrar", "apagar_banir"}' in router
    assert 'def _requires_message(action: str) -> bool:' in router
    assert 'return action in {"apagar", "fixar", "desfixar", "apagar_banir"}' in router
    assert 'if _requires_author(action) and not data.get("alvo_ref"):' in router
    assert 'if _requires_message(action) and not data.get("msg_ref"):' in router


def test_tgrp_private_gets_logs_without_group_menu() -> None:
    router = read("app/fsm_tigrao/router.py")
    keyboards = read("app/fsm_tigrao/keyboards.py")
    assert "list_historico_publico" in router
    assert 'callback_data="tfm:pgrp:logs"' in keyboards
    assert 'if action == "logs":' in router
    assert "Logs recentes do grupo" in router
    assert "chat_is_group(message.chat):\n        await _silent_group_capture(message)\n        return" in router
