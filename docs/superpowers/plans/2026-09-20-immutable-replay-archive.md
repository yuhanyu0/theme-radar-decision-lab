# Immutable Replay Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a content-addressed, immutable, typed, self-verifying archive layer for ReplayCycleResult without changing replay/scanner/budget semantics.

**Architecture:** Create one focused `replay_archive.py` module. Pure helpers build and validate archive records; strict decoder helpers reconstruct typed replay results; an explicit filesystem writer enforces destination policy, O_EXCL immutability, idempotence, and conflict detection. `run_replay_cycle()` remains untouched and filesystem-pure.

**Tech Stack:** Python 3.11, dataclasses, Enum, pathlib, os, json, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-20-immutable-replay-archive-design.md`

## Global Constraints

- Archive root for the current public repo is `recomputed/replay_cycles/`.
- Replay archives never write to `ledger/live`.
- `run_replay_cycle` remains unchanged and filesystem-pure.
- v0.1 stores `ReplayCycleResult` only; it does not archive raw `ReplayCycleInput` or raw `MarketBar` tuples.
- Archive identity is content-addressed by `ReplayCycleResult.result_hash`.
- v0.1 has no `archived_at`, manifest, index, database, cache, scheduler, search API, schema migration, cloud store, or automatic privacy classifier.
- PUBLIC writes require explicit `public_safe=True`.
- PRIVATE writes do not require `public_safe=True`.
- PUBLIC roots must resolve to a path ending in contiguous components `recomputed/replay_cycles`.
- Any resolved root containing contiguous `ledger/live` is rejected regardless of visibility.
- JSON serialization uses UTF-8, `ensure_ascii=False`, `sort_keys=True`, `indent=2`, `allow_nan=False`, and a trailing newline.
- Existing replay, market observation, scanner, budget, theme, universe, ledger, outcome, Tape, and playbook behavior must not change.
- Branch stays unmerged until exact-final-tree pytest, changed-files Ruff, and whole-branch review are green.

## Review Focus

1. **Schema drift:** nested decoder field sets must be hard-coded for archive schema v0.1; adding a dataclass field elsewhere must not silently broaden what old archives accept.
2. **Path-policy bypass:** PUBLIC-root and ledger/live checks must use `Path.resolve(strict=False)` and contiguous path parts, including symlink targets where supported.
3. **Identity mismatch:** top-level cycle/input/result hashes, nested replay hashes, filename, and cycle directory must all agree before a record is accepted.
4. **Immutable-write races/conflicts:** O_EXCL write, idempotent duplicate handling, invalid pre-existing file handling, and partial-new-file cleanup must never overwrite or delete pre-existing bytes.
5. **Strict JSON/type safety:** malformed JSON, extra/missing nested fields, invalid enums, arbitrary string-for-number coercion, NaN/Infinity, and non-object payloads must fail closed.

---

## File map

- Create `src/decision_lab/replay_archive.py`
  - archive public dataclasses/enums/constants;
  - replay/archive hash validation;
  - strict v0.1 decoder;
  - canonical path derivation;
  - destination policy;
  - immutable write/read/verify.
- Create `tests/test_replay_archive.py`
  - deterministic build/hash tests;
  - strict typed decoder tests;
  - tamper/path-tamper tests;
  - public/private/ledger destination policy tests;
  - O_EXCL/idempotence/conflict/partial-write tests;
  - Increment-5 end-to-end round-trip fixture.
- Modify `src/decision_lab/__init__.py`
  - export only the eight public archive symbols.
- Do not modify behavior in:
  - `src/decision_lab/replay.py`
  - `src/decision_lab/market_observation.py`
  - `src/decision_lab/scanner.py`
  - `src/decision_lab/research_budget.py`
  - `src/decision_lab/themes.py`
  - `src/decision_lab/universe.py`
  - `src/decision_lab/ledger.py`
  - `src/decision_lab/outcomes.py`
  - `src/decision_lab/tape.py`
  - `src/decision_lab/playbooks.py`

---

### Task 1: Archive record build, replay-result verification, deterministic path, and hash contracts

**Files:**
- Create: `src/decision_lab/replay_archive.py`
- Create: `tests/test_replay_archive.py`

**Interfaces:**
- Consumes: `ReplayCycleResult`, `ReplayThemeRecord`, `ReplayStatus`, `canonical_hash`.
- Produces:
  - `ArchiveDestinationVisibility`
  - `ReplayArchiveRecord`
  - `ReplayArchiveWriteResult`
  - `build_replay_archive_record(...)`
  - `replay_archive_path(...)`
- Private helpers established here:
  - `_parse_cycle_date(value: str) -> date`
  - `_validate_sha256_hex(value: str, *, field_name: str) -> None`
  - `_replay_result_payload_without_hash(result: ReplayCycleResult) -> dict[str, object]`
  - `_recompute_replay_result_hash(result: ReplayCycleResult) -> str`
  - `_archive_payload_without_hash(record: ReplayArchiveRecord) -> dict[str, object]`
  - `_validate_archive_record(record: ReplayArchiveRecord) -> None`

- [ ] **Step 1: Write RED tests for deterministic build, nested replay hash verification, UTC cycle path, malformed hashes, and non-finite payloads**

Create `tests/test_replay_archive.py` with:

```python
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.replay import ReplayCycleInput, run_replay_cycle
from decision_lab.replay_archive import (
    ArchiveDestinationVisibility,
    ReplayArchiveRecord,
    ReplayArchiveWriteResult,
    build_replay_archive_record,
    replay_archive_path,
)
from decision_lab.research_budget import ResearchBudgetConfig
from decision_lab.scanner import ScannerConfig, SupportDirection, ThemeScanObservation


def _radar(theme="Rates", *, discovery=0.8):
    return ThemeScanObservation(
        theme_id=theme,
        as_of="2026-09-19",
        source_type="radar_model_output",
        source_ref=f"radar:{theme}:2026-09-19",
        discovery_signal=discovery,
        novelty_signal=0.6,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=(f"radar:{theme}",),
        is_independent=False,
        observed_or_inferred="inferred",
    )


def _sample_replay_result(*, cycle_as_of="2026-09-19"):
    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=(),
            external_observations=(_radar(),),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )


def test_build_record_is_deterministic_and_content_addressed():
    result = _sample_replay_result()

    first = build_replay_archive_record(result)
    second = build_replay_archive_record(result)

    assert first == second
    assert first.schema_version == "0.1"
    assert first.content_type == "replay_cycle_result"
    assert first.producer == "theme-radar-decision-lab/replay-archive@0.1"
    assert first.cycle_as_of == result.cycle_as_of
    assert first.replay_input_hash == result.input_hash
    assert first.replay_result_hash == result.result_hash
    assert first.replay_result == result
    assert len(first.archive_record_hash) == 64

    payload = {
        "schema_version": first.schema_version,
        "content_type": first.content_type,
        "producer": first.producer,
        "cycle_as_of": first.cycle_as_of,
        "replay_input_hash": first.replay_input_hash,
        "replay_result_hash": first.replay_result_hash,
        "replay_result": asdict(first.replay_result),
    }
    assert first.archive_record_hash == canonical_hash(payload)


