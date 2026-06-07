from pathlib import Path

ROUTER = Path("app/equalizador/router.py").read_text(encoding="utf-8")
AVANCADO = Path("app/equalizador/avancado.py").read_text(encoding="utf-8")


def test_phase105_topic_duplicate_preflight_exists():
    assert "def topic_name_exists" in AVANCADO
    assert "topico_nome_duplicado" in AVANCADO
    assert "Já existe um tópico registrado com esse nome" in AVANCADO


def test_phase105_topic_409_is_structured():
    assert '"code": "topico_conflito"' in ROUTER
    assert '"proximo_passo"' in ROUTER
    assert "Atualize a lista de tópicos" in ROUTER


def test_phase105_frontend_requires_topic_name():
    assert "Informe um nome para o novo tópico." in ROUTER
    assert 'nome || "Novo tópico"' not in ROUTER
