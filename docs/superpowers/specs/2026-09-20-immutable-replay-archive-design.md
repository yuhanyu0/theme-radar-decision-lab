# Increment 6 — Immutable Replay Archive Design

Date: 2026-09-20
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/immutable-replay-archive

## 1. Purpose

Turn a deterministic ReplayCycleResult into a durable, content-addressed, self-verifying historical research artifact.

Target flow:

    ReplayCycleResult
      -> build_replay_archive_record
      -> deterministic JSON payload
      -> immutable content-addressed path
      -> write/read/verify round-trip
      -> typed ReplayCycleResult reconstruction

Increment 6 creates the historical substrate needed for later replay-cohort and walk-forward evaluation.

It does not evaluate replay quality, returns, allocation utility, or downstream trading decisions.

## 2. Scientific role

Increment 5 answers:

    Given frozen evidence now, what research allocation does the system produce?

Increment 6 adds:

    What exactly did that cycle produce, and can we prove later that the artifact was not silently changed?

The archive freezes the distinction between:

- what the replay input committed to;
- what the replay result committed to;
- the exact serialized result stored on disk.

This is a research-history artifact, not a trade ledger.

## 3. Core invariant

The archive is content-addressed by ReplayCycleResult.result_hash.

For a valid replay result R:

    archive_path(R)
      = <archive_root>/<cycle_date>/<R.result_hash>.json

and:

    same ReplayCycleResult
      -> same archive payload
      -> same archive_record_hash
      -> same archive path

The writer never silently overwrites an existing archive.

## 4. Selected architecture

Add one focused module:

    src/decision_lab/replay_archive.py

Public interfaces:

    build_replay_archive_record(
        replay_result: ReplayCycleResult,
    ) -> ReplayArchiveRecord

    replay_archive_path(
        record: ReplayArchiveRecord,
        archive_root: str | Path,
    ) -> Path

    write_replay_archive(
        record: ReplayArchiveRecord,
        archive_root: str | Path,
        *,
        destination_visibility: ArchiveDestinationVisibility,
        public_safe: bool = False,
    ) -> ReplayArchiveWriteResult

    read_replay_archive(
        path: str | Path,
    ) -> ReplayArchiveRecord

    verify_replay_archive(
        path: str | Path,
    ) -> bool

No change is made to run_replay_cycle.

## 5. Explicit non-goals

Increment 6 does not add:

- replay cohort evaluation;
- forward-return scoring;
- manifest/index files;
- SQLite/Postgres;
- caching;
- archive search;
- scheduled replay jobs;
- live market/Radar fetching;
- company research;
- linkage;
- Tape;
- playbook routing;
- Decision Ledger writes;
- portfolio sizing;
- brokerage execution;
- cloud object storage;
- automatic privacy classification;
- archive migrations across schema versions.

## 6. Why not reuse ledger/live

Replay archives belong under:

    recomputed/replay_cycles/

They do not belong under:

    ledger/live/

Reason:

- ledger/live is for immutable live Decision Objects;
- ReplayCycleResult is a research-routing/recomputation artifact;
- DataCenter FULL research can mean forced contradiction review, not a bullish decision;
- mixing replay allocations with live trade decisions would collapse two distinct semantics.

The archive writer must reject any destination rooted under a ledger/live path.

## 7. Why no manifest in v0.1

Do not add a manifest or mutable index.

A directory of content-addressed files is already discoverable.

Adding:

    manifest.json

would create a second state that could become stale while the archive file remains correct.

Cross-cycle indexing is deferred until a real query need exists.

## 8. No archived_at in the semantic record

Version 0.1 deliberately does not store archived_at.

Reason:

    same scientific replay
    archived at 12:01
    versus archived at 12:05

must not become two different archive payloads.

Filesystem metadata such as mtime is operational metadata and is not part of the scientific identity.

If later work needs:

- who archived the record;
- wall-clock archive time;
- ingestion host;
- operator metadata;

those belong in a separate outer index/envelope, not in ReplayArchiveRecord v0.1.

## 9. Archive schema

### 9.1 ReplayArchiveRecord

    ReplayArchiveRecord
      schema_version: str
      content_type: str
      producer: str
      cycle_as_of: str
      replay_input_hash: str
      replay_result_hash: str
      replay_result: ReplayCycleResult
      archive_record_hash: str

Exact v0.1 constants:

    schema_version = "0.1"
    content_type = "replay_cycle_result"
    producer = "theme-radar-decision-lab/replay-archive@0.1"

