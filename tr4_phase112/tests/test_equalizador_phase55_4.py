from pathlib import Path


def test_phase55_4_radio_templates_and_history_backend_routes_exist():
    router = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    radio = Path("app/equalizador/radio.py").read_text(encoding="utf-8")
    assert "/radio/templates" in router
    assert "/radio/historico" in router
    assert "criar_template_radio" in radio
    assert "list_radio_templates_publicos" in radio
    assert "list_radio_history_publico" in radio
    assert "eq_radio_templates" in radio
    assert "eq_radio_history" in radio


def test_phase55_4_radio_frontend_exposes_template_and_history_windows():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert "Modelos do Radio" in text
    assert "Histórico do Radio" in text
    assert "radio_template_salvar" in text
    assert "radio_template_usar" in text
    assert "radio_template_apagar" in text
    assert "renderRadioHistory" in text


def test_phase55_4_templates_do_not_store_media_base64():
    radio = Path("app/equalizador/radio.py").read_text(encoding="utf-8")
    start = radio.index("CREATE TABLE IF NOT EXISTS eq_radio_templates")
    end = radio.index("CREATE INDEX IF NOT EXISTS ix_eq_radio_templates_palco")
    ddl = radio[start:end]
    assert "media_base64" not in ddl
