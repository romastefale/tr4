from __future__ import annotations

from app.security.rate_limit import check_command_rate_limit, reset_rate_limits


def test_command_rate_limit_blocks_after_limit(monkeypatch):
    import app.security.rate_limit as rl

    reset_rate_limits()
    monkeypatch.setattr(rl, "COMMAND_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rl, "COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW", 2)
    monkeypatch.setattr(rl, "COMMAND_RATE_LIMIT_WINDOW_SECONDS", 60)

    assert check_command_rate_limit("monthfm", 1, -100).allowed is True
    assert check_command_rate_limit("monthfm", 1, -100).allowed is True
    blocked = check_command_rate_limit("monthfm", 1, -100)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 1
