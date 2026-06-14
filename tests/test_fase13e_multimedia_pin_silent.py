from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
MULTIMIDIA = (ROOT / "app/equalizador/multimidia.py").read_text(encoding="utf-8")


def test_webapp_multimedia_has_publish_and_silent_pin_button() -> None:
    assert 'id="multimidia_publicar"' in ROUTER
    assert 'id="multimidia_publicar_fixar_silencio"' in ROUTER
    assert 'Publicar e fixar em silêncio' in ROUTER
    assert '() => publicarMultimediaSessao(true)' in ROUTER
    assert 'JSON.stringify({ fixar_silencio: !!fixarSilencio })' in ROUTER


def test_multimedia_publish_endpoint_accepts_silent_pin_flag() -> None:
    assert 'request: Request' in ROUTER
    assert 'body = await request.json()' in ROUTER
    assert 'fixar_silencio = bool(body.get("fixar_silencio"))' in ROUTER
    assert 'fixar_silencio=fixar_silencio' in ROUTER


def test_multimedia_backend_pins_first_published_message_silently_without_retry_duplication() -> None:
    assert 'fixar_silencio: bool = False' in MULTIMIDIA
    assert 'required_right="can_pin_messages"' in MULTIMIDIA
    assert '"pinChatMessage"' in MULTIMIDIA
    assert '"disable_notification": True' in MULTIMIDIA
    assert 'publicação já aconteceu; não marca a sessão como falha para evitar duplicidade em retry' in MULTIMIDIA
    assert '"fixacao": {"solicitada": bool(fixar_silencio)' in MULTIMIDIA
