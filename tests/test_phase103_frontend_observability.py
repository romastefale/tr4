from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
MAIN = Path("app/main.py").read_text(encoding="utf-8")


def test_phase103_client_error_payload_has_stack_path_and_restricted_script_kind():
    assert 'script_error_restrito' in ROUTER
    assert 'payload.extra' in ROUTER
    assert 'href:' in ROUTER
    assert 'detalhe=%s' in ROUTER


def test_phase103_multimedia_handlers_are_wrapped_for_observable_errors():
    assert 'safeAsync("multimidia_iniciar_failed", iniciarMultimediaNativa)' in ROUTER
    assert 'safeAsync("multimidia_publicar_failed", publicarMultimediaSessao)' in ROUTER
    assert 'reportException("multimidia_preview_failed", error)' in ROUTER


def test_phase103_root_favicon_removes_404_noise():
    assert '@app.get("/favicon.ico", include_in_schema=False)' in MAIN
    assert 'root_favicon' in MAIN
