from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tpv_usage_text_does_not_use_html_angle_placeholder():
    tnow = read("app/bot/tnow.py")
    assert 'Uso: /tpv ID_Telegram tnow|mosaico|all|off' in tnow
    assert 'Uso: /tpv <ID Telegram>' not in tnow
    assert '/tpv <telegram_id>' not in tnow


def test_expected_music_provider_failures_are_not_logged_as_critical_errors():
    spotify = read("app/services/spotify.py")
    lastfm = read("app/services/lastfm.py")

    assert 'logger.error("Spotify recent error' not in spotify
    assert 'reason=user_not_registered' in spotify
    assert 'logger.warning' in spotify

    assert 'logger.error("Last fm error' not in lastfm
    assert 'reason=user_not_found' in lastfm
    assert 'logger.warning' in lastfm


def test_release_validator_covers_runtime_error_fixes():
    validator = read("scripts/validate_tr4_release.py")
    assert 'Uso: /tpv <ID Telegram>' in validator
    assert 'reason=user_not_registered' in validator
    assert 'reason=user_not_found' in validator
    assert 'check_expected_provider_failures_are_not_crashes' in validator
