from pathlib import Path

IDENTITY = Path("app/equalizador/identity.py").read_text(encoding="utf-8")
MESA = Path("app/equalizador/mesa.py").read_text(encoding="utf-8")
SEGURANCA = Path("app/equalizador/seguranca_avancada.py").read_text(encoding="utf-8")


def test_phase83_security_and_export_refs_are_allowed_kinds():
    assert '"sec"' in IDENTITY
    assert '"exp"' in IDENTITY
    assert 'make_ui_ref("sec"' in SEGURANCA


def test_phase83_afinacao_insuficiente_has_operator_friendly_mapping():
    assert '"afinação_insuficiente": "Permissão real do bot insuficiente."' in MESA
    assert '"afinacao_insuficiente": "Permissão real do bot insuficiente."' in MESA
