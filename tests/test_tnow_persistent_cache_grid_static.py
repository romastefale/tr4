from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TNOW = (ROOT / "app" / "bot" / "tnow.py").read_text(encoding="utf-8")
CACHE = (ROOT / "app" / "services" / "tnow_activity_cache.py").read_text(encoding="utf-8")
CARD = (ROOT / "app" / "services" / "tnow_card.py").read_text(encoding="utf-8")


def test_tnow_fluxo_consulta_salva_depois_monta_da_tabela():
    assert "await _refresh_recent_activity(bot, uid, now=now)" in TNOW
    assert "eligible = await tnow_activity_cache_service.list_for_users(user_ids, now=now)" in TNOW
    assert "await tnow_activity_cache_service.upsert_from_track" in TNOW
    assert "expires_at" in CACHE
    assert "expire_user" in CACHE


def test_tnow_usa_cache_de_canal_de_capas_sem_depender_dele():
    assert "cover_cache_service.resolve_photo" in TNOW
    assert "TNOW_COVER_CACHE_WARM_FAILED" in TNOW
    assert "update_cover_file_id" in CACHE
    assert "cover_file_id" in CACHE


def test_tnow_prioridade_de_cores_e_logs_auditaveis():
    assert "TNOW_STATUS_PRIORITY" in CACHE
    assert '"live": 0' in CACHE
    assert '"recent_15": 1' in CACHE
    assert '"recent_30": 2' in CACHE
    assert '"recent_45": 3' in CACHE
    assert '"recent_120": 4' in CACHE
    assert "TNOW_CACHE_UPSERT" in CACHE
    assert "TNOW_ENTRY_DECISION" in TNOW
    assert "TNOW_GRID_SELECTED" in TNOW


def test_tnow_card_colunas_seguem_layout_adaptativo():
    assert "_GRID_LAYOUTS" in CARD
    for layout in ("(1, 1)", "(2, 3)", "(2, 4)", "(3, 5)", "(4, 5)", "(5, 5)"):
        assert layout in CARD
    assert "def _columns_for" in CARD
    assert "_choose_grid_layout(n)" in CARD
    assert "nunca corta usuário válido" in CARD
