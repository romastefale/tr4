from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase54_3_message_send_action_is_registered_in_sources() -> None:
    mesa = (ROOT / "app/equalizador/mesa.py").read_text(encoding="utf-8")
    permissions = (ROOT / "app/equalizador/permissions.py").read_text(encoding="utf-8")
    painel = (ROOT / "app/equalizador/painel.py").read_text(encoding="utf-8")
    configuracao = (ROOT / "app/equalizador/configuracao.py").read_text(encoding="utf-8")

    assert '"mensagens.enviar": MesaActionSpec("mensagens.enviar", "mensagens.enviar", "sendMessage", None, "palco")' in mesa
    assert 'if ajuste == "mensagens.enviar":' in mesa
    assert 'register_mensagem_ref(' in mesa
    assert '"pinChatMessage"' in mesa
    assert 'CanalDefinition("mensagens.enviar", "Enviar mensagens")' in permissions
    assert '{"codigo": "mensagens.enviar", "nome": "Enviar mensagem", "categoria": "Mensagens", "direitos": ()}' in painel
    assert '"mensagens.enviar": "Enviar mensagem"' in configuracao


def test_phase54_3_router_exposes_message_send_ui_route_and_fix_permission_guard() -> None:
    source = (ROOT / "app/equalizador/router.py").read_text(encoding="utf-8")
    assert 'id="mensagem_envio_texto"' in source
    assert 'id="mensagem_envio_sem_preview"' in source
    assert 'id="mensagem_envio_sem_notificacao"' in source
    assert 'id="mensagem_envio_fixar"' in source
    assert 'data-action="mensagens.enviar"' in source
    assert '"mensagens.enviar": "mensagens/enviar"' in source
    assert '@router.post("/api/palcos/{grp_ref}/mensagens/enviar")' in source
    assert 'ajuste="mensagens.enviar"' in source
    assert 'if ajuste == "mensagens.enviar" and bool(payload.get("fixar", False)):' in source
    assert 'canal_codigo="fixados.criar"' in source
    assert '["mensagens.apagar", "fixados.criar", "fixados.remover"].includes(action)' in source
