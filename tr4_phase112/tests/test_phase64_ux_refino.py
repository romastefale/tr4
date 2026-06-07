from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / 'app/equalizador/router.py').read_text()
CONFIG = (ROOT / 'app/equalizador/configuracao.py').read_text()


def test_phase64_group_picker_outside_card_and_extra_group_metadata():
    assert 'class="group-picker header-select"' in ROUTER
    assert 'id="grupo_resumo_card" class="panel group-card"' in ROUTER
    assert ('id="grupo_estado"' in ROUTER and 'id="grupo_recursos"' in ROUTER) or 'id="grupo_meta_linha"' in ROUTER


def test_phase64_removes_redundant_home_cards_and_adds_searchable_members():
    assert 'A navegação acima já substitui os cartões repetidos' in ROUTER
    assert 'id="mesa_membros_busca"' in ROUTER
    assert 'id="alvos_busca"' in ROUTER
    assert 'function memberMatches' in ROUTER
    assert 'function renderAlvosBusca' in ROUTER


def test_phase64_owner_only_governance_and_config_compaction():
    assert 'id="governantes_palco_section" class="owner-only hidden"' in ROUTER
    assert 'govSection.classList.toggle("hidden", !modoMaestroPermitido)' in ROUTER
    assert 'class="config-actions"' in ROUTER
    assert 'function renderConfigChipList' in ROUTER


def test_phase64_config_owner_view_gets_chat_id_without_public_palcos_leak():
    assert '"chat_id": int(chat_id)' in CONFIG
    assert 'chat_by_ref = {make_ui_ref("grp", int(chat_id), alias_secret): int(chat_id) for chat_id in allowed_palcos}' in CONFIG
    assert 'row["chat_id"] = chat_by_ref[ref]' in CONFIG


def test_phase64_nav_state_indicators():
    assert 'ensureNavStates' in ROUTER
    assert 'setAllOperationalNavStates("loading")' in ROUTER
    assert 'setAllOperationalNavStates("ok")' in ROUTER
    assert 'setAllOperationalNavStates("bad")' in ROUTER
