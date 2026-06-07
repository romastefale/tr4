from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_equalizador_message_capture_uses_non_blocking_aiogram_middleware() -> None:
    source = read("app/bot/telegram.py")
    assert "class EqualizadorCaptureMiddleware(BaseMiddleware)" in source
    assert "dp.message.outer_middleware(EqualizadorCaptureMiddleware())" in source
    assert "return await handler(event, data)" in source
    assert "await _remember_equalizador_message(event)" in source


def test_equalizador_message_refs_store_telegram_message_date_for_delete_window() -> None:
    source = read("app/equalizador/mesa.py")
    assert "telegram_message_date INTEGER" in source
    assert "message_unix_time: int | None = None" in source
    assert "idade_segundos" in source
    assert '"apagavel"' in source
    assert "48 * 60 * 60" in source


def test_equalizador_ui_disables_message_actions_without_message_or_delete_window() -> None:
    source = read("app/equalizador/router.py")
    assert "mensagensPorRef" in source
    assert "Escolha uma mensagem registrada" in source
    assert "Mensagem fora da janela de apagamento do Telegram" in source
    assert "mensagem.apagavel === false" in source
    assert 'document.getElementById("mensagem_select").addEventListener("change", updateButtons)' in source