def test_build_rejects_tampered_nested_replay_result_hash():
    result = _sample_replay_result()
    tampered = replace(result, result_hash="0" * 64)

    with pytest.raises(ValueError, match="replay result hash mismatch"):
        build_replay_archive_record(tampered)


@pytest.mark.parametrize(
    "bad_hash",
    [
        "abc",
        "A" * 64,
        "g" * 64,
        "0" * 63,
    ],
)
def test_build_rejects_malformed_replay_hashes(bad_hash):
    result = _sample_replay_result()
    invalid = replace(result, input_hash=bad_hash)

    with pytest.raises(ValueError, match="replay input hash"):
        build_replay_archive_record(invalid)


def test_archive_path_uses_utc_cycle_date():
    result = _sample_replay_result(
        cycle_as_of="2026-09-19T23:30:00-04:00"
    )
    record = build_replay_archive_record(result)

    path = replay_archive_path(
        record,
        Path("/tmp/archive-root"),
    )

    assert path == (
        Path("/tmp/archive-root")
        / "2026-09-20"
        / f"{record.replay_result_hash}.json"
    )


def test_archive_path_does_not_create_directories(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "not-created"

    path = replay_archive_path(record, root)

    assert path.parent == root / "2026-09-19"
    assert not root.exists()


def test_build_rejects_non_finite_replay_payload():
    result = _sample_replay_result()
    bad_scan = replace(result.scan_results[0], research_priority=float("nan"))
    bad = replace(result, scan_results=(bad_scan,))

    with pytest.raises(ValueError):
        build_replay_archive_record(bad)
```

Production change that makes each test pass:
- existence of the archive module/public types;
- independent recomputation of nested replay result hash;
- strict lowercase SHA-256 validation;
- UTC cycle date path;
- canonical hash failure for NaN.

- [ ] **Step 2: Run Task-1 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_archive.py
```

Expected: collection failure because `decision_lab.replay_archive` does not exist.

- [ ] **Step 3: Implement public archive types/constants and pure build/path helpers**

Create `src/decision_lab/replay_archive.py` with this structure:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
import re

from .ledger import canonical_hash
from .replay import ReplayCycleResult

SCHEMA_VERSION = "0.1"
CONTENT_TYPE = "replay_cycle_result"
PRODUCER = "theme-radar-decision-lab/replay-archive@0.1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArchiveDestinationVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class ReplayArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    cycle_as_of: str
    replay_input_hash: str
    replay_result_hash: str
    replay_result: ReplayCycleResult
    archive_record_hash: str


@dataclass(frozen=True)
class ReplayArchiveWriteResult:
    path: Path
    created: bool
    replay_result_hash: str
    archive_record_hash: str


def _parse_cycle_date(value: str) -> date:
    if "T" not in value and " " not in value:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).date()


def _validate_sha256_hex(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase sha256 hex")


def _replay_result_payload_without_hash(
    result: ReplayCycleResult,
) -> dict[str, object]:
    return {
        "cycle_as_of": result.cycle_as_of,
        "input_hash": result.input_hash,
        "market_batches": [asdict(item) for item in result.market_batches],
        "combined_observations": [
            asdict(item) for item in result.combined_observations
        ],
        "scan_results": [asdict(item) for item in result.scan_results],
        "allocations": [asdict(item) for item in result.allocations],
        "theme_records": [asdict(item) for item in result.theme_records],
    }


def _recompute_replay_result_hash(result: ReplayCycleResult) -> str:
    return canonical_hash(_replay_result_payload_without_hash(result))


def _archive_payload_without_hash(
    record: ReplayArchiveRecord,
) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "content_type": record.content_type,
        "producer": record.producer,
        "cycle_as_of": record.cycle_as_of,
        "replay_input_hash": record.replay_input_hash,
        "replay_result_hash": record.replay_result_hash,
        "replay_result": asdict(record.replay_result),
    }


def _validate_archive_record(record: ReplayArchiveRecord) -> None:
    if record.schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported replay archive schema_version")
    if record.content_type != CONTENT_TYPE:
        raise ValueError("unsupported replay archive content_type")
    if record.producer != PRODUCER:
        raise ValueError("unsupported replay archive producer")

    _validate_sha256_hex(
        record.replay_input_hash,
        field_name="replay input hash",
    )
    _validate_sha256_hex(
        record.replay_result_hash,
        field_name="replay result hash",
    )
    _validate_sha256_hex(
        record.replay_result.input_hash,
        field_name="nested replay input hash",
    )
    _validate_sha256_hex(
        record.replay_result.result_hash,
        field_name="nested replay result hash",
    )
    _validate_sha256_hex(
        record.archive_record_hash,
        field_name="archive record hash",
    )

    if record.cycle_as_of != record.replay_result.cycle_as_of:
        raise ValueError("archive cycle_as_of mismatch")
    if record.replay_input_hash != record.replay_result.input_hash:
        raise ValueError("archive replay input hash mismatch")
    if record.replay_result_hash != record.replay_result.result_hash:
        raise ValueError("archive replay result hash mismatch")

    recomputed_result = _recompute_replay_result_hash(
        record.replay_result
    )
    if recomputed_result != record.replay_result.result_hash:
        raise ValueError("replay result hash mismatch")

    recomputed_archive = canonical_hash(
        _archive_payload_without_hash(record)
    )
    if recomputed_archive != record.archive_record_hash:
        raise ValueError("archive record hash mismatch")


def build_replay_archive_record(
    replay_result: ReplayCycleResult,
) -> ReplayArchiveRecord:
    _validate_sha256_hex(
        replay_result.input_hash,
        field_name="replay input hash",
    )
    _validate_sha256_hex(
        replay_result.result_hash,
        field_name="replay result hash",
    )
    if _recompute_replay_result_hash(replay_result) != replay_result.result_hash:
        raise ValueError("replay result hash mismatch")

    seed = ReplayArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=CONTENT_TYPE,
        producer=PRODUCER,
        cycle_as_of=replay_result.cycle_as_of,
        replay_input_hash=replay_result.input_hash,
        replay_result_hash=replay_result.result_hash,
        replay_result=replay_result,
        archive_record_hash="0" * 64,
    )
    archive_hash = canonical_hash(_archive_payload_without_hash(seed))
    record = ReplayArchiveRecord(
        schema_version=seed.schema_version,
        content_type=seed.content_type,
        producer=seed.producer,
        cycle_as_of=seed.cycle_as_of,
        replay_input_hash=seed.replay_input_hash,
        replay_result_hash=seed.replay_result_hash,
        replay_result=seed.replay_result,
        archive_record_hash=archive_hash,
    )
    _validate_archive_record(record)
    return record


