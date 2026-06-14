from __future__ import annotations

import pytest


class FailingBot:
    async def get_chat(self, user_id: int):
        raise RuntimeError("telegram profile unavailable")


@pytest.mark.asyncio
async def test_display_name_falls_back_to_lastfm_username(monkeypatch):
    from app.bot import tnow

    monkeypatch.setattr(tnow, "_lastfm_display_name", lambda user_id: "romastefale")

    assert await tnow._display_name(FailingBot(), 8505890439) == "romastefale"


@pytest.mark.asyncio
async def test_display_name_never_exposes_numeric_id(monkeypatch):
    from app.bot import tnow

    monkeypatch.setattr(tnow, "_lastfm_display_name", lambda user_id: None)

    assert await tnow._display_name(FailingBot(), 8505890439) == "Usuário cadastrado"
