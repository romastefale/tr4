from pathlib import Path

from app.equalizador.identity import make_ui_ref, public_tme_url, safe_public_username


def test_phase52_identity_accepts_join_and_invite_aliases() -> None:
    assert make_ui_ref("ent", "chat:user", "secret").startswith("ent_")
    assert make_ui_ref("inv", "chat:link", "secret").startswith("inv_")


def test_phase52_public_username_helpers_are_tme_only() -> None:
    assert safe_public_username("@usuario_ok") == "usuario_ok"
    assert public_tme_url("@usuario_ok") == "https://t.me/usuario_ok"
    assert public_tme_url("bad/slash") == ""


def test_phase52_router_semantic_buttons_and_public_username_policy() -> None:
    text = open("app/equalizador/router.py", encoding="utf-8").read()
    assert 'data-action="admins.promover"' in text and 'background: #168a55' in text
    assert 'data-action="silencio.ativar"' in text and 'background: #c77800' in text
    assert 'data-action="admins.rebaixar"' in text and 'background: #b42318' in text
    assert "https://t.me/${username}" in text
    assert "tg://user?id" not in text
    assert "perfil oculto" not in text.split("// Compatibilidade de testes antigos:", 1)[0]


def test_phase52_group_photo_uses_availability_and_failure_cache() -> None:
    text = open("app/equalizador/router.py", encoding="utf-8").read()
    assert "fotosGrupoIndisponiveis" in text
    assert "loadPalcoPhoto(currentPalco && currentPalco.grp_ref, Boolean(palco.foto_disponivel))" in text


def test_phase52_application_sources_do_not_emit_tg_user_id_links() -> None:
    source_paths = [
        Path("app/equalizador/router.py"),
        Path("app/equalizador/mesa.py"),
        Path("app/bot/telegram.py"),
        Path("app/bot/monthfm.py"),
        Path("app/bot/weekfm.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)
    assert "tg://user" not in combined
    assert "https://t.me/" in combined
