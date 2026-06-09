from __future__ import annotations

from pathlib import Path

ROUTER = Path("app/equalizador/router.py")


def _public_html() -> str:
    text = ROUTER.read_text(encoding="utf-8")
    start_marker = '_PUBLIC_MUSIC_HTML = """'
    start = text.index(start_marker) + len(start_marker)
    end = text.index('"""\n\n@router.get("/player"', start)
    return text[start:end]


def test_phase139_1_group_card_is_single_line_three_columns() -> None:
    html = _public_html()
    assert "grid-template-columns:46px minmax(0,1fr) auto" in html
    assert 'id="selectedGroupPhoto" class="group-photo"' in html
    assert 'class="group-info"' in html
    assert "white-space:nowrap" in html
    assert "text-overflow:ellipsis" in html


def test_phase139_1_group_switch_button_is_compact() -> None:
    html = _public_html()
    assert ".select-group{width:auto;min-width:76px;min-height:38px;height:38px" in html
    assert 'id="toggleGroupsBtn" class="select-group" type="button">Trocar</button>' in html
    assert ".select-group,.choice" not in html


def test_phase139_1_selected_group_updates_avatar_initial() -> None:
    html = _public_html()
    assert "function groupInitial(group)" in html
    assert 'const photo=$("selectedGroupPhoto");if(photo)photo.textContent=group?groupInitial(group):"G";' in html
