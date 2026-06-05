from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"
MESA = ROOT / "app" / "equalizador" / "mesa.py"


def test_phase35_invite_ui_has_advanced_fields_and_persistent_metadata() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert 'id="convite_expira"' in text
    assert 'id="convite_limite"' in text
    assert 'id="convite_aprovacao"' in text
    assert 'id="convite_dm"' in text
    assert 'id="convite_metadados"' in text
    assert 'setConviteResult(data.convite, data.dm || null, data.convite_info || null)' in text


def test_phase35_invite_payload_supports_expiry_limit_join_request_and_dm_toggle() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    assert 'expira_em_segundos: Number(document.getElementById("convite_expira").value || 0)' in text
    assert 'limite_membros: aprovacao ? 0' in text
    assert 'solicitar_aprovacao: aprovacao' in text
    assert 'enviar_dm: Boolean(document.getElementById("convite_dm").checked)' in text
    assert 'payload_enviar_dm = bool(payload.get("enviar_dm", True))' in text
    assert 'Envio por DM desativado nesta criação.' in text


def test_phase35_backend_sanitizes_invite_numeric_options_and_returns_info() -> None:
    text = MESA.read_text(encoding="utf-8")
    assert 'def _safe_int' in text
    assert 'expire_seconds = _safe_int(payload.get("expira_em_segundos")' in text
    assert 'member_limit = _safe_int(payload.get("limite_membros")' in text
    assert 'telegram_payload.pop("member_limit", None)' in text
    assert 'response["convite_info"]' in text
    assert '"solicitar_aprovacao": bool(telegram_payload.get("creates_join_request", False))' in text


def test_phase35_alvos_query_has_single_from_clause() -> None:
    text = MESA.read_text(encoding="utf-8")
    assert 'FROM eq_alvos\n                FROM eq_alvos' not in text
