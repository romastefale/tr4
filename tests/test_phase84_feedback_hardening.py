from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase84_detail_publico_maps_afinacao_insuficiente():
    assert 'afina[cç][aã]o_insuficiente' in ROUTER
    assert 'Permissão real do bot insuficiente. Abra Diagnóstico' in ROUTER


def test_phase84_radio_publish_has_working_lock_and_conflict_feedback():
    assert 'id="radio_publicar"' in ROUTER
    assert 'button.getAttribute("aria-busy") === "true"' in ROUTER
    assert 'markButton(button, "working")' in ROUTER
    assert 'res.status === 409 ? "warn" : "bad"' in ROUTER
    assert 'await reloadRadioDrafts();' in ROUTER


def test_phase84_radio_conflict_message_is_specific():
    assert 'Rascunho já foi publicado ou cancelado. Atualize a lista' in ROUTER
