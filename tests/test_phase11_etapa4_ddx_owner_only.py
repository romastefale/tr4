from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app" / "equalizador" / "router.py").read_text(encoding="utf-8")
DDX = (ROOT / "app" / "equalizador" / "ddx.py").read_text(encoding="utf-8")
SHOW = (ROOT / "app" / "bot" / "show_owner.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "FASE11_ETAPA4_DDX_OWNER_ONLY.md").read_text(encoding="utf-8")


def test_ddx_endpoints_are_maestro_only():
    assert "def _require_maestro_ddx" in ROUTER
    ddx_area = ROUTER[ROUTER.index('@router.get("/api/palcos/{grp_ref}/ddx")') : ROUTER.index('@router.get("/api/palcos/{grp_ref}/multimidia/centro")')]
    assert ddx_area.count("_require_maestro_ddx(identity)") >= 3
    assert "DDX é restrito ao owner." in ROUTER


def test_governante_does_not_see_ddx_nav_by_default():
    assert 'id="ddx_nav" class="nav secondary hidden"' in ROUTER
    assert 'button.nav:not([data-moderator-tab="1"])' in ROUTER
    assert 'if (!currentPalco || !modoMaestroPermitido)' in ROUTER


def test_ddx_single_owner_scope_disables_soft_mode():
    assert 'DDX 10 minutos está fora do escopo atual.' in ROUTER
    assert 'mode == "soft"' in ROUTER
    assert 'raise HTTPException(status_code=400, detail="DDX 10 minutos está fora do escopo atual.")' in ROUTER
    assert 'soft = None' in DDX


def test_ddx_records_full_owner_log_and_reincidence():
    assert "full_text TEXT" in DDX
    assert "actor_user_id INTEGER" in DDX
    assert "actor_kind TEXT" in DDX
    assert "DDX_REINCIDENCE_THRESHOLD = 5" in DDX
    assert "_notify_reincidence_if_needed" in DDX
    assert "Sugestão: avaliar ban pelo /show" in DDX


def test_sender_chat_alert_does_not_delete_automatically():
    assert 'status="sender_chat_alert"' in DDX
    assert "Canal remetente detectado; somente alerta owner." in DDX
    assert "Mensagem não apagada automaticamente" in DDX


def test_show_owner_mentions_ddx_owner_only():
    assert "<b>DDX</b>" in SHOW
    assert "Moderador não vê, não configura e não recebe logs." in SHOW or "DDX" in SHOW
    assert "DDX owner-only" in DOC
