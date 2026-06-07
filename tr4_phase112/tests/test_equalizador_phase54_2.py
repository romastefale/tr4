from __future__ import annotations

import base64

import pytest

pytest.importorskip("sqlalchemy")

from app.equalizador.admin import (
    ADMIN_SPECS,
    build_admin_payload,
    executar_grupo_foto,
)
from app.equalizador.maestro import MAESTRO_CONFIRMATION_PHRASE


def test_phase54_2_group_photo_actions_are_registered() -> None:
    assert ADMIN_SPECS["grupo.foto"].telegram_method == "setChatPhoto"
    assert ADMIN_SPECS["grupo.foto"].direito == "can_change_info"
    assert ADMIN_SPECS["grupo.foto.remover"].telegram_method == "deleteChatPhoto"
    assert build_admin_payload(
        ajuste="grupo.foto.remover",
        palco_id=-1001234567890,
        payload={"confirmacao": MAESTRO_CONFIRMATION_PHRASE, "ciente": True},
        db_engine=None,
    ) == ({"chat_id": -1001234567890}, None, "Foto removida")


def test_phase54_2_router_exposes_group_photo_ui_and_routes() -> None:
    source = open("app/equalizador/router.py", encoding="utf-8").read()
    assert 'data-action="grupo.foto"' in source
    assert 'data-action="grupo.foto.remover"' in source
    assert 'id="grupo_foto_input" type="file"' in source
    assert '@router.post("/api/palcos/{grp_ref}/grupo/foto")' in source
    assert '@router.post("/api/palcos/{grp_ref}/grupo/foto/remover")' in source
    assert 'fileToBase64' in source


@pytest.mark.asyncio
async def test_phase54_2_execute_group_photo_uses_multipart_and_full_base64(tmp_path) -> None:
    from app.equalizador import admin as admin_module

    calls: list[tuple[str, str, object]] = []

    async def fake_api(token: str, method: str, payload: dict | None = None):
        calls.append(("api", method, payload))
        if method == "getMe":
            return {"id": 42}
        if method == "getChatMember":
            return {"status": "administrator", "can_change_info": True}
        raise AssertionError(method)

    class FakeResponse:
        is_success = True

        def json(self):
            return {"ok": True, "result": True}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, data=None, files=None):
            calls.append(("post", url, {"data": data, "files": files}))
            return FakeResponse()

    class DummyConn:
        def execute(self, *args, **kwargs):
            return None

    class DummyEngine:
        def begin(self):
            return self

        def __enter__(self):
            return DummyConn()

        def __exit__(self, *args):
            return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(admin_module.httpx, "AsyncClient", FakeClient)
    try:
        image = b"\xff\xd8" + b"a" * 300
        result = await executar_grupo_foto(
            palco={"telegram_chat_id": -100123, "ui_ref": "grp_publico"},
            ator_ref="usr_operador",
            payload={
                "imagem_base64": base64.b64encode(image).decode(),
                "mime_type": "image/jpeg",
                "nome_arquivo": "foto.jpg",
                "confirmacao": MAESTRO_CONFIRMATION_PHRASE,
                "ciente": True,
            },
            bot_token="123:abc",
            alias_secret="secret",
            db_engine=DummyEngine(),
            telegram_api_call_fn=fake_api,
        )
    finally:
        monkeypatch.undo()

    assert result["resultado"]["ajuste"] == "grupo.foto"
    upload_call = [call for call in calls if call[0] == "post"][0]
    upload = upload_call[2]
    assert upload["data"] == {"chat_id": "-100123"}
    filename, content, mime = upload["files"]["photo"]
    assert filename == "foto.jpg"
    assert content == image
    assert mime == "image/jpeg"