def replay_archive_path(
    record: ReplayArchiveRecord,
    archive_root: str | Path,
) -> Path:
    _validate_sha256_hex(
        record.replay_result_hash,
        field_name="replay result hash",
    )
    cycle_date = _parse_cycle_date(record.cycle_as_of).isoformat()
    return (
        Path(archive_root)
        / cycle_date
        / f"{record.replay_result_hash}.json"
    )
```

Do not import `os` or `json` yet; Task 1 remains pure.

- [ ] **Step 4: Run Task-1 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_archive.py
pytest -q
```

Expected: all Task-1 and existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/decision_lab/replay_archive.py tests/test_replay_archive.py
git commit -m "feat: add replay archive record boundary"
```

---

### Task 2: Strict v0.1 typed decoder, read, canonical-path verification, and tamper detection

**Files:**
- Modify: `src/decision_lab/replay_archive.py`
- Modify: `tests/test_replay_archive.py`

**Interfaces:**
- Consumes all public dataclasses/enums embedded in `ReplayCycleResult`.
- Produces:
  - `read_replay_archive(path) -> ReplayArchiveRecord`
  - `verify_replay_archive(path) -> bool`
- Private helpers added:
  - `_require_exact_fields(...)`
  - `_decode_theme_scan_observation(...)`
  - `_decode_market_diagnostic(...)`
  - `_decode_market_batch(...)`
  - `_decode_scan_result(...)`
  - `_decode_allocation(...)`
  - `_decode_theme_record(...)`
  - `_decode_replay_result(...)`
  - `_record_payload(record) -> dict[str, object]`

- [ ] **Step 1: Add RED reader/decoder/tamper/path tests**

Append imports:

```python
import json

from decision_lab.market_observation import (
    MarketObservationMode,
    MarketObservationStatus,
)
from decision_lab.replay import ReplayStatus
from decision_lab.replay_archive import (
    read_replay_archive,
    verify_replay_archive,
)
from decision_lab.research_budget import ResearchTier
from decision_lab.scanner import SupportDirection
```

Add a test-only deterministic serializer helper:

```python
def _record_payload(record):
    return {
        "schema_version": record.schema_version,
        "content_type": record.content_type,
        "producer": record.producer,
        "cycle_as_of": record.cycle_as_of,
        "replay_input_hash": record.replay_input_hash,
        "replay_result_hash": record.replay_result_hash,
        "replay_result": asdict(record.replay_result),
        "archive_record_hash": record.archive_record_hash,
    }


def _write_payload(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _standard_path(tmp_path, record):
    return (
        tmp_path
        / "2026-09-19"
        / f"{record.replay_result_hash}.json"
    )
```

Add tests:

```python
def test_reader_round_trips_typed_replay_result(tmp_path):
    result = _sample_replay_result()
    record = build_replay_archive_record(result)
    path = _standard_path(tmp_path, record)
    _write_payload(path, _record_payload(record))

    loaded = read_replay_archive(path)

    assert loaded == record
    assert loaded.replay_result == result
    assert loaded.replay_result.theme_records[0].replay_status is ReplayStatus.ROUTED
    assert loaded.replay_result.allocations[0].tier is ResearchTier.SCAN_ONLY
    assert verify_replay_archive(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "allocation_tier",
        "scan_priority",
        "embedded_result_hash",
        "top_result_hash",
        "top_input_hash",
        "archive_hash",
    ],
)
def test_tampering_invalidates_archive(tmp_path, mutation):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)

    if mutation == "allocation_tier":
        payload["replay_result"]["allocations"][0]["tier"] = (
            "FULL_DECISION_RESEARCH"
        )
    elif mutation == "scan_priority":
        payload["replay_result"]["scan_results"][0]["research_priority"] = 0.99
    elif mutation == "embedded_result_hash":
        payload["replay_result"]["result_hash"] = "1" * 64
    elif mutation == "top_result_hash":
        payload["replay_result_hash"] = "1" * 64
    elif mutation == "top_input_hash":
        payload["replay_input_hash"] = "1" * 64
    elif mutation == "archive_hash":
        payload["archive_record_hash"] = "1" * 64

    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_extra_top_level_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["unexpected"] = "value"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="unexpected archive fields"):
        read_replay_archive(path)


def test_reader_rejects_extra_nested_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["allocations"][0]["unexpected"] = 1
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="unexpected ResearchAllocation fields"):
        read_replay_archive(path)


def test_reader_rejects_missing_nested_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0].pop("theme_id")
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="missing ThemeScanResult fields"):
        read_replay_archive(path)


def test_reader_rejects_invalid_nested_enum(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["theme_records"][0]["replay_status"] = "magic"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_string_for_numeric_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0]["research_priority"] = "0.5"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(TypeError, match="research_priority"):
        read_replay_archive(path)


def test_reader_rejects_non_string_identity_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0]["theme_id"] = 123
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(TypeError, match="theme_id"):
        read_replay_archive(path)


def test_reader_rejects_non_finite_json_constant(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    path = _standard_path(tmp_path, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_record_payload(record), allow_nan=False)
    text = text.replace(
        '"research_priority": 0.0',
        '"research_priority": NaN',
        1,
    )
    path.write_text(text, encoding="utf-8")

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        read_replay_archive(path)


def test_reader_rejects_missing_top_level_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload.pop("producer")
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="missing archive fields"):
        read_replay_archive(path)


def test_reader_rejects_wrong_filename(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    path = tmp_path / "2026-09-19" / f"{'1' * 64}.json"
    _write_payload(path, _record_payload(record))

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="archive filename mismatch"):
        read_replay_archive(path)


def test_reader_rejects_wrong_cycle_directory(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    path = tmp_path / "2026-09-18" / f"{record.replay_result_hash}.json"
    _write_payload(path, _record_payload(record))

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="archive cycle directory mismatch"):
        read_replay_archive(path)


