from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SignedExport:
    source: str
    base_filename: str
    compressed_filename: str
    manifest_filename: str
    raw_bytes: bytes
    gzip_bytes: bytes
    manifest_bytes: bytes
    raw_sha256: str
    gzip_sha256: str
    record_count: int


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def count_jsonl_records(data: bytes) -> int:
    if not data:
        return 0
    return sum(1 for line in data.splitlines() if line.strip())


def gzip_jsonl(data: bytes) -> bytes:
    """Compacta JSONL em gzip com mtime fixo para manifesto reprodutível."""
    return gzip.compress(data or b"", compresslevel=9, mtime=0)


def build_manifest(
    *,
    source: str,
    base_filename: str,
    compressed_filename: str,
    raw_bytes: bytes,
    gzip_bytes: bytes,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "tr3.audit_export_manifest.v1",
        "created_at": utcnow_iso(),
        "source": source,
        "base_filename": base_filename,
        "compressed_filename": compressed_filename,
        "encoding": "utf-8",
        "format": "jsonl.gz",
        "compression": "gzip",
        "record_count": count_jsonl_records(raw_bytes),
        "raw_size_bytes": len(raw_bytes or b""),
        "gzip_size_bytes": len(gzip_bytes or b""),
        "raw_sha256": sha256_hex(raw_bytes),
        "gzip_sha256": sha256_hex(gzip_bytes),
        "extra": extra or {},
    }


def create_signed_jsonl_export(
    *,
    source: str,
    base_filename: str,
    data: bytes,
    extra: dict[str, Any] | None = None,
) -> SignedExport:
    raw = data or b""
    compressed_filename = f"{base_filename}.gz" if not base_filename.endswith(".gz") else base_filename
    manifest_filename = compressed_filename + ".manifest.json"
    gz = gzip_jsonl(raw)
    manifest = build_manifest(
        source=source,
        base_filename=base_filename,
        compressed_filename=compressed_filename,
        raw_bytes=raw,
        gzip_bytes=gz,
        extra=extra,
    )
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    return SignedExport(
        source=source,
        base_filename=base_filename,
        compressed_filename=compressed_filename,
        manifest_filename=manifest_filename,
        raw_bytes=raw,
        gzip_bytes=gz,
        manifest_bytes=manifest_bytes,
        raw_sha256=manifest["raw_sha256"],
        gzip_sha256=manifest["gzip_sha256"],
        record_count=int(manifest["record_count"]),
    )
