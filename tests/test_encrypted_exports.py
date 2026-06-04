from __future__ import annotations

import base64
import json

import pytest

from app.security.encrypted_exports import (
    EncryptionNotConfigured,
    create_encrypted_signed_export,
    decrypt_encrypted_export,
    derive_export_key,
)
from app.security.signed_exports import create_signed_jsonl_export


def test_encrypted_export_roundtrip_with_passphrase():
    signed = create_signed_jsonl_export(source="test", base_filename="test.jsonl", data=b"{\"a\":1}\n")
    encrypted = create_encrypted_signed_export(signed_export=signed, secret="local-passphrase")
    assert encrypted.encrypted_filename == "test.jsonl.gz.enc"
    assert encrypted.manifest_filename == "test.jsonl.gz.enc.manifest.json"
    assert encrypted.ciphertext_bytes != signed.gzip_bytes
    recovered = decrypt_encrypted_export(
        ciphertext=encrypted.ciphertext_bytes,
        manifest_bytes=encrypted.manifest_bytes,
        secret="local-passphrase",
    )
    assert recovered == signed.gzip_bytes


def test_encrypted_manifest_contains_algorithm_and_hashes():
    signed = create_signed_jsonl_export(source="test", base_filename="test.jsonl", data=b"{}\n")
    encrypted = create_encrypted_signed_export(signed_export=signed, secret="pass")
    manifest = json.loads(encrypted.manifest_bytes.decode("utf-8"))
    assert manifest["schema"] == "tr3.encrypted_audit_export_manifest.v1"
    assert manifest["encryption"]["algorithm"] == "AES-256-GCM"
    assert manifest["plaintext_gzip_sha256"] == signed.gzip_sha256
    assert manifest["ciphertext_sha256"] == encrypted.ciphertext_sha256


def test_direct_base64_key_is_supported():
    signed = create_signed_jsonl_export(source="test", base_filename="test.jsonl", data=b"{}\n")
    key = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
    encrypted = create_encrypted_signed_export(signed_export=signed, secret=f"base64:{key}")
    recovered = decrypt_encrypted_export(ciphertext=encrypted.ciphertext_bytes, manifest_bytes=encrypted.manifest_bytes, secret=f"base64:{key}")
    assert recovered == signed.gzip_bytes


def test_missing_secret_is_rejected():
    signed = create_signed_jsonl_export(source="test", base_filename="test.jsonl", data=b"{}\n")
    with pytest.raises(EncryptionNotConfigured):
        create_encrypted_signed_export(signed_export=signed, secret="")


def test_derive_key_returns_32_bytes_for_passphrase():
    key, metadata = derive_export_key("passphrase")
    assert len(key) == 32
    assert metadata["kdf"] == "PBKDF2-HMAC-SHA256"
