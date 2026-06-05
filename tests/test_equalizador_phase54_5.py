from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase54_5_convites_window_has_selected_invite_controls() -> None:
    source = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="convites_resumo"' in source
    assert 'id="convite_detalhe"' in source
    assert 'id="convites_lista"' in source
    assert 'id="copiar_convite_selecionado"' in source
    assert 'id="abrir_convite_selecionado"' in source
    assert 'function updateConviteSelecionado()' in source
    assert 'function renderConvitesLista(rows)' in source
    assert 'Convite já revogado' in source


def test_phase54_5_topicos_window_has_selected_topic_and_general_sections() -> None:
    source = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="topicos_resumo"' in source
    assert 'id="topico_detalhe"' in source
    assert 'id="topicos_lista"' in source
    assert 'Tópico selecionado' in source
    assert 'Tópico geral' in source
    assert 'function updateTopicoSelecionado()' in source
    assert 'function renderTopicosLista(rows)' in source
    assert 'Tópico já marcado como apagado' in source