No caller-supplied arbitrary provenance field is stored in v0.1.

ReplayCycleResult already contains the evidence/config/package commitments that define the replay result.

Arbitrary environment provenance is deferred because making it part of the same content-addressed record would cause identical replay results to collide with different metadata.

## 10. Archive record hash

archive_record_hash is computed over the exact archive semantic payload with archive_record_hash omitted.

Define:

    archive_payload_without_hash = {
        "schema_version": ...,
        "content_type": ...,
        "producer": ...,
        "cycle_as_of": ...,
        "replay_input_hash": ...,
        "replay_result_hash": ...,
        "replay_result": asdict(replay_result),
    }

Then:

    archive_record_hash =
        canonical_hash(archive_payload_without_hash)

This hash binds the complete stored replay result.

It has no self-reference.

## 11. Replay result verification

An archive must not trust embedded ReplayCycleResult.result_hash.

Given serialized replay_result payload:

1. require all expected ReplayCycleResult top-level fields;
2. read stored nested result_hash;
3. construct the result payload exactly as Increment 5 did:

       {
         "cycle_as_of": ...,
         "input_hash": ...,
         "market_batches": ...,
         "combined_observations": ...,
         "scan_results": ...,
         "allocations": ...,
         "theme_records": ...,
       }

4. recompute:

       canonical_hash(result_payload)

5. require equality with replay_result.result_hash.

This independently detects tampering with nested market batches, scan results, allocations, or theme records.

## 12. Input-hash verification boundary

ReplayCycleResult stores input_hash but does not contain the full semantic ReplayCycleInput payload.

Therefore Increment 6 can verify:

    top-level replay_input_hash
      == replay_result.input_hash

but cannot independently recompute input_hash from the archive alone.

Do not claim otherwise.

Full input-snapshot archival is a separate future design because it changes privacy/storage scope materially.

## 13. Top-level consistency checks

For a valid ReplayArchiveRecord:

    record.cycle_as_of
      == record.replay_result.cycle_as_of

    record.replay_input_hash
      == record.replay_result.input_hash

    record.replay_result_hash
      == record.replay_result.result_hash

All three must hold.

A mismatch is invalid even if archive_record_hash itself matches the malformed payload.

## 14. Hash format validation

All of these must be lowercase 64-character SHA-256 hex strings:

- replay_input_hash;
- replay_result_hash;
- replay_result.input_hash;
- replay_result.result_hash;
- archive_record_hash.

Reject uppercase, truncated, non-hex, or malformed values.

## 15. Archive cycle directory

Archive path uses the UTC cycle date derived from cycle_as_of.

Rules:

- date-only cycle_as_of -> that date;
- datetime cycle_as_of -> parse ISO datetime, normalize to UTC, take UTC date;
- naive datetime -> interpret as UTC, matching replay semantics.

Example:

    cycle_as_of = 2026-09-19T23:30:00-04:00

maps to archive directory:

    2026-09-20/

## 16. Standard public-repo path

For this repository, the standard archive root is:

    recomputed/replay_cycles/

Example:

    recomputed/replay_cycles/
      2026-09-19/
        <64-char-result-hash>.json

The core writer does not infer the git repository root from ambient cwd.

The caller passes archive_root explicitly.

## 17. ArchiveDestinationVisibility

Define:

    class ArchiveDestinationVisibility(str, Enum):
        PUBLIC = "public"
        PRIVATE = "private"

The writer does not detect repository visibility automatically.

The caller explicitly declares destination visibility.

## 18. Public-safe gate

For:

    destination_visibility = PUBLIC

the writer requires:

    public_safe is True

Otherwise raise:

    PermissionError(
        "public archive write requires explicit public_safe=True"
    )

This is an explicit caller affirmation only.

It is not an automated privacy scanner.

Version 0.1 does not inspect the replay payload and claim to know whether data is sensitive or licensed.

## 19. Private destination behavior

For:

    destination_visibility = PRIVATE

the writer does not require public_safe=True.

The same immutable/content-addressed semantics apply.

This does not add cloud/private-store integration; it simply allows a caller-selected private filesystem root.

## 20. Public root restriction

When destination_visibility is PUBLIC, archive_root must end with the path components:

    recomputed/replay_cycles

Otherwise raise:

    ValueError(
        "public replay archives must use recomputed/replay_cycles"
    )

Examples allowed:

    recomputed/replay_cycles
    /workspace/project/recomputed/replay_cycles

Examples rejected:

    reports/replay_cycles
    ledger/live
    /tmp/public-output

