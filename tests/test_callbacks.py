from __future__ import annotations

import pytest

from app.security.callbacks import CallbackParseError, page_number, parse_callback, trailing_int


def test_parse_callback_prefix_and_parts():
    parsed = parse_callback("radio:template:use:10", prefix="radio:template:")
    assert parsed.parts[-1] == "10"


def test_trailing_int_rejects_bad_payload():
    with pytest.raises(CallbackParseError):
        trailing_int("radio:template:use:not-int", prefix="radio:template:use:")


def test_page_number_bounds():
    assert page_number("radio:history:page:3", prefix="radio:history:page:") == 3
    with pytest.raises(CallbackParseError):
        page_number("radio:history:page:-1", prefix="radio:history:page:")