def test_verify_returns_false_for_missing_and_malformed_json(tmp_path):
    missing = tmp_path / "missing.json"
    assert not verify_replay_archive(missing)

    malformed = tmp_path / "bad" / "payload.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("{not-json", encoding="utf-8")
    assert not verify_replay_archive(malformed)
```

Production change that makes these tests pass:
- exact v0.1 nested decoder;
- independent nested result-hash recomputation;
- canonical filename/date-dir enforcement;
- verify wrapper.

- [ ] **Step 2: Run Task-2 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_archive.py
```

Expected: failures for missing reader/verifier and decoder behavior.

- [ ] **Step 3: Add strict decoder imports and hard-coded field sets**

Extend `replay_archive.py` imports:

```python
import json
from collections.abc import Mapping
from math import isfinite

from .market_observation import (
    MarketObservationBatch,
    MarketObservationDiagnostics,
    MarketObservationMode,
    MarketObservationStatus,
)
from .replay import (
    ReplayCycleResult,
    ReplayStatus,
    ReplayThemeRecord,
)
from .research_budget import ResearchAllocation, ResearchTier
from .scanner import (
    SupportDirection,
    ThemeScanObservation,
    ThemeScanResult,
)
```

Hard-code schema-v0.1 field sets:

```python
_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "cycle_as_of",
    "replay_input_hash",
    "replay_result_hash",
    "replay_result",
    "archive_record_hash",
}

_REPLAY_RESULT_FIELDS = {
    "cycle_as_of",
    "market_batches",
    "combined_observations",
    "scan_results",
    "allocations",
    "theme_records",
    "input_hash",
    "result_hash",
}

_REPLAY_THEME_RECORD_FIELDS = {
    "theme_id",
    "registered",
    "market_batch",
    "scan_result",
    "allocation",
    "replay_status",
}

_MARKET_BATCH_FIELDS = {
    "theme_id",
    "cycle_as_of",
    "market_as_of",
    "observations",
    "diagnostics",
    "input_hash",
    "spec_hash",
    "config_hash",
}

_MARKET_DIAGNOSTIC_FIELDS = {
    "theme_id",
    "mode",
    "instrument",
    "benchmark",
    "market_as_of",
    "current_start",
    "current_end",
    "prior_start",
    "prior_end",
    "status",
    "reason",
    "current_return",
    "benchmark_current_return",
    "current_excess_return",
    "comparison_current_excess_return",
    "comparison_prior_excess_return",
    "novelty_abs_excess_change",
    "breadth",
    "persistence",
    "current_member_symbols",
    "stable_member_symbols",
    "current_member_count",
    "stable_member_count",
    "membership_changed",
    "support_direction",
    "relative_strength_signal",
    "breadth_signal",
    "persistence_signal",
    "novelty_signal",
    "universe_version",
    "package_version",
    "spec_version",
    "config_version",
    "input_hash",
    "spec_hash",
    "config_hash",
    "diagnostic_hash",
    "evidence_refs",
    "warnings",
}

_THEME_SCAN_OBSERVATION_FIELDS = {
    "theme_id",
    "as_of",
    "source_type",
    "source_ref",
    "discovery_signal",
    "structure_signal",
    "persistence_signal",
    "breadth_signal",
    "relative_strength_signal",
    "volatility_signal",
    "novelty_signal",
    "support_direction",
    "evidence_refs",
    "is_independent",
    "observed_or_inferred",
    "notes",
}

_THEME_SCAN_RESULT_FIELDS = {
    "theme_id",
    "as_of",
    "discovery_score",
    "structural_score",
    "persistence_score",
    "breadth_score",
    "relative_strength_score",
    "novelty_score",
    "evidence_confidence",
    "independent_support_count",
    "independent_contradiction_count",
    "lifecycle_recommendation",
    "research_priority",
    "forced_review",
    "forced_review_severity",
    "forced_review_reasons",
    "reasons",
    "evidence_refs",
    "config_hash",
    "registry_version",
    "prior_result_refs",
}

_RESEARCH_ALLOCATION_FIELDS = {
    "theme_id",
    "as_of",
    "tier",
    "scan_priority",
    "effective_priority",
    "scan_novelty_score",
    "forced_review",
    "allocation_reasons",
    "source_scan_result_hash",
}
```

- [ ] **Step 4: Implement exact-field and primitive validators**

Add:

```python
def _require_mapping(value, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return dict(value)


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ValueError(
            f"missing {label} fields: {sorted(missing)}"
        )
    if extra:
        raise ValueError(
            f"unexpected {label} fields: {sorted(extra)}"
        )


def _require_list(value, *, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a JSON array")
    return value


def _require_str(value, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_optional_str(value, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name=field_name)


def _require_literal(
    value,
    *,
    field_name: str,
    allowed: set[str],
) -> str:
    text = _require_str(value, field_name=field_name)
    if text not in allowed:
        raise ValueError(f"invalid {field_name}")
    return text


def _require_number_or_none(value, *, field_name: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or null")
    if not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return value


def _require_number(value, *, field_name: str) -> float | int:
    number = _require_number_or_none(value, field_name=field_name)
    if number is None:
        raise TypeError(f"{field_name} must be numeric")
    return number


def _require_int(value, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_bool(value, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _tuple_of_strings(value, *, field_name: str) -> tuple[str, ...]:
    items = _require_list(value, field_name=field_name)
    if not all(isinstance(item, str) for item in items):
        raise TypeError(f"{field_name} must contain strings")
    return tuple(items)
```

Also validate `source_type` against this fixed v0.1 set:

```python
_SOURCE_TYPES = {
    "market_data",
    "sec_filing",
    "company_ir",
    "official_macro",
    "industry_primary",
    "reputable_reporting",
    "radar_model_output",
    "derived_feature",
}
```

- [ ] **Step 5: Implement typed nested decoders**

Implement each decoder with exact-field check before construction.

Representative observation decoder:

```python
def _decode_theme_scan_observation(value) -> ThemeScanObservation:
    payload = _require_mapping(
        value,
        label="ThemeScanObservation",
    )
    _require_exact_fields(
        payload,
        _THEME_SCAN_OBSERVATION_FIELDS,
        label="ThemeScanObservation",
    )

    source_type = payload["source_type"]
    if source_type not in _SOURCE_TYPES:
        raise ValueError("invalid ThemeScanObservation source_type")

    return ThemeScanObservation(
        theme_id=_require_str(
            payload["theme_id"],
            field_name="theme_id",
        ),
        as_of=_require_str(
            payload["as_of"],
            field_name="as_of",
        ),
        source_type=source_type,
        source_ref=_require_str(
            payload["source_ref"],
            field_name="source_ref",
        ),
        discovery_signal=_require_number_or_none(
            payload["discovery_signal"],
            field_name="discovery_signal",
        ),
        structure_signal=_require_number_or_none(
            payload["structure_signal"],
            field_name="structure_signal",
        ),
        persistence_signal=_require_number_or_none(
            payload["persistence_signal"],
            field_name="persistence_signal",
        ),
        breadth_signal=_require_number_or_none(
            payload["breadth_signal"],
            field_name="breadth_signal",
        ),
        relative_strength_signal=_require_number_or_none(
            payload["relative_strength_signal"],
            field_name="relative_strength_signal",
        ),
        volatility_signal=_require_number_or_none(
            payload["volatility_signal"],
            field_name="volatility_signal",
        ),
        novelty_signal=_require_number_or_none(
            payload["novelty_signal"],
            field_name="novelty_signal",
        ),
        support_direction=SupportDirection(
            payload["support_direction"]
        ),
        evidence_refs=_tuple_of_strings(
            payload["evidence_refs"],
            field_name="evidence_refs",
        ),
        is_independent=_require_bool(
            payload["is_independent"],
            field_name="is_independent",
        ),
        observed_or_inferred=_require_literal(
            payload["observed_or_inferred"],
            field_name="observed_or_inferred",
            allowed={"observed", "inferred"},
        ),
        notes=_require_optional_str(
            payload["notes"],
            field_name="notes",
        ),
    )
```

Implement `_decode_market_diagnostic` with an explicit constructor after `_require_exact_fields`. Every string identity/date/version/hash field uses `_require_str` or `_require_optional_str`; do not call `str(...)`. Convert exactly:
- `mode=MarketObservationMode(_require_str(payload["mode"], field_name="mode"))`
- `status=MarketObservationStatus(_require_str(payload["status"], field_name="status"))`
- `support_direction=SupportDirection(_require_str(payload["support_direction"], field_name="support_direction"))`
- `current_member_symbols`, `stable_member_symbols`, `evidence_refs`, and `warnings` with `_tuple_of_strings`;
- `current_member_count` and `stable_member_count` with `_require_int`;
- `membership_changed` with `_require_bool`;
- every optional return/signal/breadth/persistence field with `_require_number_or_none`;
- `diagnostic_hash` with `_require_optional_str`.

Implement `_decode_scan_result` with exact fields and:
- all identity/date/lifecycle/config/registry fields through strict string helpers;
- all tuple fields through `_tuple_of_strings`;
- counts/severity through `_require_int`;
- booleans through `_require_bool`;
- numeric scores through `_require_number_or_none` where nullable and a new `_require_number` helper where non-null.

Implement `_decode_allocation` with:
- `tier=ResearchTier(_require_str(payload["tier"], field_name="tier"))`;
- strict string helpers for identifiers/hashes/date;
- numeric helpers for priorities;
- `_require_bool` for forced_review;
- `_tuple_of_strings` for reasons.

Implement `_decode_theme_record` with:
- strict `theme_id` and `registered`;
- optional nested objects decoded only when the value is not None;
- `ReplayStatus(_require_str(payload["replay_status"], field_name="replay_status"))`.

No decoder may repair or coerce a wrong primitive type.

Implement `_decode_market_batch`:

```python
def _decode_market_batch(value) -> MarketObservationBatch:
    payload = _require_mapping(value, label="MarketObservationBatch")
    _require_exact_fields(
        payload,
        _MARKET_BATCH_FIELDS,
        label="MarketObservationBatch",
    )
    return MarketObservationBatch(
        theme_id=_require_str(
            payload["theme_id"],
            field_name="theme_id",
        ),
        cycle_as_of=_require_str(
            payload["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        market_as_of=_require_optional_str(
            payload["market_as_of"],
            field_name="market_as_of",
        ),
        observations=tuple(
            _decode_theme_scan_observation(item)
            for item in _require_list(
                payload["observations"],
                field_name="observations",
            )
        ),
        diagnostics=tuple(
            _decode_market_diagnostic(item)
            for item in _require_list(
                payload["diagnostics"],
                field_name="diagnostics",
            )
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        spec_hash=_require_str(
            payload["spec_hash"],
            field_name="spec_hash",
        ),
        config_hash=_require_str(
            payload["config_hash"],
            field_name="config_hash",
        ),
    )
```

Implement `_decode_scan_result`, `_decode_allocation`, and `_decode_theme_record` with the same exact-field policy. For optional nested values in `ReplayThemeRecord`, preserve `None` or call the correct decoder.

Implement `_decode_replay_result`:

```python
def _decode_replay_result(value) -> ReplayCycleResult:
    payload = _require_mapping(value, label="ReplayCycleResult")
    _require_exact_fields(
        payload,
        _REPLAY_RESULT_FIELDS,
        label="ReplayCycleResult",
    )
    return ReplayCycleResult(
        cycle_as_of=_require_str(
            payload["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        market_batches=tuple(
            _decode_market_batch(item)
            for item in _require_list(
                payload["market_batches"],
                field_name="market_batches",
            )
        ),
        combined_observations=tuple(
            _decode_theme_scan_observation(item)
            for item in _require_list(
                payload["combined_observations"],
                field_name="combined_observations",
            )
        ),
        scan_results=tuple(
            _decode_scan_result(item)
            for item in _require_list(
                payload["scan_results"],
                field_name="scan_results",
            )
        ),
        allocations=tuple(
            _decode_allocation(item)
            for item in _require_list(
                payload["allocations"],
                field_name="allocations",
            )
        ),
        theme_records=tuple(
            _decode_theme_record(item)
            for item in _require_list(
                payload["theme_records"],
                field_name="theme_records",
            )
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        result_hash=_require_str(
            payload["result_hash"],
            field_name="result_hash",
        ),
    )
```

Do not coerce numeric strings.

- [ ] **Step 6: Implement reader and verifier**

Add:

```python
def _decode_archive_record(payload) -> ReplayArchiveRecord:
    data = _require_mapping(payload, label="archive")
    _require_exact_fields(
        data,
        _ARCHIVE_FIELDS,
        label="archive",
    )
    record = ReplayArchiveRecord(
        schema_version=_require_str(
            data["schema_version"],
            field_name="schema_version",
        ),
        content_type=_require_str(
            data["content_type"],
            field_name="content_type",
        ),
        producer=_require_str(
            data["producer"],
            field_name="producer",
        ),
        cycle_as_of=_require_str(
            data["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        replay_input_hash=_require_str(
            data["replay_input_hash"],
            field_name="replay_input_hash",
        ),
        replay_result_hash=_require_str(
            data["replay_result_hash"],
            field_name="replay_result_hash",
        ),
        replay_result=_decode_replay_result(data["replay_result"]),
        archive_record_hash=_require_str(
            data["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_archive_record(record)
    return record


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant: {value}")


def read_replay_archive(path: str | Path) -> ReplayArchiveRecord:
    target = Path(path)
    payload = json.loads(
        target.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )
    record = _decode_archive_record(payload)

    expected_name = f"{record.replay_result_hash}.json"
    if target.name != expected_name:
        raise ValueError("archive filename mismatch")

    expected_cycle = _parse_cycle_date(record.cycle_as_of).isoformat()
    if target.parent.name != expected_cycle:
        raise ValueError("archive cycle directory mismatch")

    return record


def verify_replay_archive(path: str | Path) -> bool:
    try:
        read_replay_archive(path)
    except FileNotFoundError:
        return False
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return True
```

Do not catch `PermissionError`.

- [ ] **Step 7: Run Task-2 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/decision_lab/replay_archive.py tests/test_replay_archive.py
git commit -m "feat: decode and verify replay archives"
```

---

### Task 3: Destination policy and immutable O_EXCL writer

**Files:**
- Modify: `src/decision_lab/replay_archive.py`
- Modify: `tests/test_replay_archive.py`

**Interfaces:**
- Produces:
  - `write_replay_archive(...)`
- Private helpers:
  - `_contains_path_sequence(...)`
  - `_resolved_archive_root(...)`
  - `_validate_destination_policy(...)`
  - `_serialize_archive_record(...)`

- [ ] **Step 1: Add RED destination/idempotence/conflict tests**

Append imports:

```python
import os

from decision_lab.replay_archive import write_replay_archive
```

Add tests:

```python
def test_public_write_requires_explicit_public_safe_before_directory_creation(
    tmp_path,
):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "recomputed" / "replay_cycles"

    with pytest.raises(
        PermissionError,
        match="public archive write requires explicit public_safe=True",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=False,
        )

    assert not root.exists()


def test_public_write_requires_canonical_root_suffix(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "reports" / "replay_cycles"

    with pytest.raises(
        ValueError,
        match="public replay archives must use recomputed/replay_cycles",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )

    assert not root.exists()


@pytest.mark.parametrize(
    "visibility",
    [
        ArchiveDestinationVisibility.PUBLIC,
        ArchiveDestinationVisibility.PRIVATE,
    ],
)
def test_ledger_live_destination_is_always_rejected(tmp_path, visibility):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "ledger" / "live" / "replay_cycles"

    with pytest.raises(
        ValueError,
        match="replay archives may not be written under ledger/live",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=visibility,
            public_safe=True,
        )

    assert not root.exists()


def test_private_destination_allows_public_safe_false(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private-replays"

    result = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        public_safe=False,
    )

    assert result.created
    assert result.path.exists()


def test_same_record_write_is_idempotent(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "recomputed" / "replay_cycles"

    first = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )
    second = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )

    assert first.created
    assert not second.created
    assert first.path == second.path
    assert first.archive_record_hash == second.archive_record_hash
    assert first.replay_result_hash == second.replay_result_hash
    assert list(first.path.parent.glob("*.json")) == [first.path]


def test_existing_conflicting_file_is_never_overwritten(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private"
    path = replay_archive_path(record, root)
    path.parent.mkdir(parents=True)
    original = b"{\"different\":true}\n"
    path.write_bytes(original)

    with pytest.raises(FileExistsError, match="archive path conflict"):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )

    assert path.read_bytes() == original
```

Add symlink tests:

```python
def test_symlink_resolving_under_ledger_live_is_rejected(tmp_path):
    target = tmp_path / "ledger" / "live" / "real"
    target.mkdir(parents=True)
    link = tmp_path / "archive-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    record = build_replay_archive_record(_sample_replay_result())
    with pytest.raises(
        ValueError,
        match="replay archives may not be written under ledger/live",
    ):
        write_replay_archive(
            record,
            link,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )


def test_public_symlink_to_noncanonical_destination_is_rejected(tmp_path):
    target = tmp_path / "reports" / "replay_cycles"
    target.mkdir(parents=True)
    link_parent = tmp_path / "recomputed"
    link_parent.mkdir()
    link = link_parent / "replay_cycles"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    record = build_replay_archive_record(_sample_replay_result())
    with pytest.raises(
        ValueError,
        match="public replay archives must use recomputed/replay_cycles",
    ):
        write_replay_archive(
            record,
            link,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )
```

- [ ] **Step 2: Run Task-3 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_archive.py
```

Expected: writer/destination tests fail because `write_replay_archive` does not exist.

- [ ] **Step 3: Implement resolved path-policy helpers**

Extend imports:

```python
import os
```

Add:

```python
def _contains_path_sequence(
    parts: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    width = len(sequence)
    return any(
        tuple(parts[index : index + width]) == sequence
        for index in range(len(parts) - width + 1)
    )


def _resolved_archive_root(archive_root: str | Path) -> Path:
    return Path(archive_root).expanduser().resolve(strict=False)


def _validate_destination_policy(
    archive_root: str | Path,
    *,
    destination_visibility: ArchiveDestinationVisibility,
    public_safe: bool,
) -> Path:
    if not isinstance(
        destination_visibility,
        ArchiveDestinationVisibility,
    ):
        raise TypeError("invalid archive destination visibility")

    resolved = _resolved_archive_root(archive_root)
    parts = tuple(resolved.parts)

    if _contains_path_sequence(parts, ("ledger", "live")):
        raise ValueError(
            "replay archives may not be written under ledger/live"
        )

    if destination_visibility is ArchiveDestinationVisibility.PUBLIC:
        if not public_safe:
            raise PermissionError(
                "public archive write requires explicit public_safe=True"
            )
        if len(parts) < 2 or parts[-2:] != (
            "recomputed",
            "replay_cycles",
        ):
            raise ValueError(
                "public replay archives must use recomputed/replay_cycles"
            )

    return resolved
```

Policy validation runs before `mkdir`.

- [ ] **Step 4: Implement deterministic serialization and immutable writer**

Add:

```python
def _record_payload(record: ReplayArchiveRecord) -> dict[str, object]:
    return {
        **_archive_payload_without_hash(record),
        "archive_record_hash": record.archive_record_hash,
    }


def _serialize_archive_record(record: ReplayArchiveRecord) -> bytes:
    return (
        json.dumps(
            _record_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
```

Implement writer:

```python
def write_replay_archive(
    record: ReplayArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ReplayArchiveWriteResult:
    resolved_root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_archive_record(record)

    path = replay_archive_path(record, resolved_root)
    requested_payload = _record_payload(record)
    requested_bytes = _serialize_archive_record(record)

    path.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        try:
            existing = read_replay_archive(path)
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            FileNotFoundError,
        ) as exc:
            raise FileExistsError("archive path conflict") from exc

        if _record_payload(existing) != requested_payload:
            raise FileExistsError("archive path conflict")

        return ReplayArchiveWriteResult(
            path=path,
            created=False,
            replay_result_hash=record.replay_result_hash,
            archive_record_hash=record.archive_record_hash,
        )

    created_here = True
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(requested_bytes)
    except Exception:
        if created_here:
            path.unlink(missing_ok=True)
        raise

    return ReplayArchiveWriteResult(
        path=path,
        created=True,
        replay_result_hash=record.replay_result_hash,
        archive_record_hash=record.archive_record_hash,
    )
```

Do not add overwrite or repair options.

- [ ] **Step 5: Run Task-3 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/decision_lab/replay_archive.py tests/test_replay_archive.py
git commit -m "feat: write immutable replay archives"
```

---

### Task 4: Partial-write cleanup, full nested tamper matrix, real replay round-trip, and public exports

**Files:**
- Modify: `src/decision_lab/replay_archive.py`
- Modify: `tests/test_replay_archive.py`
- Modify: `src/decision_lab/__init__.py`

**Interfaces:**
- Finalizes all Increment-6 public behavior.
- Uses existing Increment-5 replay engine as input only.
- Produces public exports for the eight archive symbols.

- [ ] **Step 1: Add RED partial-write cleanup test using a narrow os.fdopen monkeypatch**

Add:

```python
def test_partial_new_file_is_removed_after_write_failure(tmp_path, monkeypatch):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private"

    class BrokenWriter:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, data):
            raise OSError("simulated write failure")

    real_fdopen = os.fdopen

    def broken_fdopen(fd, mode):
        os.close(fd)
        return BrokenWriter()

    monkeypatch.setattr(os, "fdopen", broken_fdopen)

    with pytest.raises(OSError, match="simulated write failure"):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )

    path = replay_archive_path(record, root.resolve(strict=False))
    assert not path.exists()

    monkeypatch.setattr(os, "fdopen", real_fdopen)