This guards against accidentally treating another public directory as the canonical replay archive.

## 21. Hard ledger/live prohibition

Regardless of visibility, reject any archive_root whose normalized path contains contiguous components:

    ledger/live

Raise:

    ValueError("replay archives may not be written under ledger/live")

This is a semantic safety invariant, not just a public-repo rule.

## 22. ReplayArchiveWriteResult

    ReplayArchiveWriteResult
      path: Path
      created: bool
      replay_result_hash: str
      archive_record_hash: str

Meanings:

- created=True: this call created the file;
- created=False: an existing valid identical archive already occupied the canonical path.

## 23. Deterministic JSON representation

Serialize ReplayArchiveRecord as UTF-8 JSON:

- ensure_ascii=False;
- sort_keys=True;
- indent=2;
- allow_nan=False;
- trailing newline.

Enums are serialized to their string values.

Tuples are serialized as JSON arrays.

The archive_record_hash is computed from canonical_hash over the semantic Python payload, not from pretty-printed bytes.

Whitespace differences therefore do not change scientific identity.

## 24. Exact field policy

Version 0.1 reader accepts exactly these top-level archive keys:

    schema_version
    content_type
    producer
    cycle_as_of
    replay_input_hash
    replay_result_hash
    replay_result
    archive_record_hash

Missing or extra top-level keys are invalid.

This prevents a reader from silently ignoring unversioned schema additions.

## 25. Schema/version policy

read_replay_archive supports exactly:

    schema_version == "0.1"

and:

    content_type == "replay_cycle_result"

and:

    producer == "theme-radar-decision-lab/replay-archive@0.1"

Anything else raises ValueError.

No schema migration is attempted in Increment 6.

## 26. ReplayCycleResult typed reconstruction

read_replay_archive returns a typed ReplayArchiveRecord whose replay_result is a typed ReplayCycleResult.

The decoder reconstructs:

- ReplayCycleResult;
- ReplayThemeRecord;
- ReplayStatus;
- MarketObservationBatch;
- MarketObservationDiagnostics;
- MarketObservationMode;
- MarketObservationStatus;
- ThemeScanObservation;
- SupportDirection;
- ThemeScanResult;
- ResearchAllocation;
- ResearchTier.

No generic dict-only return is used for the public reader.

## 27. Decoder strictness

For each reconstructed dataclass:

- the JSON object must contain exactly the field names of the v0.1 dataclass contract;
- missing fields are invalid;
- extra fields are invalid;
- enum strings must map to valid enum values;
- tuple/list fields must have the expected container type;
- nested objects must be mappings;
- unexpected structural types raise ValueError or TypeError;
- numeric values are not silently coerced from arbitrary strings.

Exact-field enforcement applies recursively to ReplayCycleResult, ReplayThemeRecord, MarketObservationBatch, MarketObservationDiagnostics, ThemeScanObservation, ThemeScanResult, and ResearchAllocation.

The reader is not a permissive migration layer.

## 28. Build behavior

build_replay_archive_record(replay_result):

1. validate replay_result.input_hash format;
2. validate replay_result.result_hash format;
3. independently recompute replay_result.result_hash from replay_result contents;
4. reject if it does not match;
5. construct deterministic archive payload;
6. compute archive_record_hash;
7. return ReplayArchiveRecord.

It has no filesystem side effects.

## 29. Canonical path behavior

replay_archive_path(record, archive_root):

1. validate record replay_result_hash format;
2. derive UTC cycle date from record.cycle_as_of;
3. return:

       Path(archive_root)
       / cycle_date
       / f"{record.replay_result_hash}.json"

It does not create directories.

## 30. Immutable write algorithm

write_replay_archive performs:

1. validate destination policy before touching filesystem;
2. validate the ReplayArchiveRecord completely;
3. derive canonical path;
4. create parent directories with parents=True, exist_ok=True;
5. attempt exclusive file creation using:

       os.O_WRONLY | os.O_CREAT | os.O_EXCL

6. if creation succeeds:
   - write deterministic JSON;
   - flush/close;
   - return created=True.

7. if exclusive creation reports FileExistsError:
   - read existing file;
   - verify it fully;
   - compare existing semantic archive payload with requested payload;
   - if identical, return created=False;
   - otherwise raise FileExistsError indicating content conflict.

No overwrite flag exists.

## 31. Partial-write cleanup

If a newly-created archive file encounters an exception while being written:

- close the descriptor if needed;
- unlink only the file created by this call;
- re-raise the original error.

