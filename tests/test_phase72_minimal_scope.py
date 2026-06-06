import ast
from pathlib import Path


def _html() -> str:
    source = Path('app/equalizador/router.py').read_text(encoding='utf-8')
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '_EQUALIZADOR_HTML':
                    return ast.literal_eval(node.value)
    raise AssertionError('_EQUALIZADOR_HTML não encontrado')


def test_phase72_removes_redundant_group_name_and_home_hints():
    html = _html()
    assert 'Fase 72: limpeza minimalista estrita conforme prints.' in html
    assert '<p class="section-note">Escolha um grupo ou pesquise uma ação.</p>' not in html
    assert '<p id="palcos_hint" class="section-note"></p>' in html
    assert 'body.phase68-minimal #palcos_hint { display: none !important; }' in html
    assert 'document.getElementById("mesa_titulo").textContent = "Ações";' in html
    assert 'body.phase68-minimal #mesa_titulo { display: none !important; }' in html


def test_phase72_group_card_has_title_description_and_single_meta_line():
    html = _html()
    assert 'grupoDescricao ? ` <span class="inline-dot">•</span> <span class="group-desc-inline">${escapeHtml(grupoDescricao)}</span>`' in html
    assert 'body.phase68-minimal #grupo_descricao { display: none !important; }' in html
    assert 'recursos.filter(Boolean).join(" • ")' in html
    assert 'grupo.tipo' not in html
    assert 'grupo_membros' not in html


def test_phase72_status_and_refresh_are_not_repeated_below_card():
    html = _html()
    assert 'body.phase68-minimal .refresh-state { display: none !important; }' in html
    assert 'statusMesa("Pronto", "ok");' in html
    assert 'Pronto. Ações disponíveis conforme permissões.' not in html
    assert 'setRefreshState("", "loading");' in html


def test_phase72_select_does_not_keep_selected_group_name_visible():
    html = _html()
    assert 'function syncPalcoHeaderSelect(selectedRef)' in html
    assert 'opt.textContent = opt.value === selectedRef ? "Grupo selecionado"' in html
    assert 'headerSelect.appendChild(option("", "Selecionar grupo"));' in html
    assert 'headerSelect.appendChild(option(palco.grp_ref, palco.titulo || "Grupo"));' in html


def test_phase72_keeps_action_buttons_in_two_columns_when_possible():
    html = _html()
    assert 'body.phase68-minimal .view .toolbar:not(.app-tabs)' in html
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in html


def test_phase72_preserves_js_escape_guards():
    html = _html()
    assert 'split(/\\s+/).filter' in html
    assert 'split(/\\n+/)' in html
    assert 'split(/\n+/)' not in html.replace('split(/\\n+/)', '')
