from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app" / "templates" / "tnow_card.html").read_text(encoding="utf-8")


def test_tnow_seleciona_ate_25_sem_usar_grade_como_filtro():
    assert "selected_activities = eligible[:MAX_TILES]" in TNOW
    assert "eligible[:slots]" not in TNOW
    assert "eligible[:capacity]" not in TNOW
    assert "empty_slots = max(0, capacity - len(selected_activities))" in TNOW


def test_logs_expoem_capacidade_renderizados_e_vazios():
    assert "capacity=%s" in TNOW
    assert "rendered=%s" in TNOW
    assert "empty_slots=%s" in TNOW


def test_card_nao_exibe_badge_de_provedor_musical():
    assert "last.fm" not in CARD.lower()
    assert "badge" not in CARD
    assert ".tile .badge" not in TEMPLATE


def test_layout_tem_casos_sem_vazio_exagerado():
    from app.services.tnow_card import _choose_grid_layout

    expected = {
        1: (1, 1, 1),
        2: (1, 2, 2),
        3: (1, 3, 3),
        4: (2, 2, 4),
        5: (2, 3, 6),
        7: (2, 4, 8),
        10: (2, 5, 10),
        13: (3, 5, 15),
        17: (4, 5, 20),
        21: (5, 5, 25),
        25: (5, 5, 25),
    }
    for n, layout in expected.items():
        assert _choose_grid_layout(n) == layout
        assert layout[2] >= n
        assert layout[2] <= 25
