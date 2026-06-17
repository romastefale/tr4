from __future__ import annotations

import logging
import os
import sys

import uvicorn

from app.logging_safety import configure_safe_logging


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
configure_safe_logging()
logger = logging.getLogger("tr4.bootstrap")


def _port_from_env() -> int:
    raw = os.getenv("PORT", "8000").strip() or "8000"
    try:
        return int(raw)
    except ValueError:
        logger.warning("PORT_INVALID value=%r fallback=8000", raw)
        return 8000


if __name__ == "__main__":
    port = _port_from_env()
    logger.info("BOOTSTRAP_START host=0.0.0.0 port=%s app=app.main:app", port)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info").lower(),
    )
