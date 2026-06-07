from app.equalizador.erros_telegram import telegram_error_info, telegram_error_info_from_payload


def test_phase54_7_normaliza_429_sem_id() -> None:
    info = telegram_error_info_from_payload(data={"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 7", "parameters": {"retry_after": 7}}, status_code=429)
    assert info.category == "rate_limit"
    assert "7" in info.public_detail
    assert "Too Many" not in info.public_detail


def test_phase54_7_sanitiza_ids_e_token() -> None:
    info = telegram_error_info(description="Bad Request: chat -100123456789 not found for 8505890439 with bot123:ABC", status_code=400, error_code=400)
    assert "-100123456789" not in info.public_detail
    assert "8505890439" not in info.public_detail
    assert "bot123:ABC" not in info.public_detail


def test_phase54_7_classifica_409() -> None:
    info = telegram_error_info(description="Conflict: terminated by other getUpdates request", status_code=409, error_code=409)
    assert info.category == "conflict"
    assert "Atualize o painel" in info.public_detail