```

The production behavior under test already exists from Task 3; this test proves cleanup rather than adding a new interface.

- [ ] **Step 2: Add RED nested market-diagnostic tamper test using a real registered-theme replay**

Build a minimal registered BASKET replay inside the test file:

```python
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.replay import ThemeReplayInput
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


def _market_replay_result():
    universe = ThemeUniverse(
        theme="ArchiveTheme",
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("layer"))
    universe.add_candidate(
        Candidate(
            ticker="AAA",
            theme="ArchiveTheme",
            layer="layer",
            effective_from="2026-01-01",
        )
    )
    package = ThemePackage(
        definition=ThemeDefinition(
            theme_id="ArchiveTheme",
            display_name="Archive Theme",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-01-01",
            version="1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path="fixture",
    )
    spec = MarketObservationSpec(
        theme_id="ArchiveTheme",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )
    bars = tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            available_at=f"{session}T21:00:00+00:00",
            close=close,
        )
        for symbol, closes in (
            ("SPY", (100, 100, 100)),
            ("AAA", (100, 100, 103)),
        )
        for session, close in zip(
            ("2026-09-17", "2026-09-18", "2026-09-19"),
            closes,
            strict=True,
        )
    )
    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(
                ThemeReplayInput(
                    package=package,
                    market_spec=spec,
                    market_config=MarketObservationConfig(),
                    bars=bars,
                    market_source_ref="fixture:archive-market",
                ),
            ),
            external_observations=(),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
