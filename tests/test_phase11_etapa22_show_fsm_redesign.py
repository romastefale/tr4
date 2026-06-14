from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs/FASE11_ETAPA22_SHOW_FSM_OWNER_CENTER.md").read_text(encoding="utf-8")


def test_show_owner_home_is_objective_based_and_uses_moderador_language():
    assert "Owner Center organized by objectives" in SHOW
    assert "Configurar moderadores" in SHOW
    assert "Pacotes e ações" in SHOW
    assert "Limites e exceções" in SHOW
    assert "Logs" in SHOW
    assert "Segurança" in SHOW
    assert "Moderador:" in SHOW
    assert "Governante:" not in SHOW


def test_show_owner_keeps_context_and_reuses_existing_assignment():
    assert "def _refresh_selected_assignment" in SHOW
    assert "_refresh_selected_assignment(state)" in SHOW
    assert 'state["assignment_ref"] = assignment.get("assignment_ref") or ""' in SHOW
    assert 'state["actions"] = list(assignment.get("actions") or [])' in SHOW


def test_show_owner_music_has_objective_subpages():
    assert 'callback_data="show:music_blocks"' in SHOW
    assert 'callback_data="show:music_catalog"' in SHOW
    assert 'callback_data="show:music_schedules"' in SHOW
    assert "def _music_blocks_text" in SHOW
    assert "def _music_catalog_text" in SHOW
    assert "def _music_schedules_text" in SHOW


def test_show_owner_has_logs_and_security_pages():
    assert "def _logs_text" in SHOW
    assert "list_historico_publico" in SHOW
    assert "def _security_text" in SHOW
    assert 'callback_data="show:logs"' in SHOW
    assert 'callback_data="show:security"' in SHOW


def test_document_records_user_decisions():
    assert "3 abas" in DOC
    assert "Mensagens, Pessoas e Música" in DOC
    assert "Owner Center fica só no /town" in DOC
    assert "DDX fica só no /town" in DOC
