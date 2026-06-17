from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
