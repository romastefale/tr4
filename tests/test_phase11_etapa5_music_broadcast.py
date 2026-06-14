from __future__ import annotations

import pytest

from app.bot.music_broadcast_core import (
    BroadcastTarget,
    build_music_broadcast_caption,
    normalize_music_key,
    targets_from_music_groups,
    track_identity,
    selection_from_arg,
)
from pathlib import Path


def test_music_broadcast_normalizes_blocks_without_username_operational_input():
    assert normalize_music_key("  Arctic-Monkeys!! ") == "arcticmonkeys"
    assert normalize_music_key("João   Gilberto") == "joão gilberto"


def test_music_broadcast_caption_uses_group_as_listener():
    caption = build_music_broadcast_caption(
        {"artist": "Daft Punk", "track_name": "Digital Love", "track_url": "https://example.invalid/track"},
        listener_name="Grupo Teste",
        actor_label="TR4",
    )
    assert "Grupo Teste" in caption
    assert "Digital Love" in caption
    assert "Daft Punk" in caption
    assert "Transmitido por TR4" in caption


def test_music_broadcast_targets_hide_raw_group_ids_from_labels():
    targets = targets_from_music_groups([
        {"chat_id": -100123, "title": "Sala A"},
        {"chat_id": "-100456", "username": "canal"},
        {"chat_id": "bad", "title": "ignorar"},
    ])
    assert [item.chat_id for item in targets] == [-100123, -100456]
    assert [item.title for item in targets] == ["Sala A", "canal"]


def test_music_broadcast_selection_supports_all_and_multiple_numbers():
    groups = [BroadcastTarget(chat_id=i, title=f"G{i}") for i in range(1, 6)]
    assert [t.chat_id for t in selection_from_arg("all", groups)] == [1, 2, 3, 4, 5]
    assert [t.chat_id for t in selection_from_arg("1,3 5", groups)] == [1, 3, 5]
    assert selection_from_arg("9", groups) == []


def test_broadcast_is_private_command_only_scope():
    source = Path("app/bot/setup_commands.py").read_text()
    private_tail = source.split("_PRIVATE_COMMANDS", 1)[1]
    public_head = source.split("_PRIVATE_COMMANDS", 1)[0]
    assert "CommandDef(\"tbrd\"" in private_tail
    assert "CommandDef(\"tbrd\"" not in public_head
    assert "CommandDef(\"broadcast\"" not in private_tail
    assert "CommandDef(\"broadcast\"" not in public_head


def test_track_identity_accepts_lastfm_style_track():
    info = track_identity({"artist": "A", "track_name": "B", "track_id": "lfm:abc", "cover": "https://img"})
    assert info["artist"] == "A"
    assert info["track_name"] == "B"
    assert info["track_id"] == "lfm:abc"
    assert info["cover"] == "https://img"
