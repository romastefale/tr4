from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class LazyTR4App:
    """ASGI bootstrap shell for Railway.

    Railway healthchecks must reach a process listening on PORT and receiving
    HTTP requests. The full TR4 app imports Telegram, DB, web, music and plugin
    modules; any slow import or runtime startup must not prevent /healthz from
    answering. This shell exposes liveness immediately and loads app.main in a
    background task, while /readyz reports the real app state.
    """

    def __init__(self) -> None:
        self._health_app = FastAPI(title="TR4 Bootstrap")
        self._real_app: Any | None = None
        self._startup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._status = "pending"
        self._error: str | None = None
        self._configure_health_routes()

    def _configure_health_routes(self) -> None:
        @self._health_app.get("/healthz", status_code=200)
        def healthz() -> dict[str, str]:
            return {"status": "ok"}

        @self._health_app.get("/readyz")
        def readyz() -> JSONResponse:
            ok = self._status == "ready"
            return JSONResponse(
                {
                    "status": "ready" if ok else "not_ready",
                    "bootstrap": {
                        "real_app_status": self._status,
                        "real_app_error": self._error,
                    },
                },
                status_code=200 if ok else 503,
            )

    async def _ensure_real_app(self) -> Any | None:
        if self._real_app is not None:
            return self._real_app

        async with self._lock:
            if self._real_app is not None:
                return self._real_app

            self._status = "starting"
            self._error = None
            try:
                module = await asyncio.to_thread(importlib.import_module, "app.main")
                real_app = getattr(module, "app")
                await real_app.router.startup()
                self._real_app = real_app
                self._status = "ready"
                logger.info("TR4_REAL_APP_READY")
                return self._real_app
            except Exception as exc:
                self._status = "failed"
                self._error = f"{type(exc).__name__}: {exc}"
                logger.exception("TR4_REAL_APP_STARTUP_FAILED")
                return None

    async def _send_json(self, send, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _lifespan(self, receive, send) -> None:
        while True:
            message = await receive()
            message_type = message.get("type")

            if message_type == "lifespan.startup":
                self._startup_task = asyncio.create_task(self._ensure_real_app())
                await send({"type": "lifespan.startup.complete"})
                continue

            if message_type == "lifespan.shutdown":
                if self._startup_task and not self._startup_task.done():
                    self._startup_task.cancel()
                    try:
                        await self._startup_task
                    except asyncio.CancelledError:
                        pass
                if self._real_app is not None:
                    await self._real_app.router.shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def __call__(self, scope, receive, send) -> None:
        scope_type = scope.get("type")

        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return

        if scope_type == "http" and scope.get("path") in {"/healthz", "/readyz"}:
            await self._health_app(scope, receive, send)
            return

        real_app = await self._ensure_real_app()
        if real_app is None:
            await self._send_json(
                send,
                503,
                {
                    "ok": False,
                    "status": "not_ready",
                    "error": self._error,
                },
            )
            return

        await real_app(scope, receive, send)


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        LazyTR4App(),
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
