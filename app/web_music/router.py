from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.bot.music_command_runner import (
    MusicCommandError,
    current_track_preview,
    execute_dm_music_command,
    execute_group_music_command,
    execute_nowp_publish,
    execute_story_music_command,
    execute_universal_songcharts,
    list_common_music_groups,
)
from app.web_music.auth import authenticate_web_music_request
from app.web_music.state import get_web_music_bot

logger = logging.getLogger(__name__)
router = APIRouter()
_PLAYER_HTML = Path(__file__).with_name("player.html")
_ALLOWED_GROUP_COMMANDS = {"nowp", "weekfm", "monthfm", "tcanvas", "tly", "tnow", "songcharts"}


class GroupCommandPayload(BaseModel):
    command: str | None = None
    group_ref: str | None = None
    period: str | None = None
    target: str | None = None
    format: str | None = None


class ClientErrorPayload(BaseModel):
    kind: str | None = None
    message: str | None = None
    extra: str | None = None
    href: str | None = None
    source: str | None = None
    phase: str | None = None
    age_ms: str | None = None
    user_agent: str | None = None


def _bot_or_503():
    bot = get_web_music_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail={"code": "bot_not_ready", "message": "Bot não está pronto."})
    return bot


def _error_response(exc: MusicCommandError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "code": exc.code, "message": exc.message, "group_title": exc.group_title},
        status_code=exc.status_code,
    )


@router.get("/player", response_class=HTMLResponse)
def player() -> HTMLResponse:
    return HTMLResponse(_PLAYER_HTML.read_text(encoding="utf-8"))


@router.get("/api/public/ping")
def public_ping() -> dict[str, Any]:
    return {"ok": True, "mode": "music_only_web"}


@router.post("/api/client-error")
async def client_error(payload: ClientErrorPayload) -> dict[str, bool]:
    # Log mínimo e sanitizado. Nunca grava Authorization/initData.
    logger.info(
        "WEB_MUSIC_CLIENT_EVENT kind=%s source=%s message=%s extra=%s",
        (payload.kind or "")[:60],
        (payload.source or "")[:40],
        (payload.message or "")[:160],
        (payload.extra or "")[:160],
    )
    return {"ok": True}


@router.get("/api/public/me")
async def public_me(request: Request) -> dict[str, Any]:
    user = authenticate_web_music_request(request)
    return {
        "ok": True,
        "user": user.public_dict(),
        "can_open_universal_songcharts": True,
    }


@router.get("/api/public/home")
async def public_home(request: Request) -> dict[str, Any]:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    groups = await list_common_music_groups(bot, user.id)
    track = await current_track_preview(user.id)
    return {"ok": True, "user": user.public_dict(), "groups": groups, "track": track}


@router.get("/api/public/playing-preview")
async def playing_preview(request: Request) -> dict[str, Any]:
    user = authenticate_web_music_request(request)
    return await current_track_preview(user.id)


@router.post("/api/public/nowp")
async def public_nowp(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    try:
        result = await execute_nowp_publish(
            bot,
            requester_id=user.id,
            requester_name=user.full_name,
            group_ref=payload.group_ref,
        )
    except MusicCommandError as exc:
        return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.post("/api/public/group-command")
async def group_command(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    command = (payload.command or "").strip().lower().lstrip("/")
    if command not in _ALLOWED_GROUP_COMMANDS:
        return JSONResponse(
            {
                "ok": False,
                "code": "command_not_allowed",
                "message": "Comando musical não permitido nesta tela.",
            },
            status_code=403,
        )
    try:
        result = await execute_group_music_command(
            bot,
            command=command,
            requester_id=user.id,
            requester_name=user.full_name,
            group_ref=payload.group_ref,
            period=payload.period,
        )
    except MusicCommandError as exc:
        return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.get("/api/public/command/{command_name}")
async def command_preview(request: Request, command_name: str, group_ref: str | None = None) -> Any:
    authenticate_web_music_request(request)
    command = command_name.strip().lower().lstrip("/")
    if command == "playing":
        user = authenticate_web_music_request(request)
        return await current_track_preview(user.id)
    return JSONResponse(
        {
            "ok": False,
            "code": "command_requires_send_endpoint",
            "message": "Use o botão de confirmação para executar este comando no Telegram.",
        },
        status_code=400,
    )


@router.post("/api/public/story-command")
async def story_command(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    target = getattr(payload, "target", None) or None
    try:
        result = await execute_story_music_command(
            bot,
            requester_id=user.id,
            requester_name=user.full_name,
            target=target,
            group_ref=payload.group_ref,
        )
    except MusicCommandError as exc:
        return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.post("/api/public/dm-command")
async def dm_command(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    command = (payload.command or "").strip().lower().lstrip("/")
    try:
        result = await execute_dm_music_command(
            bot,
            command=command,
            requester_id=user.id,
            requester_name=user.full_name,
        )
    except MusicCommandError as exc:
        return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.post("/api/public/execute-command")
@router.post("/api/public/send-command-copy")
async def execute_command_copy(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    command = (payload.command or "").strip().lower().lstrip("/")
    if payload.group_ref:
        try:
            result = await execute_group_music_command(
                bot,
                command=command,
                requester_id=user.id,
                requester_name=user.full_name,
                group_ref=payload.group_ref,
                period=payload.period,
            )
        except MusicCommandError as exc:
            return _error_response(exc)
    else:
        try:
            result = await execute_dm_music_command(
                bot,
                command=command,
                requester_id=user.id,
                requester_name=user.full_name,
            )
        except MusicCommandError as exc:
            return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.post("/api/public/songcharts-universal")
async def songcharts_universal(request: Request, payload: GroupCommandPayload) -> Any:
    user = authenticate_web_music_request(request)
    bot = _bot_or_503()
    try:
        result = await execute_universal_songcharts(
            bot,
            requester_id=user.id,
            requester_name=user.full_name,
            period=payload.period,
        )
    except MusicCommandError as exc:
        return _error_response(exc)
    return {"ok": True, "code": result.code, "message": result.message, "group_title": result.group_title}


@router.post("/api/public/download-result")
async def reserved_download_result(request: Request) -> JSONResponse:
    authenticate_web_music_request(request)
    return JSONResponse(
        {
            "ok": False,
            "code": "endpoint_not_available_music_only",
            "message": "Download direto não faz parte desta etapa musical.",
        },
        status_code=501,
    )
