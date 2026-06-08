from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.equalizador import router as equalizador_router
from app.equalizador.security import TelegramWebAppIdentity


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(equalizador_router.router)
    return TestClient(app)


def _identity() -> TelegramWebAppIdentity:
    return TelegramWebAppIdentity(
        user_id=123456,
        user={"id": 123456, "first_name": "Teste", "username": "teste"},
        auth_date=1,
    )


def _mock_identity(monkeypatch) -> None:
    monkeypatch.setattr(equalizador_router, "_public_identity_from_authorization", lambda _authorization: _identity())


def test_render_result_text_only_shows_download_button() -> None:
    html = equalizador_router._PUBLIC_MUSIC_HTML
    start = html.index("function renderResult(data)")
    end = html.index("\n  async function loadPlayingPreview", start)
    render_result_source = html[start:end]

    assert 'data.text||data.message' in render_result_source
    assert 'if(resultDownloadTarget(data,image)||data.text||data.message)addAction("Baixar",downloadResult);' in render_result_source


def test_public_execute_command_tly_valid_session_sends_dm(monkeypatch) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_command(command_name: str, group_ref=None, period: str = "week", authorization=None):
        assert command_name == "tly"
        assert authorization == "eqs valid"
        return {"title": "Letra", "text": "Resultado real do comando", "filename": "tly.txt"}

    async def fake_bot_api(method: str, payload: dict[str, object]):
        sent.append((method, payload))
        return {"ok": True}

    _mock_identity(monkeypatch)
    monkeypatch.setattr(equalizador_router, "public_music_command", fake_command)
    monkeypatch.setattr(equalizador_router, "_bot_api", fake_bot_api)

    res = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "tly", "format": "dm"},
    )

    assert res.status_code == 200
    assert res.json() == {"ok": True, "sent": True, "command": "tly", "message": "Enviado na sua DM."}
    assert sent == [("sendMessage", {"chat_id": 123456, "text": "Letra\n\nResultado real do comando"})]


def test_public_execute_command_playing_sends_photo_when_cover_url_exists(monkeypatch) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_command(command_name: str, group_ref=None, period: str = "week", authorization=None):
        assert command_name == "playing"
        return {"title": "Tocando", "text": "Música — Artista", "cover_url": "https://cdn.example.com/cover.png"}

    async def fake_bot_api(method: str, payload: dict[str, object]):
        sent.append((method, payload))
        return {"ok": True}

    _mock_identity(monkeypatch)
    monkeypatch.setattr(equalizador_router, "public_music_command", fake_command)
    monkeypatch.setattr(equalizador_router, "_bot_api", fake_bot_api)

    res = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "playing", "format": "dm"},
    )

    assert res.status_code == 200
    assert sent == [
        (
            "sendPhoto",
            {
                "chat_id": 123456,
                "photo": "https://cdn.example.com/cover.png",
                "caption": "Tocando\n\nMúsica — Artista",
            },
        )
    ]


def test_public_execute_command_nowp_requires_group_and_uses_nowp_flow(monkeypatch) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    called: list[str] = []

    async def fake_nowp(request, authorization=None):
        called.append(authorization or "")
        return {"ok": True, "message": "Publicado em Grupo Teste."}

    async def fake_bot_api(method: str, payload: dict[str, object]):
        sent.append((method, payload))
        return {"ok": True}

    _mock_identity(monkeypatch)
    monkeypatch.setattr(equalizador_router, "public_music_nowp", fake_nowp)
    monkeypatch.setattr(equalizador_router, "_bot_api", fake_bot_api)

    missing = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "nowp", "format": "dm"},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "Escolha um grupo antes de enviar."

    res = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "nowp", "group_ref": "grp_ok", "format": "dm"},
    )
    assert res.status_code == 200
    assert called == ["eqs valid"]
    assert sent == [("sendMessage", {"chat_id": 123456, "text": "Publicar\n\nPublicado em Grupo Teste."})]


def test_public_execute_command_invalid_command_returns_400(monkeypatch) -> None:
    _mock_identity(monkeypatch)

    res = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "rm-rf", "format": "dm"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Comando indisponível para envio."


def test_public_execute_command_group_required_without_group_ref_returns_400(monkeypatch) -> None:
    _mock_identity(monkeypatch)

    res = _client().post(
        "/equalizador/api/public/execute-command",
        headers={"Authorization": "eqs valid"},
        json={"command": "songcharts", "format": "dm"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Escolha um grupo antes de enviar."


def test_public_execute_command_without_session_returns_401(monkeypatch) -> None:
    def fake_identity(_authorization: str | None) -> TelegramWebAppIdentity:
        raise HTTPException(status_code=401, detail="Abra pelo Telegram para continuar.")

    monkeypatch.setattr(equalizador_router, "_public_identity_from_authorization", fake_identity)

    res = _client().post(
        "/equalizador/api/public/execute-command",
        json={"command": "tly", "format": "dm"},
    )

    assert res.status_code == 401
    assert res.json()["detail"] == "Abra pelo Telegram para continuar."


def test_public_download_text_returns_attachment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(equalizador_router, "_PUBLIC_DOWNLOAD_DIR", tmp_path)
    _mock_identity(monkeypatch)

    prepared = _client().post(
        "/equalizador/api/public/download-result",
        headers={"Authorization": "eqs valid"},
        json={"target": "data:text/plain;base64,cmVzdWx0YWRvCg==", "filename": "tigraoRADIO_tly_20260608_120000.txt"},
    )
    assert prepared.status_code == 200

    res = _client().get(prepared.json()["download_url"])

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "attachment" in res.headers["content-disposition"]
    assert "tigraoRADIO_tly_20260608_120000.txt" in res.headers["content-disposition"]
    assert res.content == b"resultado\n"


def test_public_download_remote_large_file_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(equalizador_router, "_PUBLIC_DOWNLOAD_DIR", tmp_path)
    _mock_identity(monkeypatch)

    class LargeResponse:
        headers = {"content-length": str(equalizador_router._PUBLIC_DOWNLOAD_MAX_BYTES + 1), "content-type": "text/plain"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"x"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str):
            assert method == "GET"
            assert url == "https://93.184.216.34/large.txt"
            return LargeResponse()

    monkeypatch.setattr(equalizador_router.httpx, "AsyncClient", FakeClient)

    res = _client().post(
        "/equalizador/api/public/download-result",
        headers={"Authorization": "eqs valid"},
        json={"target": "https://93.184.216.34/large.txt", "filename": "large.txt"},
    )

    assert res.status_code == 413
    assert res.json()["detail"] == "Arquivo grande demais para download pelo Mini App."


def test_public_download_remote_redirect_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(equalizador_router, "_PUBLIC_DOWNLOAD_DIR", tmp_path)
    _mock_identity(monkeypatch)

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/arquivo.txt"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("follow_redirects") is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str):
            assert method == "GET"
            assert url == "https://93.184.216.34/redirect"
            return RedirectResponse()

    monkeypatch.setattr(equalizador_router.httpx, "AsyncClient", FakeClient)

    res = _client().post(
        "/equalizador/api/public/download-result",
        headers={"Authorization": "eqs valid"},
        json={"target": "https://93.184.216.34/redirect", "filename": "redirect.txt"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Redirecionamento remoto bloqueado para download."
