from __future__ import annotations

import logging

from app.logging_safety import SecretRedactionFilter, redact_secrets, configure_safe_logging


def test_redact_query_secrets() -> None:
    text = (
        "GET https://ws.audioscrobbler.com/2.0/?method=x"
        "&api_key=abc123secret&format=json&access_token=spotifytoken"
    )
    redacted = redact_secrets(text)
    assert "abc123secret" not in redacted
    assert "spotifytoken" not in redacted
    assert "api_key=[REDACTED]" in redacted
    assert "access_token=[REDACTED]" in redacted


def test_secret_redaction_filter_rewrites_record() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization=Bearer verysecrettokenvalue",
        args=(),
        exc_info=None,
    )
    assert SecretRedactionFilter().filter(record)
    assert "verysecrettokenvalue" not in record.getMessage()


def test_configure_safe_logging_suppresses_httpx_info() -> None:
    configure_safe_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_configure_safe_logging_redacts_exception_text(capsys) -> None:
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("tr4.audit.redaction.test")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.ERROR)
    logger.propagate = False

    configure_safe_logging()
    # configure_safe_logging wraps handlers already registered on root. This
    # handler is intentionally added after configuration, so attach the same
    # filter path used by runtime handlers and verify the record factory still
    # sanitizes exception text for future handlers.
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s%(exc_text)s"))

    try:
        raise RuntimeError("request failed api_key=lastfmsecretvalue access_token=spotifysecretvalue")
    except RuntimeError:
        logger.exception("operation failed Authorization=Bearer bearersecretvalue")

    output = stream.getvalue()
    assert "lastfmsecretvalue" not in output
    assert "spotifysecretvalue" not in output
    assert "bearersecretvalue" not in output
    assert "api_key=[REDACTED]" in output
    assert "access_token=[REDACTED]" in output
    assert "Authorization=[REDACTED]" in output


def test_redact_known_legacy_env_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("TR3_LASTFM_API_KEY", "legacy_lastfm_secret")
    monkeypatch.setenv("TR3_SPOTIFY_CLIENT_SECRET", "legacy_spotify_secret")
    text = redact_secrets("legacy_lastfm_secret legacy_spotify_secret")
    assert "legacy_lastfm_secret" not in text
    assert "legacy_spotify_secret" not in text
    assert text.count("[REDACTED_SECRET]") == 2


def test_secret_redaction_preserves_uvicorn_access_args_shape() -> None:
    import io
    from uvicorn.logging import AccessFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'))

    logger = logging.getLogger("tr4.audit.uvicorn.access.test")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    configure_safe_logging()
    if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
        handler.addFilter(SecretRedactionFilter())

    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "100.64.0.2:52221",
        "GET",
        "/healthz?api_key=lastfmsecretvalue",
        "1.1",
        200,
    )

    output = stream.getvalue()
    assert "ValueError" not in output
    assert "lastfmsecretvalue" not in output
    assert "api_key=[REDACTED]" in output
    assert "/healthz" in output
