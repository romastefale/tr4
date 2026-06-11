from __future__ import annotations

from pathlib import Path

import pytest

from app.equalizador.governante_webapp import action_allowed_by_package, package_actions


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/equalizador/router.py"


def test_governante_packages_match_agreed_scope() -> None:
    assert "mensagens.enviar" in package_actions("basico")
    assert "mensagens.enviar_foto" in package_actions("basico")
    assert "broadcast.musical.webapp" in package_actions("basico")
    assert "mensagens.apagar" in package_actions("moderador")
    assert "membros.remover" in package_actions("moderador")
    assert "membros.reintegrar" in package_actions("moderador")
    assert "convites.criar" in package_actions("moderador")
    assert not action_allowed_by_package(pacote="avancado", action="mensagens.apagar_lote").permitido
    assert not action_allowed_by_package(pacote="avancado", action="ddx.configurar").permitido


def test_mesa_supports_send_photo_with_caption_and_msg_ref_registration_author() -> None:
    pytest.importorskip("sqlalchemy")
    from app.equalizador.mesa import ACTION_SPECS, build_action_payload

    assert ACTION_SPECS["mensagens.enviar_foto"].telegram_method == "sendPhoto"
    payload, alvo_ref, resumo = build_action_payload(
        ajuste="mensagens.enviar_foto",
        palco_id=-1001234567890,
        payload={"foto": "https://example.com/a.jpg", "legenda": "Legenda", "sem_notificacao": True},
    )
    assert payload["photo"] == "https://example.com/a.jpg"
    assert payload["caption"] == "Legenda"
    assert payload["disable_notification"] is True
    assert alvo_ref is None
    assert resumo == "Legenda"


def test_ban_payload_always_revokes_messages() -> None:
    sqlalchemy = pytest.importorskip("sqlalchemy")
    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    msg_engine = engine
    from app.equalizador.mesa import build_action_payload, register_alvo_ref

    alvo_ref = register_alvo_ref(
        chat_id=-1001234567890,
        user_id=123,
        nome_publico="Autor",
        alias_secret="secret",
        db_engine=msg_engine,
    )
    payload, target_ref, _ = build_action_payload(
        ajuste="membros.remover",
        palco_id=-1001234567890,
        payload={"alvo_ref": alvo_ref, "revogar_mensagens": False},
        db_engine=msg_engine,
    )
    assert target_ref == alvo_ref
    assert payload["revoke_messages"] is True


def test_message_author_link_can_resolve_only_when_author_was_seen() -> None:
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from app.equalizador.mesa import MesaTargetError, register_mensagem_ref, resolve_alvo_from_mensagem_ref

    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    msg_ref = register_mensagem_ref(
        chat_id=-1001234567890,
        message_id=77,
        resumo_publico="mensagem do autor",
        alias_secret="secret",
        autor_user_id=456,
        autor_nome_publico="Pessoa Autora",
        db_engine=engine,
    )
    alvo = resolve_alvo_from_mensagem_ref(palco_id=-1001234567890, msg_ref=msg_ref, db_engine=engine)
    assert alvo["alvo_ref"].startswith("usr_")
    assert alvo["nome"] == "Pessoa Autora"

    msg_sem_autor = register_mensagem_ref(
        chat_id=-1001234567890,
        message_id=78,
        resumo_publico="sem autor",
        alias_secret="secret",
        db_engine=engine,
    )
    try:
        resolve_alvo_from_mensagem_ref(palco_id=-1001234567890, msg_ref=msg_sem_autor, db_engine=engine)
    except MesaTargetError as exc:
        assert "Autor da mensagem" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("mensagem sem autor conhecido não deveria resolver alvo")


def test_router_exposes_governante_webapp_actions_without_id_for_delete() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert '"mensagens.enviar_foto": "mensagens/enviar-foto"' in source
    assert '@router.post("/api/palcos/{grp_ref}/mensagens/enviar-foto")' in source
    assert 'placeholder="ID numérico, usr_... ou link de mensagem"' in source
    assert 'allow_username=False' in source
    assert '"mensagens.enviar_foto": "mensagens.enviar"' in source
    assert 'solicitar_aprovacao: true' in source
    assert 'limite_membros: 0' in source
