from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase80_class_and_tokens_exist():
    assert "phase80-visual-system" in ROUTER
    assert "--eq-bg" in ROUTER
    assert "--eq-surface" in ROUTER
    assert "--eq-primary" in ROUTER
    assert "--eq-success" in ROUTER
    assert "--eq-danger" in ROUTER


def test_phase80_neutral_surfaces_are_default():
    assert "background: var(--eq-bg)" in ROUTER
    assert "background: var(--eq-surface)" in ROUTER
    assert "background: var(--eq-surface-2)" in ROUTER
    assert "background: var(--eq-surface-3)" in ROUTER


def test_phase80_semantic_colors_are_limited_to_actions_and_states():
    assert 'button.action[data-action="mensagens.apagar"]' in ROUTER
    assert 'background: var(--eq-danger)' in ROUTER
    assert 'button.action[data-action="convites.criar"]' in ROUTER
    assert 'background: var(--eq-success)' in ROUTER
    assert 'button#resolver_mensagem' in ROUTER
    assert 'background: var(--eq-primary)' in ROUTER


def test_phase80_keeps_governance_from_phase79():
    assert "governancaCargoLabel" in ROUTER
    assert 'item.addEventListener("toggle"' in ROUTER
