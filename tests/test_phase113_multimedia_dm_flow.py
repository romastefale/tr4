from pathlib import Path

MULTI = Path("app/equalizador/multimidia.py").read_text(encoding="utf-8")
TG = Path("app/bot/telegram.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase113_session_ref_hint_is_extracted_from_force_reply():
    assert 'extract_multimedia_session_ref' in MULTI
    assert 'session_ref_hint' in MULTI
    assert 'Sessão {payload}' in TG
    assert 'reply_to_message' in TG


def test_phase113_diagnostic_endpoint_exists():
    assert '/multimidia/sessoes/{session_ref}/diagnostico' in ROUTER
    assert 'multimedia_session_diagnostic' in ROUTER
    assert 'faltando' in ROUTER


def test_phase113_publication_reports_missing_ready_reasons():
    assert 'conteúdo no privado do bot' in MULTI
    assert 'estado pronto' in MULTI
    assert 'Sessão ainda não está pronta.' in MULTI