```

Add:

```python
def test_nested_market_diagnostic_tamper_is_detected(tmp_path):
    record = build_replay_archive_record(_market_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["market_batches"][0]["diagnostics"][0][
        "current_excess_return"
    ] = 0.99
    path = (
        tmp_path
        / "2026-09-19"
        / f"{record.replay_result_hash}.json"
    )
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)
```

- [ ] **Step 3: Add exact schema/content-type/producer and malformed-object tests**

Add:

```python
@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("schema_version", "9.9"),
        ("content_type", "other"),
        ("producer", "other-producer"),
    ],
)
def test_reader_rejects_unsupported_archive_contract(
    tmp_path,
    field_name,
    bad_value,
):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload[field_name] = bad_value
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_non_object_top_level_json(tmp_path):
    path = tmp_path / "2026-09-19" / f"{'0' * 64}.json"
    _write_payload(path, ["not", "an", "object"])

    assert not verify_replay_archive(path)
    with pytest.raises(TypeError, match="archive must be a JSON object"):
        read_replay_archive(path)
```

Adjust test helper `_write_payload` to accept any JSON value.

- [ ] **Step 4: Add the full Increment-5 public-safe replay fixture and typed writer round-trip**

Add imports:

```python
from decision_lab.market_observation import (
    load_market_observation_config,
    load_market_observation_spec,
)
from decision_lab.themes import load_theme_package
```

Add the full replay fixture:

```python
ROOT = Path(__file__).resolve().parents[1]

