from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")


def test_panel_has_invite_inside_people_and_group_cards():
    assert "Convite rápido" in ROUTER
    assert "convite_rapido_nome" in ROUTER
    assert "auto-group-card" in ROUTER
    assert "Escolha o grupo por nome/foto" in ROUTER


def test_panel_keeps_owner_features_out_of_moderator_tabs():
    assert 'const moderatorPanelViews = new Set(["mensagens_view", "pessoas_view", "radio_view"])' in ROUTER
    assert 'data-action="convites.criar"' in ROUTER
    assert 'convites.criar") return "pessoas_view"' in ROUTER


def test_show_has_search_pagination_and_custom_limit():
    assert "show:gpage:" in SHOW
    assert "show:upage:" in SHOW
    assert "show:gsearch" in SHOW
    assert "show:usearch" in SHOW
    assert "show:lo:" in SHOW
    assert "limit_custom" in SHOW


def test_show_music_is_button_driven():
    assert "music_block_artist" in SHOW
    assert "music_block_track" in SHOW
    assert "music_catalog_add" in SHOW
    assert "music_schedule_add" in SHOW
    assert "mb_rm" in SHOW
    assert "mc_rm" in SHOW
    assert "ms_pause" in SHOW
    assert "ms_resume" in SHOW


def test_ddx_mentions_reincidence_suggestion():
    assert "Sugestão: há reincidência" in SHOW
