from pathlib import Path


def test_phase46_frontend_uses_array_in_load_palco_data_promise_all():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert 'const [afinacaoRes, mensagensRes, alvosRes, historicoRes, distribuicaoRes, painelRes, entradasRes, convitesRes, topicosRes, remetentesRes] = await Promise.all([' in text
    assert 'api(base + "/canais-remetentes").then((r) => r.ok ? r.json() : { remetentes: [] }).catch(() => ({ remetentes: [] }))\n        ]);' in text


def test_phase46_loading_message_still_exists():
    text = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    assert 'Afinando acesso…' in text
    assert 'fetch("/equalizador/api/me"' in text
