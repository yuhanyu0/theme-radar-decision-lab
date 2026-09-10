# Private-mode activation checklist

Live Decision Ledger writes and scheduled cross-repository research are intentionally disabled while this repository is public.

## 1. Make this repository private

In GitHub, change `theme-radar-decision-lab` visibility to **Private** before adding any live decisions, private Radar snapshots, proprietary thresholds, account-specific context, or secrets.

## 2. Add read-only access to the private Radar repository

The default `GITHUB_TOKEN` for this repository should not be assumed to read a separate private repository. Create a fine-grained token with the minimum required scope:

- Repository access: `yuhanyu0/theme-radar-log` only
- Repository permissions: **Contents: Read-only**
- No write/admin permissions

Store it as an Actions secret named:

`RADAR_REPO_TOKEN`

The Decision Lab code reads this token only from the environment and never writes it into artifacts or the ledger.

## 3. Market-data provider

The public-safe MVP uses adjusted daily data from `yfinance` for development. Production should use a timestamped, contractual market-data provider and retain provenance/as-of metadata. Provider credentials must be stored as Actions secrets and must never be committed.

## 4. Primary company evidence

Production candidate promotion should prefer SEC filings, company earnings releases/IR, official macro/industry sources, and only then reputable reporting. Radar output remains `source_type=radar_model_output` and is lower-trust than primary evidence.

## 5. Live ledger guard

`ledger/live/` is append-only. A live writer must:

- generate a new decision id/path;
- refuse overwrite (`O_EXCL` invariant);
- record source timestamps and source hashes;
- record model/config version;
- put any later-model replay under `recomputed/` instead of rewriting history.

## 6. Scheduled workflow sequence after private activation

Recommended production order:

1. Verify market calendar/session freshness.
2. Freeze independent market evidence.
3. Read the latest valid Radar model output with `RADAR_REPO_TOKEN`.
4. Read/derive structural maturity only from a valid Navigator source; never fabricate missing Navigator fields from the Daily Radar log.
5. Refresh the dynamic theme universe and primary company evidence.
6. Rebuild leave-one-out layer controls and layer-equal composite controls.
7. Compute linkage diagnostics and circularity warnings.
8. Compute Tape path state and A-H/NoTrade match scores.
9. Compile and append immutable Decision Objects only for material state changes.
10. Update 1/3/5/10/20D outcomes in separate outcome files.
11. Run weekly walk-forward summaries including missed upside for BLOCKED/WATCH_ONLY decisions.

## 7. Minimum go-live acceptance tests

Before enabling scheduled live writes, CI must prove:

- target ticker is excluded from every control used to evaluate it;
- identity-like controls are flagged;
- C cannot execute a falling knife;
- B cannot jump directly from failed path to clean retest;
- Decision Ledger overwrite fails;
- live and recomputed directories cannot be mixed by the writer;
- missing/stale Radar or Navigator input causes an explicit degraded state, never silent substitution;
- probability outputs remain labelled uncalibrated until enough immutable live samples exist.
