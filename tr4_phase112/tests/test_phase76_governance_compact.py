from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
PALCOS = Path("app/equalizador/palcos.py").read_text(encoding="utf-8")


def test_phase76_class_enabled_and_neutral_surfaces():
    assert "phase76-governance-compact" in ROUTER
    assert "background: #101418" in ROUTER
    assert "background: #161b20" in ROUTER


def test_governantes_are_collapsed_disclosure_cards():
    assert 'document.createElement("details")' in ROUTER
    assert 'document.createElement("summary")' in ROUTER
    assert 'governance-detail' in ROUTER
    assert 'governance-card[open]' in ROUTER


def test_governantes_summary_shows_person_name_username_group_and_counts():
    assert 'governance-person-main' in ROUTER
    assert 'governance-person-sub' in ROUTER
    assert 'Nome público ainda não visto' in ROUTER
    assert 'janela(s)' in ROUTER
    assert 'canal(is)' in ROUTER


def test_operator_profile_falls_back_to_known_targets_before_generic_label():
    assert 'FROM eq_alvos' in PALCOS
    assert 'nome_publico AS nome' in PALCOS
    assert 'ORDER BY updated_at DESC' in PALCOS
    assert 'Nome público ainda não visto' in PALCOS
