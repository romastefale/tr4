from __future__ import annotations

import pytest

from app.security.encrypted_exports import (
    EncryptionKeyNotFound,
    build_decryption_keyring,
    create_encrypted_signed_export,
    decrypt_encrypted_export,
    keyring_public_summary,
    normalize_key_id,
    parse_decryption_keyring,
)
from app.security.signed_exports import create_signed_jsonl_export


def _signed():
    return create_signed_jsonl_export(source="audit_events", base_filename="audit.jsonl", data=b'{"x":1}\n')


def test_key_id_is_written_to_manifest_and_keyring_decrypts():
    signed = _signed()
    export = create_encrypted_signed_export(signed_export=signed, secret="new-secret", key_id="key-2026-06")
    keyring = build_decryption_keyring(
        current_key_id="key-2026-06",
        current_secret="new-secret",
        extra_keyring_raw="old-2026-05=old-secret",
    )
    assert decrypt_encrypted_export(
        ciphertext=export.ciphertext_bytes,
        manifest_bytes=export.manifest_bytes,
        keyring=keyring,
    ) == signed.gzip_bytes


def test_keyring_can_decrypt_legacy_manifest_key():
    signed = _signed()
    export = create_encrypted_signed_export(signed_export=signed, secret="old-secret", key_id="old-2026-05")
    keyring = build_decryption_keyring(
        current_key_id="key-2026-06",
        current_secret="new-secret",
        extra_keyring_raw="old-2026-05=old-secret",
    )
    assert decrypt_encrypted_export(
        ciphertext=export.ciphertext_bytes,
        manifest_bytes=export.manifest_bytes,
        keyring=keyring,
    ) == signed.gzip_bytes


def test_missing_key_id_raises_clear_error():
    export = create_encrypted_signed_export(signed_export=_signed(), secret="old-secret", key_id="old")
    with pytest.raises(EncryptionKeyNotFound):
        decrypt_encrypted_export(
            ciphertext=export.ciphertext_bytes,
            manifest_bytes=export.manifest_bytes,
            keyring={"new": "new-secret"},
        )


def test_keyring_parser_and_public_summary():
    assert parse_decryption_keyring("old=a;older=b") == {"old": "a", "older": "b"}
    summary = keyring_public_summary(current_key_id="current", extra_keyring_raw="old=a;older=b")
    assert summary == {"current_key_id": "current", "legacy_key_ids": ["old", "older"], "legacy_count": 2}


def test_invalid_key_id_rejected():
    with pytest.raises(Exception):
        normalize_key_id("bad id")
