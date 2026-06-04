from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.security.signed_exports import SignedExport, sha256_hex, utcnow_iso

_PBKDF2_ITERATIONS = 310_000
_SALT_BYTES = 16
_NONCE_BYTES = 12


class EncryptionNotConfigured(RuntimeError):
    pass


class ExportEncryptionError(RuntimeError):
    pass


class EncryptionKeyNotFound(ExportEncryptionError):
    pass


@dataclass(frozen=True)
class EncryptedSignedExport:
    source: str
    encrypted_filename: str
    manifest_filename: str
    ciphertext_bytes: bytes
    manifest_bytes: bytes
    ciphertext_sha256: str
    plaintext_gzip_sha256: str
    record_count: int


def _b64(data: bytes | None) -> str | None:
    if data is None:
        return None
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64decode(value: str) -> bytes:
    raw = value.strip().encode("ascii")
    # urlsafe_b64decode tolerates normal base64 alphabet too.
    padding = b"=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _aad_bytes(metadata: dict[str, Any]) -> bytes:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_key_id(key_id: str | None) -> str:
    value = str(key_id or "").strip()
    if not value:
        raise ExportEncryptionError("key_id vazio")
    if any(ch in value for ch in "\n\r\t =;,"):
        raise ExportEncryptionError("key_id contém caractere inválido")
    return value


def parse_decryption_keyring(raw: str | None) -> dict[str, str]:
    """Parseia chaves antigas para decrypt offline.

    Formato recomendado em variável de ambiente:

    ```text
    old-2026-01=passphrase antiga;old-2026-02=base64:<32 bytes>
    ```

    Separadores aceitos: ponto e vírgula ou quebra de linha. Valores vazios são
    ignorados. A chave atual deve ficar em `TR3_AUDIT_EXPORT_ENCRYPTION_KEY`.
    """
    items: dict[str, str] = {}
    text = str(raw or "").strip()
    if not text:
        return items
    for chunk in text.replace("\n", ";").split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        if "=" not in piece:
            raise ExportEncryptionError("item de keyring deve usar key_id=secret")
        key_id, secret = piece.split("=", 1)
        normalized = normalize_key_id(key_id)
        if not secret.strip():
            raise ExportEncryptionError(f"secret vazio para key_id {normalized}")
        if normalized in items:
            raise ExportEncryptionError(f"key_id duplicado no keyring: {normalized}")
        items[normalized] = secret.strip()
    return items


def build_decryption_keyring(
    *,
    current_key_id: str,
    current_secret: str | bytes | None,
    extra_keyring_raw: str | None = None,
) -> dict[str, str | bytes]:
    keyring: dict[str, str | bytes] = {}
    if current_secret is not None and str(current_secret).strip():
        keyring[normalize_key_id(current_key_id)] = current_secret
    for key_id, secret in parse_decryption_keyring(extra_keyring_raw).items():
        if key_id in keyring:
            raise ExportEncryptionError(f"key_id duplicado entre chave atual e antigas: {key_id}")
        keyring[key_id] = secret
    return keyring


def resolve_secret_for_key_id(key_id: str, keyring: dict[str, str | bytes]) -> str | bytes:
    normalized = normalize_key_id(key_id)
    try:
        return keyring[normalized]
    except KeyError as exc:
        raise EncryptionKeyNotFound(f"key_id não encontrado para decrypt: {normalized}") from exc


def keyring_public_summary(
    *,
    current_key_id: str,
    extra_keyring_raw: str | None = None,
) -> dict[str, Any]:
    current = normalize_key_id(current_key_id)
    legacy = sorted(parse_decryption_keyring(extra_keyring_raw).keys())
    return {
        "current_key_id": current,
        "legacy_key_ids": legacy,
        "legacy_count": len(legacy),
    }


def derive_export_key(secret: str | bytes | None, *, salt: bytes | None = None) -> tuple[bytes, dict[str, Any]]:
    """Deriva chave AES-256-GCM para export.

    Formatos aceitos:
    - `base64:<32 bytes em base64>` ou `b64:<...>`: chave direta AES-256.
    - qualquer outro texto: passphrase derivada com PBKDF2-HMAC-SHA256.
    """
    if secret is None:
        raise EncryptionNotConfigured("TR3_AUDIT_EXPORT_ENCRYPTION_KEY não configurada")
    if isinstance(secret, bytes):
        text = secret.decode("utf-8", errors="strict").strip()
    else:
        text = str(secret or "").strip()
    if not text:
        raise EncryptionNotConfigured("TR3_AUDIT_EXPORT_ENCRYPTION_KEY vazia")

    lowered = text.lower()
    if lowered.startswith("base64:") or lowered.startswith("b64:"):
        encoded = text.split(":", 1)[1].strip()
        key = _b64decode(encoded)
        if len(key) != 32:
            raise ExportEncryptionError("chave base64 deve decodificar para 32 bytes")
        return key, {"kdf": "none", "key_encoding": "base64", "salt_b64": None, "iterations": None}

    actual_salt = salt or os.urandom(_SALT_BYTES)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=actual_salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = kdf.derive(text.encode("utf-8"))
    return key, {
        "kdf": "PBKDF2-HMAC-SHA256",
        "key_encoding": "passphrase",
        "salt_b64": _b64(actual_salt),
        "iterations": _PBKDF2_ITERATIONS,
    }


