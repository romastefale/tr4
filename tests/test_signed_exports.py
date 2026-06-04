from __future__ import annotations

import gzip
import json

from app.security.signed_exports import (
    count_jsonl_records,
    create_signed_jsonl_export,
    gzip_jsonl,
    sha256_hex,
)


def test_create_signed_jsonl_export_generates_gzip_and_manifest():
    export = create_signed_jsonl_export(
        source="audit_events",
        base_filename="audit.jsonl",
        data=b'{"a":1}\n{"b":2}\n',
        extra={"limit": 2},
    )
    assert export.compressed_filename == "audit.jsonl.gz"
    assert export.manifest_filename == "audit.jsonl.gz.manifest.json"
    assert gzip.decompress(export.gzip_bytes) == export.raw_bytes
    assert export.record_count == 2

    manifest = json.loads(export.manifest_bytes.decode("utf-8"))
    assert manifest["schema"] == "tr3.audit_export_manifest.v1"
    assert manifest["source"] == "audit_events"
    assert manifest["raw_sha256"] == sha256_hex(export.raw_bytes)
    assert manifest["gzip_sha256"] == sha256_hex(export.gzip_bytes)
    assert manifest["extra"] == {"limit": 2}


def test_gzip_jsonl_is_deterministic_for_same_payload():
    data = b'{"x":1}\n'
    assert gzip_jsonl(data) == gzip_jsonl(data)


def test_count_jsonl_records_ignores_blank_lines():
    assert count_jsonl_records(b'{"a":1}\n\n {"b":2}\n') == 2
