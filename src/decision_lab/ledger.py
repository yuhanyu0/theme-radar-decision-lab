from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def write_immutable_json(path: str | Path, payload: dict[str, Any]) -> str:
    """Create a JSON record exactly once.

    `os.O_EXCL` prevents silent overwrites. Historical recomputations must use a
    different path under `recomputed/` rather than mutating `ledger/live/`.
    Returns the SHA-256 hash of the canonical payload.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = canonical_hash(payload)

    record = dict(payload)
    record.setdefault("record_hash", digest)
    data = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
    except Exception:
        try:
            target.unlink(missing_ok=True)
        finally:
            raise
    return digest


def verify_record(path: str | Path) -> bool:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    stored = payload.pop("record_hash", None)
    if stored is None:
        return False
    return stored == canonical_hash(payload)