Never delete a pre-existing file.

## 32. Idempotence

Calling:

    write_replay_archive(record, same_root, ...)

twice must produce:

first call:

    created=True

second call:

    created=False

and the same:

- path;
- replay_result_hash;
- archive_record_hash.

No duplicate file is created.

## 33. Existing-file conflict

If canonical path already exists but contains:

- invalid JSON;
- invalid archive hash;
- different archive payload;
- different nested replay result;
- wrong schema;
- wrong result hash;

the writer must not overwrite it.

Raise FileExistsError.

This protects the binding:

    replay_result_hash
      <-> exact archived semantic payload

## 34. Reader behavior

read_replay_archive(path):

1. read UTF-8 JSON;
2. require a JSON object;
3. enforce exact top-level field set;
4. validate schema/content_type/producer;
5. validate top-level hash formats;
6. validate archive_record_hash;
7. validate nested replay_result hash independently;
8. validate top-level/nested cycle/input/result consistency;
9. validate canonical filename and cycle directory;
10. reconstruct typed ReplayCycleResult;
11. return typed ReplayArchiveRecord.

Any violation raises ValueError unless the underlying I/O raises FileNotFoundError/PermissionError.

## 35. Filename verification

For a standard archive file:

    path.name

must equal:

    f"{record.replay_result_hash}.json"

If not, verification fails.

The reader also requires:

    path.parent.name

to equal the UTC cycle-date directory derived from cycle_as_of.

This prevents a valid payload copied under a misleading canonical path from passing archive verification.

## 36. verify_replay_archive

verify_replay_archive(path) -> bool

Behavior:

- return True only if read_replay_archive(path) would fully succeed;
- return False for:
  - malformed JSON;
  - wrong schema;
  - hash mismatch;
  - nested replay-result mismatch;
  - filename mismatch;
  - cycle-directory mismatch;
  - type/enum decode failure.

FileNotFoundError also returns False.

PermissionError may propagate because it is an environment/access problem rather than record invalidity.

## 37. Record reconstruction equality

For a valid ReplayCycleResult result:

    record = build_replay_archive_record(result)
    write_replay_archive(record, ...)
    loaded = read_replay_archive(path)

must satisfy:

    loaded == record
    loaded.replay_result == result

This is the core round-trip property.

## 38. Replay purity preservation

Increment 6 must not modify:

    run_replay_cycle

to write archives automatically.

This remains true:

    run_replay_cycle(...)
      -> zero filesystem writes

Archival requires an explicit second call.

## 39. Archive identity versus filesystem metadata

File mtime, inode, permissions, and directory creation time do not enter:

- replay_input_hash;
- replay_result_hash;
- archive_record_hash.

Touching a valid file's mtime must not change read/verify outcome.

Scientific identity is payload-based.

## 40. Public-safe payload guidance

When writing to the current public repository, the caller should only set public_safe=True for replay artifacts containing public-safe material.

Examples appropriate for tests/public archive:

- synthetic market bars already reduced into replay results;
- public ticker symbols;
- public configuration identifiers/hashes;
- public-safe Radar-like observations;
- deterministic research allocations.

Do not affirm public_safe=True for records containing:

- personal holdings;
- position sizes;
- account identifiers;
- brokerage balances;
- credentials/tokens;
- private notes;
- proprietary licensed raw payloads;
- confidential employer data.

The writer cannot detect these reliably.

## 41. No raw-bar archival added

ReplayCycleResult contains MarketObservationBatch diagnostics/observations, not raw MarketBar tuples.

Increment 6 archives ReplayCycleResult only.

It does not broaden the data-retention surface to raw market inputs.

## 42. First round-trip acceptance fixture

Use Increment 5's public-safe end-to-end fixture:

    DataCenter_Infra
    Genomics_Bio
    Rates
    registered NO_OBSERVATION theme

Produce:

    ReplayCycleResult

Then:

    build_replay_archive_record
      -> write to temp/recomputed/replay_cycles
      -> read
      -> verify
      -> reconstruct

Required:

    loaded.replay_result == original ReplayCycleResult
    verify_replay_archive(path) is True

No live network data is used.

## 43. Idempotence acceptance

Same record, same root:

first write:

    created=True

second write:

    created=False

Same canonical path and both hashes.

Directory contains exactly one archive JSON file for that result.

## 44. Tamper acceptance

Starting from a valid archive, separately mutate:

