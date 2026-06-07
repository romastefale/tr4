import pytest

pytest.importorskip("sqlalchemy")

from app.equalizador.afinacao import canais_from_bot_rights
from app.equalizador.avancado import ADVANCED_SPECS, build_advanced_payload, register_sender_chat_ref, register_topic_ref, list_sender_chats_publicos, list_topics_publicos
from app.equalizador.permissions import CANAL_BY_CODE


def test_phase44_channels_registered():
    for code in [
        "reacoes.recentes.limpar",
        "canais_remetentes.banir",
        "canais_remetentes.liberar",
        "membros.tag.definir",
        "topicos.criar",
        "topicos.editar",
        "topicos.fechar",
        "topicos.reabrir",
        "topicos.apagar",
        "topicos.desfixar",
        "topicos.geral.fechar",
        "topicos.geral.reabrir",
    ]:
        assert code in CANAL_BY_CODE


def test_phase44_afinacao_maps_advanced_rights():
    rows = canais_from_bot_rights({
        "status": "administrator",
        "can_delete_messages": True,
        "can_restrict_members": True,
        "can_manage_tags": True,
        "can_manage_topics": True,
        "can_pin_messages": True,
    })
    available = {row["codigo"] for row in rows if row["disponivel"]}
    assert "reacoes.recentes.limpar" in available
    assert "canais_remetentes.banir" in available
    assert "membros.tag.definir" in available
    assert "topicos.criar" in available
    assert "topicos.desfixar" in available


def test_phase44_specs_use_real_telegram_methods():
    assert ADVANCED_SPECS["reacoes.mensagem.limpar"].telegram_method == "deleteMessageReaction"
    assert ADVANCED_SPECS["reacoes.recentes.limpar"].telegram_method == "deleteAllMessageReactions"
    assert ADVANCED_SPECS["canais_remetentes.banir"].telegram_method == "banChatSenderChat"
    assert ADVANCED_SPECS["topicos.criar"].telegram_method == "createForumTopic"
    assert ADVANCED_SPECS["membros.tag.definir"].telegram_method == "setChatMemberTag"


def test_phase44_sender_and_topic_refs_roundtrip(tmp_path):
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path/'phase44.db'}")
    sender_ref = register_sender_chat_ref(chat_id=-1001, sender_chat_id=-2002, titulo_publico="Canal", alias_secret="s", db_engine=engine)
    topico_ref = register_topic_ref(chat_id=-1001, message_thread_id=44, nome_publico="Geral", alias_secret="s", db_engine=engine)
    assert sender_ref.startswith("snd_")
    assert topico_ref.startswith("top_")
    assert list_sender_chats_publicos(palco_id=-1001, db_engine=engine)[0]["sender_ref"] == sender_ref
    assert list_topics_publicos(palco_id=-1001, db_engine=engine)[0]["topico_ref"] == topico_ref


def test_phase44_build_topic_create_payload(tmp_path):
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path/'phase44_payload.db'}")
    payload, alvo_ref, label = build_advanced_payload(
        ajuste="topicos.criar",
        palco_id=-1001,
        payload={"nome": "Avisos"},
        alias_secret="s",
        db_engine=engine,
    )
    assert payload == {"chat_id": -1001, "name": "Avisos"}
    assert alvo_ref is None
    assert label == "Avisos"
