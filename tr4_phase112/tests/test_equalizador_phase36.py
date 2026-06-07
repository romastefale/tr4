from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_phase36_adds_silence_deactivation_channel_route_and_button() -> None:
    permissions = read("app/equalizador/permissions.py")
    afinacao = read("app/equalizador/afinacao.py")
    router = read("app/equalizador/router.py")
    assert 'CanalDefinition("silencio.desativar", "Desativar modo silêncio", critico=True)' in permissions
    assert '"codigo": "silencio.desativar"' in afinacao
    assert '"direitos": ("can_restrict_members",)' in afinacao
    assert 'data-action="silencio.desativar"' in router
    assert '"silencio.desativar": "silencio/desativar"' in router
    assert '@router.post("/api/palcos/{grp_ref}/silencio/desativar")' in router


def test_phase36_transmission_has_options_and_export_box() -> None:
    router = read("app/equalizador/router.py")
    assert 'id="transmissao_preview"' in router
    assert 'id="transmissao_silenciosa"' in router
    assert 'id="transmissao_fixar"' in router
    assert 'id="exportacao_resultado"' in router
    assert 'fixar: Boolean(document.getElementById("transmissao_fixar").checked)' in router
    assert 'box.value = exp.json_texto || JSON.stringify(exp, null, 2)' in router


def test_phase36_maestro_backend_stores_silence_state_and_can_restore() -> None:
    maestro = read("app/equalizador/maestro.py")
    assert 'CREATE TABLE IF NOT EXISTS eq_silencio_estado' in maestro
    assert 'telegram_api_call(bot_token, "getChat", {"chat_id": palco_id})' in maestro
    assert 'def build_silencio_desativar_payload' in maestro
    assert 'async def executar_modo_silencio_desativar' in maestro
    assert '"silencio.desativar"' in maestro
    assert '_mark_silencio_inativo' in maestro


def test_phase36_transmission_can_pin_but_keeps_send_success_if_pin_fails() -> None:
    maestro = read("app/equalizador/maestro.py")
    assert 'if bool(payload.get("fixar")) and message_id is not None:' in maestro
    assert 'required_right="can_pin_messages"' in maestro
    assert '"pinChatMessage"' in maestro
    assert 'fixacao = {"ok": False, "motivo": mesa_error_public_detail(exc)}' in maestro
    assert 'response["fixacao"] = fixacao' in maestro


def test_phase36_export_contains_sanitized_json_text() -> None:
    maestro = read("app/equalizador/maestro.py")
    assert 'payload["json_texto"] = json.dumps(payload, ensure_ascii=False, indent=2)' in maestro