1. nested allocation.tier;
2. nested scan_result.research_priority;
3. nested MarketObservationDiagnostics.current_excess_return;
4. embedded replay_result.result_hash;
5. top-level replay_result_hash;
6. top-level replay_input_hash;
7. archive_record_hash.

Each mutation must make:

    verify_replay_archive(path) == False

and:

    read_replay_archive(path)

raise ValueError.

## 45. Path-tamper acceptance

Copy a valid archive to:

- a wrong result-hash filename;
- a wrong cycle-date directory.

Both must fail verification even though the JSON payload is unchanged.

## 46. Existing conflict acceptance

Create a file at the canonical path containing a different/invalid payload.

Then call write_replay_archive with the valid requested record.

Required:

- writer raises FileExistsError;
- existing file bytes remain unchanged.

## 47. Public-safety acceptance

PUBLIC destination:

    public_safe=False
      -> PermissionError
      -> no directory created

PUBLIC destination with wrong root suffix:

    public_safe=True
      -> ValueError
      -> no directory created

PRIVATE destination:

    public_safe=False
      -> allowed

Any ledger/live destination:

    -> ValueError
    -> no directory created

## 48. Archive-root normalization

Destination policy checks happen on resolved normalized path parts.

Before any directory creation:

    resolved_root = Path(archive_root).expanduser().resolve(strict=False)

Use resolved_root.parts for all PUBLIC-root and ledger/live policy checks.

This prevents a symlinked archive_root from bypassing the semantic destination policy.

Do not rely on string substring tests such as:

    "ledger/live" in str(path)

because platform separators and unrelated names can produce false results.

Use contiguous component matching over resolved Path.parts.

## 49. Concurrency semantics

Two processes may attempt to write the same record concurrently.

O_EXCL guarantees at most one creates the file.

The loser follows the existing-file path:

- once the file is readable and valid and identical -> created=False;
- if the file is temporarily incomplete because the winning process has not finished, the loser may receive FileExistsError rather than treating partial data as valid.

Version 0.1 does not add retry/backoff or file locks.

This is fail-closed and acceptable.

## 50. Archive JSON size

Version 0.1 stores one complete ReplayCycleResult per file even though ReplayThemeRecord duplicates nested market/scan/allocation objects already present in top-level tuples.

Do not normalize/deduplicate this representation in Increment 6.

Reason:

- ReplayCycleResult.result_hash already commits to the current structure;
- changing representation would complicate independent result-hash verification;
- replay artifacts are currently small.

## 51. Decoder implementation boundary

Keep decoder helpers private inside replay_archive.py.

Suggested private helpers:

    _parse_cycle_date
    _validate_sha256_hex
    _replay_result_payload_without_hash
    _recompute_replay_result_hash
    _archive_payload_without_hash
    _serialize_archive_record
    _require_exact_fields
    _decode_support_direction
    _decode_theme_scan_observation
    _decode_market_diagnostic
    _decode_market_batch
    _decode_scan_result
    _decode_allocation
    _decode_theme_record
    _decode_replay_result
    _validate_archive_record
    _contains_path_sequence

Do not expose generic serialization framework abstractions.

## 52. Proposed public types

### ReplayArchiveRecord

Frozen dataclass.

### ReplayArchiveWriteResult

Frozen dataclass.

### ArchiveDestinationVisibility

String Enum with PUBLIC/PRIVATE.

No mutable archive manager/service object is needed.

## 53. Error taxonomy

Use built-in exception types:

### ValueError

Malformed or inconsistent archive semantics:

- invalid hashes;
- unsupported schema/content type/producer;
- replay hash mismatch;
- archive hash mismatch;
- canonical path mismatch;
- public root mismatch;
- ledger/live prohibition.

### PermissionError

PUBLIC write without public_safe=True.

### FileExistsError

Canonical path occupied by conflicting/invalid content.

### FileNotFoundError

read_replay_archive on missing file.

Do not add a custom exception hierarchy in v0.1.

## 54. Public exports

Add these to decision_lab.__init__:

    ArchiveDestinationVisibility
    ReplayArchiveRecord
    ReplayArchiveWriteResult
    build_replay_archive_record
    read_replay_archive
    replay_archive_path
    verify_replay_archive
    write_replay_archive

Do not export decoder/private validation helpers.

## 55. Files

Create:

    src/decision_lab/replay_archive.py

Create:

    tests/test_replay_archive.py

Modify only for exports:

    src/decision_lab/__init__.py

Do not modify behavior in:

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

If archive implementation appears to require a semantic change in those modules, stop and upgrade scope rather than editing them silently.

