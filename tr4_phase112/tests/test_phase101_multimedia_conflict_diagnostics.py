from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase101_multimedia_conflict_returns_structured_session():
    assert '"codigo": "multimidia_conflito_estado"' in ROUTER
    assert '"sessao": sessao_publica' in ROUTER
    assert 'public_multimedia_session(get_multimedia_session(session_ref=session_ref))' in ROUTER


def test_phase101_frontend_uses_structured_conflict_message():
    assert 'detail.sessao && detail.sessao.session_ref' in ROUTER
    assert 'multimediaSessionsPorRef.set(detail.sessao.session_ref, detail.sessao)' in ROUTER
    assert 'detail.mensagem || detail.message' in ROUTER


def test_phase101_awaiting_session_preview_is_actionable():
    assert 'falta enviar conteúdo no privado' in ROUTER
