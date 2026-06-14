from __future__ import annotations

from app.bot.setup_commands import command_scope_summary
from app.bot.telegram import bot_dispatcher
from app.bot.monthfm import router as monthfm_router
from app.bot.weekfm import router as weekfm_router
from app.bot.tnow import router as tnow_router
from app.bot.tcanvas import router as tcanvas_router
from app.bot.tstory import router as tstory_router
from app.bot.tly import router as tly_router
from app.bot.radiofm import router as radiofm_router
from app.bot.myself import router as myself_router
from app.bot.songcharts import router as songcharts_router
from app.bot.music_groups import ensure_tables, list_groups
from app.security.rate_limit import check_command_rate_limit, reset_rate_limits


def main() -> None:
    assert bot_dispatcher is not None
    for router in [monthfm_router, weekfm_router, tnow_router, tcanvas_router, tstory_router, tly_router, radiofm_router, myself_router, songcharts_router]:
        assert router is not None
    scopes = command_scope_summary()
    assert "playing" in scopes["public"]
    assert "tigrao" not in scopes["public"]
    assert "radio" not in scopes["public"]
    reset_rate_limits()
    assert check_command_rate_limit("playing", 1, 1).allowed
    ensure_tables()
    assert isinstance(list_groups(), list)
    print("music-only smoke ok")


if __name__ == "__main__":
    main()