## 56. Test filesystem policy

All archive write/read/tamper tests use pytest tmp_path.

Tests must never write to the repository's real:

    recomputed/
    ledger/live/

No cleanup logic may target real repository state.

## 57. Determinism acceptance

For semantically identical ReplayCycleResult objects:

    build_replay_archive_record(first)
      == build_replay_archive_record(second)

even if:

- they were computed in separate calls;
- filesystem mtimes differ;
- archive roots differ.

archive_record_hash depends only on record semantic payload.

## 58. No ambient-state dependency

build_replay_archive_record and replay_archive_path must not depend on:

- datetime.now;
- environment variables;
- cwd;
- git state;
- network;
- randomness;
- UUIDs.

write_replay_archive depends only on the explicit archive_root/destination flags plus filesystem state.

## 59. No hidden repair

Reader/verifier never:

- rewrites a bad hash;
- renames a wrong file;
- normalizes an invalid enum;
- replaces a corrupted field;
- repairs a malformed archive.

Invalid records remain invalid.

## 60. Future Increment 7 compatibility

Increment 7 may scan archive directories to build replay cohorts.

Therefore v0.1 guarantees:

- stable schema_version;
- stable canonical result-hash filename;
- stable cycle-date directory;
- deterministic typed reconstruction;
- explicit NO_OBSERVATION versus SCAN_ONLY preservation;
- no mutable manifest dependency.

Increment 7 should treat archive files as source records and any cohort index as derived/rebuildable state.

## 61. Functional acceptance checklist

Increment 6 is complete when tests prove:

1. valid ReplayCycleResult builds deterministic record;
2. invalid nested ReplayCycleResult.result_hash is rejected at build;
3. archive_record_hash has no self-reference;
4. top-level/nested cycle/input/result fields agree;
5. standard path uses UTC cycle date;
6. same record writes idempotently;
7. writer never overwrites conflict;
8. partial newly-created file is cleaned on write failure;
9. public-safe gate occurs before directory creation;
10. public root suffix is enforced;
11. ledger/live is always rejected;
12. private filesystem destination is permitted;
13. valid archive round-trips to equal typed ReplayCycleResult;
14. nested allocation tamper is detected;
15. nested scan-result tamper is detected;
16. nested market diagnostic tamper is detected;
17. top-level input/result hash tamper is detected;
18. archive_record_hash tamper is detected;
19. wrong filename is detected;
20. wrong cycle directory is detected;
21. malformed JSON is invalid;
22. missing/extra top-level fields are invalid;
23. unsupported schema is invalid;
24. invalid enum/type in nested payload is invalid;
25. verify returns False for invalid/missing archive;
26. run_replay_cycle remains filesystem-pure;
27. no forbidden downstream module changes;
28. all existing tests remain green;
29. changed-files Ruff passes.

## 62. Deferred work

Deliberately deferred:

- archive manifests;
- cohort indexes;
- SQLite;
- search/query API;
- archive compression;
- schema migrations;
- raw ReplayCycleInput snapshot archival;
- archive signatures/HMAC;
- cloud object storage;
- automatic public/private classification;
- scheduled archive creation;
- replay cohort evaluation;
- forward outcome attribution;
- threshold calibration;
- FULL_DECISION_RESEARCH executor.

## 63. Completion criterion

Increment 6 is complete when a public-safe ReplayCycleResult can be:

    built
      -> archived immutably
      -> written twice idempotently
      -> read back as typed data
      -> independently hash-verified
      -> rejected after nested tampering
      -> rejected under misleading canonical paths

while:

- run_replay_cycle stays pure;
- ledger/live stays untouched;
- no mutable index exists;
- no raw input data retention is added;
- no downstream research/execution semantics change.


## 64. Non-finite JSON rejection

Archive serialization and verification must reject NaN and Infinity.

Replay archives are intended to be portable standards-compliant JSON.

Use allow_nan=False for pretty serialization and canonical_hash already rejects non-finite values.

A manually-constructed ReplayCycleResult containing a non-finite numeric field must fail build/serialization rather than emit non-standard JSON.

## 65. Symlink destination acceptance

Add filesystem tests proving destination policy is applied after path resolution where symlinks are supported.

At minimum:

- a symlinked root resolving under ledger/live is rejected;
- PUBLIC root symlinked to a non-recomputed destination is rejected.

If the test platform does not support symlink creation, mark only those platform-specific tests skipped; the non-symlink policy tests remain mandatory.