REPLAY_SESSIONS = (
    "2026-09-03",
    "2026-09-04",
    "2026-09-08",
    "2026-09-09",
    "2026-09-10",
    "2026-09-11",
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
)


def _series(symbol, closes):
    return tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            available_at=f"{session}T21:00:00+00:00",
            close=close,
        )
        for session, close in zip(REPLAY_SESSIONS, closes, strict=True)
    )


def _full_replay_result():
    market_config = load_market_observation_config(
        ROOT / "config/adapters/market_observation_defaults.yaml"
    )
    dc_package = load_theme_package(
        ROOT / "config/themes/datacenter_infra.yaml"
    )
    bio_package = load_theme_package(
        ROOT / "config/themes/genomics_bio.yaml"
    )
    dc_spec = load_market_observation_spec(
        ROOT / "config/market_observations/datacenter_infra.yaml"
    )
    bio_spec = load_market_observation_spec(
        ROOT / "config/market_observations/genomics_bio.yaml"
    )

    dc_bars = (
        _series("SPY", [100] * 11)
        + _series(
            "BE",
            [100, 102, 104, 106, 108, 110, 106, 102, 98, 94, 90],
        )
        + _series(
            "NRG",
            [100, 101, 102, 103, 104, 105, 102, 99, 96, 93, 90],
        )
        + _series(
            "CEG",
            [100, 102, 103, 105, 106, 108, 106, 103, 100, 98, 95],
        )
    )
    bio_bars = (
        _series("SPY", [100] * 11)
        + _series(
            "ARKG",
            [100, 99, 98, 97, 96, 95, 100, 105, 110, 115, 120],
        )
        + _series(
            "XBI",
            [100, 99, 98, 97, 96, 96, 96.2, 96.4, 96.6, 96.8, 97.0],
        )
    )

    quiet_universe = ThemeUniverse(
        theme="QuietTheme",
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    quiet_universe.add_layer(ThemeLayer("layer"))
    quiet_package = ThemePackage(
        definition=ThemeDefinition(
            theme_id="QuietTheme",
            display_name="Quiet Theme",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-01-01",
            version="1",
        ),
        universe=quiet_universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path="fixture",
    )
    quiet_spec = MarketObservationSpec(
        theme_id="QuietTheme",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )

    def radar(theme, discovery, novelty):
        return ThemeScanObservation(
            theme_id=theme,
            as_of="2026-09-19",
            source_type="radar_model_output",
            source_ref=f"radar:{theme}:2026-09-19",
            discovery_signal=discovery,
            novelty_signal=novelty,
            support_direction=SupportDirection.SUPPORTING,
            evidence_refs=(f"radar:{theme}",),
            is_independent=False,
            observed_or_inferred="inferred",
        )

    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(
                ThemeReplayInput(
                    package=dc_package,
                    market_spec=dc_spec,
                    market_config=market_config,
                    bars=dc_bars,
                    market_source_ref="fixture:archive:datacenter",
                ),
                ThemeReplayInput(
                    package=bio_package,
                    market_spec=bio_spec,
                    market_config=market_config,
                    bars=bio_bars,
                    market_source_ref="fixture:archive:genomics",
                ),
                ThemeReplayInput(
                    package=quiet_package,
                    market_spec=quiet_spec,
                    market_config=market_config,
                    bars=(
                        MarketBar(
                            symbol="SPY",
                            session_date="2026-09-19",
                            available_at="2026-09-19T21:00:00+00:00",
                            close=100,
                        ),
                    ),
                    market_source_ref="fixture:archive:quiet",
                ),
            ),
            external_observations=(
                radar("DataCenter_Infra", 0.9, 0.8),
                radar("Genomics_Bio", 0.85, 0.75),
                radar("Rates", 0.8, 0.6),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
```

Then add:

```python
def test_write_read_verify_round_trip_preserves_full_typed_result(tmp_path):
    replay_result = _full_replay_result()
    record = build_replay_archive_record(replay_result)
    root = tmp_path / "recomputed" / "replay_cycles"

    written = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )
    loaded = read_replay_archive(written.path)

    assert verify_replay_archive(written.path)
    assert loaded == record
    assert loaded.replay_result == replay_result
```

Add:

```python
def test_archive_identity_is_independent_of_root_and_mtime(tmp_path):
    replay_result = _full_replay_result()
    first_record = build_replay_archive_record(replay_result)
    second_record = build_replay_archive_record(replay_result)
    assert first_record == second_record

    first = write_replay_archive(
        first_record,
        tmp_path / "private-a",
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
    )
    second = write_replay_archive(
        second_record,
        tmp_path / "private-b",
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
    )

    os.utime(first.path, (1_000_000, 1_000_000))

    assert verify_replay_archive(first.path)
    assert verify_replay_archive(second.path)
    assert read_replay_archive(first.path) == read_replay_archive(second.path)
```

- [ ] **Step 5: Add public import RED test**

Add:

```python
def test_replay_archive_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "ArchiveDestinationVisibility",
        "ReplayArchiveRecord",
        "ReplayArchiveWriteResult",
        "build_replay_archive_record",
        "read_replay_archive",
        "replay_archive_path",
        "verify_replay_archive",
        "write_replay_archive",
    ):
        assert getattr(decision_lab, name) is not None
