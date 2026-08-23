"""telegram handlers — carrega base estavel e aplica start/help publicos."""
from __future__ import annotations

import re
import urllib.request

_SRC_URL = (
    "https://raw.githubusercontent.com/romastefale/tr4/"
    "aefc7e2d3ec9860f83310a27635da69276d75b09/app/bot/telegram.py"
)

_WRAPPERS = (
    "def _start_text(message: Message) -> str:\n"
    "    from app.bot.help_texts import build_start_text\n"
    "    return build_start_text(message, is_owner=_is_owner_message(message))\n"
    "\n"
    "\n"
    "def _help_text(message: Message) -> str:\n"
    "    from app.bot.help_texts import build_help_text\n"
    "    return build_help_text(message, is_owner=_is_owner_message(message))\n"
    "\n"
    "\n"
)


def _load() -> dict:
    with urllib.request.urlopen(_SRC_URL, timeout=45) as resp:
        src = resp.read().decode("utf-8")
    pattern = (
        r"def _start_text\(message: Message\) -> str:.*?"
        r"def _help_text\(message: Message\) -> str:.*?"
        r"(?=\n\n# Negrito unicode)"
    )
    src2, n = re.subn(pattern, _WRAPPERS, src, count=1, flags=re.S)
    if n != 1:
        raise RuntimeError(f"telegram help patch failed n={n}")
    ns: dict = {"__name__": "app.bot.telegram", "__file__": __file__}
    exec(compile(src2, __file__, "exec"), ns)
    return ns


_NS = _load()
globals().update({k: v for k, v in _NS.items() if not k.startswith("__")})
