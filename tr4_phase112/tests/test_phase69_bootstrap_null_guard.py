from pathlib import Path


def _router_source() -> str:
    return Path("app/equalizador/router.py").read_text(encoding="utf-8")


def test_bot_revisoes_container_exists_for_bootstrap_render():
    src = _router_source()
    assert 'id="bot_revisoes"' in src
    assert 'const revisoes = document.getElementById("bot_revisoes")' in src


def test_bot_revisoes_append_child_is_null_guarded():
    src = _router_source()
    start = src.index('const revisoes = document.getElementById("bot_revisoes")')
    snippet = src[start:start + 500]
    assert 'if (revisoes)' in snippet
    assert 'revisoes.replaceChildren()' in snippet
    assert 'revisoes.appendChild(box)' in snippet


def test_all_get_element_by_id_targets_exist_in_static_html():
    import re
    src = _router_source()
    html_ids = set(re.findall(r'id="([^"]+)"', src))
    js_ids = set(re.findall(r'getElementById\("([^"]+)"\)', src))
    missing = js_ids - html_ids
    assert not missing, f"IDs usados no JS sem elemento HTML: {sorted(missing)}"
