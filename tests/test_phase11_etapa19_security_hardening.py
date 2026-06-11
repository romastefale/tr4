from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
SHOW = (ROOT / "app/bot/show_owner.py").read_text(encoding="utf-8")


def test_equalizador_innerhtml_dynamic_channel_and_status_are_escaped():
    assert 'escapeHtml(canal.nome || canal.codigo || "Canal")' in ROUTER
    assert 'item.innerHTML = `<strong>${canal.nome}</strong>' not in ROUTER
    assert 'statusEl.innerHTML="<strong>"+escapeHtml(title||"Diagnóstico")+"</strong>"+escapeHtml(msg||"")' in ROUTER
    assert 'statusEl.innerHTML="<strong>"+(title||"Diagnóstico")+"</strong>"+(msg||"")' not in ROUTER


def test_public_player_urls_are_http_only_before_entering_html_attributes():
    assert 'function safeUrl(v)' in ROUTER
    assert 'const url=safeUrl(track.spotify_url||"")' in ROUTER
    assert 'const coverUrl=safeUrl(track.cover_url||"")' in ROUTER
    assert 'const photo=safeUrl(group&&group.photo_url)' in ROUTER
    assert 'cover.src=track.cover_url' not in ROUTER


def test_client_error_endpoint_has_size_and_markup_hardening():
    assert 'content-length' in ROUTER
    assert '> 4096' in ROUTER
    assert 'text_value = text_value.replace("<", "‹").replace(">", "›")' in ROUTER


def test_show_owner_callbacks_are_allowlisted_and_logged():
    assert 'def _valid_show_callback_data' in SHOW
    assert '_SHOW_SIMPLE_ACTIONS' in SHOW
    assert 'SHOW_OWNER_INVALID_CALLBACK' in SHOW
    assert 'Ação inválida ou expirada.' in SHOW
    assert 'Grupo indisponível ou expirado.' in SHOW
    assert 'Governante indisponível ou expirado.' in SHOW


def test_show_owner_ddx_text_is_limited_before_persistence():
    assert 'def _sanitize_ddx_owner_word' in SHOW
    assert '_DDX_OWNER_WORD_MAX_LEN = 80' in SHOW
    assert 'Evitei salvar texto com sinais de HTML' in SHOW
    assert 'word, error = _sanitize_ddx_owner_word(message.text)' in SHOW
