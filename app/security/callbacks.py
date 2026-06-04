from __future__ import annotations

from dataclasses import dataclass


class CallbackParseError(ValueError):
    """Raised when inline callback data is malformed or unexpected."""


@dataclass(frozen=True)
class ParsedCallback:
    raw: str
    parts: tuple[str, ...]

    @property
    def action(self) -> str:
        return ":".join(self.parts)


def parse_callback(data: str | None, *, prefix: str | None = None, min_parts: int = 1) -> ParsedCallback:
    raw = str(data or "").strip()
    if not raw:
        raise CallbackParseError("callback vazio")
    if prefix is not None and not raw.startswith(prefix):
        raise CallbackParseError(f"callback fora do prefixo esperado: {prefix}")
    parts = tuple(part for part in raw.split(":") if part != "")
    if len(parts) < min_parts:
        raise CallbackParseError("callback incompleto")
    return ParsedCallback(raw=raw, parts=parts)


def trailing_int(data: str | None, *, prefix: str, name: str = "id", minimum: int | None = 0, maximum: int | None = None) -> int:
    parse_callback(data, prefix=prefix, min_parts=1)
    try:
        value = int(str(data).rsplit(":", 1)[-1])
    except (TypeError, ValueError) as exc:
        raise CallbackParseError(f"{name} inválido") from exc
    if minimum is not None and value < minimum:
        raise CallbackParseError(f"{name} abaixo do mínimo")
    if maximum is not None and value > maximum:
        raise CallbackParseError(f"{name} acima do máximo")
    return value


def page_number(data: str | None, *, prefix: str, default: int = 0, maximum: int = 10_000) -> int:
    raw = str(data or "").strip()
    if raw == prefix.rstrip(":"):
        return default
    return trailing_int(raw, prefix=prefix, name="página", minimum=0, maximum=maximum)
