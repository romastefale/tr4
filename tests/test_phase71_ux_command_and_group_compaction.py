import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "equalizador" / "router.py"
COMMANDS = ROOT / "app" / "bot" / "setup_commands.py"
DOC = ROOT / "TR4_MUSIC_ONLY.md"


def _html() -> str:
    source = ROUTER.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_EQUALIZADOR_HTML":
                    return ast.literal_eval(node.value)
    raise AssertionError("_EQUALIZADOR_HTML não encontrado")


def test_phase71_public_commands_overwrite_stale_panel_scopes():
    text = COMMANDS.read_text(encoding="utf-8")
    assert "BotCommandScopeAllPrivateChats" in text
    assert "BotCommandScopeAllGroupChats" in text
    assert "BotCommandScopeAllChatAdministrators" in text
    assert 'CommandDef("login", "Conectar Spotify")' in text
    for stale in ('CommandDef("tigrao"', 'CommandDef("owner"', 'CommandDef("radio"', 'CommandDef("btb"'):
        assert stale not in text


def test_phase71_docs_do_not_advertise_old_panel_commands_as_removed_tutorial_list():
    text = DOC.read_text(encoding="utf-8")
    assert "Comandos públicos exibidos no menu" in text
    assert "Painéis antigos ou operacionais não devem aparecer no menu público" in text
    assert "`/login`" in text


def test_phase71_home_is_compact_and_group_meta_is_single_line():
    html = _html()
    assert 'id="grupo_meta_linha"' in html
    assert 'id="grupo_tipo"' not in html
    assert 'id="grupo_membros"' not in html
    assert 'id="grupo_estado"' not in html
    assert 'id="grupo_recursos"' not in html
    assert 'id="grupo_card_status"' in html
    assert 'body.phase68-minimal #app > .top { display: none !important; }' in html
    assert 'metricas.textContent = `${usuarios} usuários • ${palcos} grupos • ${operadores} operadores`;' in html
    assert 'recursos.filter(Boolean).join(" • ")' in html


def test_phase71_preserves_js_escape_guards():
    html = _html()
    assert "split(/\\s+/).filter" in html
    assert "split(/\\n+/)" in html
    assert "split(/\n+/)" not in html.replace("split(/\\n+/)", "")