```

Run only this test before changing `__init__.py`.

Expected: FAIL because exports do not exist.

- [ ] **Step 6: Export archive interfaces**

Modify `src/decision_lab/__init__.py`:

```python
from .replay_archive import (
    ArchiveDestinationVisibility,
    ReplayArchiveRecord,
    ReplayArchiveWriteResult,
    build_replay_archive_record,
    read_replay_archive,
    replay_archive_path,
    verify_replay_archive,
    write_replay_archive,
)
```

Add all eight names to the sorted `__all__`.

Do not export private decoder/validation helpers.

- [ ] **Step 7: Run Task-4 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/decision_lab/replay_archive.py src/decision_lab/__init__.py tests/test_replay_archive.py
git commit -m "test: prove replay archive round trip and tamper resistance"
```

---

### Task 5: Final safety audit, Ruff, exact-tree verification, and whole-branch review

**Files:**
- Verify: `src/decision_lab/replay_archive.py`
- Verify: `src/decision_lab/__init__.py`
- Verify: `tests/test_replay_archive.py`
- Review-only: all forbidden downstream modules.

**Interfaces:**
- Produces verification evidence only.
- No new public behavior.

- [ ] **Step 1: Run fresh full regression**

Run:

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run changed-files Ruff**

Run:

```bash
python -m ruff check   src/decision_lab/replay_archive.py   src/decision_lab/__init__.py   tests/test_replay_archive.py
```

Expected: exit 0.

- [ ] **Step 3: Audit forbidden semantic drift**

Verify no diffs to:

```text
src/decision_lab/replay.py
src/decision_lab/market_observation.py
src/decision_lab/scanner.py
src/decision_lab/research_budget.py
src/decision_lab/themes.py
src/decision_lab/universe.py
src/decision_lab/ledger.py
src/decision_lab/outcomes.py
src/decision_lab/tape.py
src/decision_lab/playbooks.py
```

Verify final PR contains no persistent new `.github/workflows` file.

Verify `replay_archive.py` contains no imports/calls for:

```text
requests
urllib
httpx
yfinance
alpaca
polygon
datetime.now
random
uuid
subprocess
socket
```

Filesystem imports `Path`, `os`, and `json` are expected only in this archive module.

- [ ] **Step 4: Whole-branch review against Review Focus**

Inspect specifically:

- v0.1 decoder field sets are hard-coded and recursive;
- `read_replay_archive` never trusts stored result hash without recomputation;
- input hash is only checked for top-level/nested equality, never falsely claimed independently recomputed;
- `archive_record_hash` excludes itself;
- path uses UTC cycle date;
- filename equals nested/top-level replay result hash;
- directory date matches cycle_as_of;
- PUBLIC policy requires explicit `public_safe=True` before `mkdir`;
- PUBLIC path suffix is checked on resolved path;
- ledger/live sequence is checked on resolved path for all visibility modes;
- O_EXCL is used;
- pre-existing invalid/conflicting bytes are never overwritten/deleted;
- newly-created partial file is removed after write failure;
- identical pre-existing valid file returns `created=False`;
- reader returns typed enums/dataclasses, not dicts;
- NaN/Infinity cannot be serialized/hashed;
- `run_replay_cycle` remains untouched;
- tests only write under `tmp_path`.

Any Critical/Important issue gets one TDD fix pass:

1. write reproducing RED test;
2. verify RED;
3. implement minimal fix;
4. rerun test;
5. rerun full suite and Ruff.

- [ ] **Step 5: Exact-final-tree verification**

On the exact final branch head run:

```bash
pytest -q
python -m ruff check   src/decision_lab/replay_archive.py   src/decision_lab/__init__.py   tests/test_replay_archive.py
```

Record exact pytest count/time and Ruff result.

- [ ] **Step 6: Keep branch unmerged**

Present integration options after exact-final-tree verification. Do not merge until explicit user authorization.
