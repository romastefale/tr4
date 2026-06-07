from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase85_class_enabled():
    assert "phase85-cleanup" in ROUTER
    assert '"phase85-cleanup"' in ROUTER


def test_phase85_prevents_button_overflow():
    assert "box-sizing: border-box; min-width: 0; max-width: 100%" in ROUTER
    assert "white-space: normal" in ROUTER
    assert "overflow-wrap: anywhere" in ROUTER
    assert "#seguranca_exportar_criptografado" in ROUTER


def test_phase85_disclosure_list_helper_exists():
    assert "const disclosureRow" in ROUTER
    assert "const fillDisclosureList" in ROUTER
    assert "details.disclosure-row" in ROUTER


def test_phase85_diagnostic_sections_are_collapsible():
    assert 'document.createElement("details")' in ROUTER
    assert 'wrapper.className = "diagnostic-section"' in ROUTER
    assert "diagnostic-section-body" in ROUTER
    assert "liberado(s)" in ROUTER


def test_phase85_config_matrix_is_not_rendered_as_huge_open_item_list():
    assert 'fillDisclosureList("config_matriz"' in ROUTER
    assert "Toque para ver canais" in ROUTER
    assert 'fillList("config_matriz", matrizRows' not in ROUTER
