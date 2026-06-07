from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def test_phase29_ui_has_mobile_status_and_empty_states() -> None:
    text = _router_text()
    assert "id=\"mesa_status\"" in text
    assert "id=\"mensagens_hint\"" in text
    assert "id=\"alvos_hint\"" in text
    assert "@media (max-width: 560px)" in text
    assert "Ações permanecem bloqueadas até confirmação do bot" in text


def test_phase29_ui_sanitizes_public_error_details() -> None:
    text = _router_text()
    assert "const detailPublico" in text
    assert "palco oculto" in text
    assert "referência oculta" in text
    assert "perfil oculto" in text
    assert "toast(detailPublico(data.detail || data), \"bad\")" in text


def test_phase29_distribution_uses_public_channel_names() -> None:
    text = _router_text()
    assert "const canalNome" in text
    assert ".map(canalNome).join" in text
    assert "mensagens.apagar não aparece" not in text


def test_phase29_actions_show_progress_and_reload_after_failure() -> None:
    text = _router_text()
    assert "Executando: " in text
    assert "await loadPalcoData(); return;" in text
    assert "Último ajuste concluído" in text
