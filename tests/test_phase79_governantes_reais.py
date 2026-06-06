from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase79_class_and_helpers_exist():
    assert "phase79-governantes-reais" in ROUTER
    assert "governancaCargoLabel" in ROUTER
    assert "governancaNomePublico" in ROUTER


def test_phase79_summary_has_name_username_role_and_counts():
    assert "governance-person-main" in ROUTER
    assert "governance-cargo" in ROUTER
    assert "Governante principal" in ROUTER
    assert "Governante designado" in ROUTER
    assert "janela(s)" in ROUTER
    assert "canal(is)" in ROUTER


def test_phase79_governance_accordion_is_exclusive():
    assert 'item.addEventListener("toggle"' in ROUTER
    assert 'querySelectorAll("details.governance-card[open]")' in ROUTER
    assert "other.open = false" in ROUTER


def test_phase79_unknown_name_is_explicit_not_fake():
    assert "Nome público ainda não visto" in ROUTER
    assert "governance-warn" in ROUTER