def create_encrypted_signed_export(
    *,
    signed_export: SignedExport,
    secret: str | bytes | None,
    key_id: str = "current",
    extra: dict[str, Any] | None = None,
) -> EncryptedSignedExport:
    key_id = normalize_key_id(key_id)
    key, key_meta = derive_export_key(secret)
    nonce = os.urandom(_NONCE_BYTES)
    aad_metadata = {
        "schema": "tr3.encrypted_audit_export_aad.v1",
        "source": signed_export.source,
        "compressed_filename": signed_export.compressed_filename,
        "record_count": signed_export.record_count,
        "plaintext_gzip_sha256": signed_export.gzip_sha256,
    }
    aad = _aad_bytes(aad_metadata)
    ciphertext = AESGCM(key).encrypt(nonce, signed_export.gzip_bytes, aad)
    encrypted_filename = signed_export.compressed_filename + ".enc"
    manifest_filename = encrypted_filename + ".manifest.json"
    manifest = {
        "schema": "tr3.encrypted_audit_export_manifest.v1",
        "created_at": utcnow_iso(),
        "source": signed_export.source,
        "base_filename": signed_export.base_filename,
        "compressed_filename": signed_export.compressed_filename,
        "encrypted_filename": encrypted_filename,
        "manifest_filename": manifest_filename,
        "format": "jsonl.gz.enc",
        "compression": "gzip",
        "encryption": {
            "algorithm": "AES-256-GCM",
            "nonce_b64": _b64(nonce),
            "key_id": key_id,
            **key_meta,
            "aad": aad_metadata,
        },
        "record_count": signed_export.record_count,
        "raw_size_bytes": len(signed_export.raw_bytes),
        "gzip_size_bytes": len(signed_export.gzip_bytes),
        "ciphertext_size_bytes": len(ciphertext),
        "raw_sha256": signed_export.raw_sha256,
        "plaintext_gzip_sha256": signed_export.gzip_sha256,
        "ciphertext_sha256": sha256_hex(ciphertext),
        "extra": extra or {},
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    return EncryptedSignedExport(
        source=signed_export.source,
        encrypted_filename=encrypted_filename,
        manifest_filename=manifest_filename,
        ciphertext_bytes=ciphertext,
        manifest_bytes=manifest_bytes,
        ciphertext_sha256=manifest["ciphertext_sha256"],
        plaintext_gzip_sha256=signed_export.gzip_sha256,
        record_count=signed_export.record_count,
    )


def decrypt_encrypted_export(
    *,
    ciphertext: bytes,
    manifest_bytes: bytes,
    secret: str | bytes | None = None,
    keyring: dict[str, str | bytes] | None = None,
) -> bytes:
    """Retorna o payload `.jsonl.gz` descriptografado.

    Usado em testes e recuperação manual. Não faz replay de dados.

    Compatibilidade: passar `secret=` descriptografa diretamente, como na Fase
    10M. Para rotação, passe `keyring={key_id: secret}`; a função usa o
    `key_id` do manifesto.
    """
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    encryption = manifest.get("encryption") or {}
    if encryption.get("algorithm") != "AES-256-GCM":
        raise ExportEncryptionError("algoritmo não suportado")
    selected_secret: str | bytes | None = secret
    if selected_secret is None:
        if keyring is None:
            raise EncryptionNotConfigured("secret ou keyring obrigatório para decrypt")
        selected_secret = resolve_secret_for_key_id(str(encryption.get("key_id") or ""), keyring)
    salt_b64 = encryption.get("salt_b64")
    salt = _b64decode(salt_b64) if salt_b64 else None
    key, _ = derive_export_key(selected_secret, salt=salt)
    nonce = _b64decode(str(encryption.get("nonce_b64") or ""))
    aad = _aad_bytes(encryption.get("aad") or {})
    plaintext = AESGCM(key).decrypt(nonce, ciphertext or b"", aad)
    expected = manifest.get("plaintext_gzip_sha256")
    if expected and sha256_hex(plaintext) != expected:
        raise ExportEncryptionError("hash do plaintext gzip não confere")
    return plaintext
