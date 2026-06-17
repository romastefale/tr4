from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (ROOT / "scripts" / "validate_tr4_release.py").read_text(encoding="utf-8")


def test_stage8_release_validator_exists_and_checks_core_contracts():
    assert "TR4_RELEASE_VALIDATE_OK" in VALIDATOR
    assert "selected_activities = eligible[:MAX_TILES]" in VALIDATOR
    assert "eligible[:slots]" in VALIDATOR
    assert "resolve_music_display_name" in VALIDATOR
    assert "telegram_user_profiles" in VALIDATOR
    assert "provider-badge" in VALIDATOR
    assert "Last.fm" in VALIDATOR
    assert "Last fm" in VALIDATOR
    assert "Spotify" in VALIDATOR


def test_stage8_release_validator_has_no_aiogram_dependency():
    assert "aiogram" not in VALIDATOR
    assert "import app.bot" not in VALIDATOR
