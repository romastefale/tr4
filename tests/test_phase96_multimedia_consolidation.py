from pathlib import Path

MULTI = Path("app/equalizador/multimidia.py").read_text(encoding="utf-8")
BOT = Path("app/bot/telegram.py").read_text(encoding="utf-8")
ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_phase96_accepts_all_native_telegram_content_types():
    for kind in ["text", "photo", "video", "document", "audio", "voice", "animation"]:
        assert kind in MULTI


def test_phase96_animation_is_collected_and_published_natively():
    assert 'getattr(message, "animation", None)' in BOT
    assert 'sendAnimation' in MULTI
    assert 'can_send_documents' in MULTI


def test_phase96_public_labels_are_translated_for_webapp():
    assert 'estado' in MULTI
    assert 'tipo_label' in MULTI
    assert 'Pronto para publicar' in MULTI
    assert 'Crie uma sessão. O Telegram coleta texto, foto, vídeo, áudio, voz, documento ou animação' in ROUTER
