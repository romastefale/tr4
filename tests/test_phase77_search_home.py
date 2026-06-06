from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase77_keeps_center_photo_and_removes_group_select_from_home():
    assert "phase77-search-home" in ROUTER
    assert "body.phase77-search-home .bot-avatar" in ROUTER
    assert "width: 92px" in ROUTER
    assert "#palco_header_select" in ROUTER
    assert "body.phase77-search-home #palco_header_select" in ROUTER
    assert "display: none !important" in ROUTER


def test_phase77_search_is_primary_group_entry():
    assert "Buscar grupo, @, ID ou ação" in ROUTER
    assert 'sub: "abrir grupo"' in ROUTER
    assert 'document.body.classList.add("group-selected")' in ROUTER
    assert 'body.phase77-search-home:not(.group-selected) #mesa' in ROUTER
