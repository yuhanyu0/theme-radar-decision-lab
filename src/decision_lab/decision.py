from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .ledger import canonical_hash
from .linkage import LinkageResult
from .playbooks import PlaybookRouting
from .tape import TapeAssessment


def compile_decision(
    *,
    decision_id: str,
    market_asof: str,
    theme: str,
    ticker: str,
    theme_state: str,
    theme_key: bool,
    company_state: str,
    tape: TapeAssessment,
    routing: PlaybookRouting,
    strongest_reason_not_to_trade: str,
    model_version: str,
    config_payload: Any,
    dynamic_universe_layer: str | None = None,
    company_thesis: str | None = None,
    linkage: LinkageResult | None = None,
    radar_run_id: str | None = None,
    radar_source_commit: str | None = None,
    world_raw: str | None = None,
    world_calibrated: str | None = None,
    world_confidence: str | None = None,
    max_permission: str | float | None = None,
    entry_condition: str | None = None,
    invalidation: str | None = None,
    evidence_refs: list[str] | None = None,
    source_timestamps: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Compile a single immutable Decision Object.

    This function does not write to disk and never sends orders. The resulting object
    can be frozen with `write_immutable_json`.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    playbook_scores = dict(routing.normalized_scores)

    decision = {
        "decision_id": decision_id,
        "created_at": created_at,
        "market_asof": market_asof,
        "theme": theme,
        "ticker": ticker.upper(),
        "radar_run_id": radar_run_id,
        "radar_source_commit": radar_source_commit,
        "world_raw": world_raw,
        "world_calibrated": world_calibrated,
        "world_confidence": world_confidence,
        "theme_state": theme_state,
        "theme_key": bool(theme_key),
        "dynamic_universe_layer": dynamic_universe_layer,
        "company_state": company_state,
        "company_thesis": company_thesis,
        "linkage": {} if linkage is None else asdict(linkage),
        "tape": asdict(tape),
        "playbooks": {
            "scores": playbook_scores,
            "raw_scores": dict(routing.raw_scores),
            "selected": routing.selected_playbook,
            "probability_is_calibrated": routing.probability_is_calibrated,
            "sample_size": None,
            "rationale": list(routing.rationale),
        },
        "action": routing.action,
        "max_permission": max_permission,
        "entry_condition": entry_condition,
        "invalidation": invalidation,
        "strongest_reason_not_to_trade": strongest_reason_not_to_trade,
        "evidence_refs": evidence_refs or [],
        "source_timestamps": source_timestamps or {},
        "model_version": model_version,
        "config_hash": canonical_hash(config_payload),
    }
    decision["decision_payload_hash"] = canonical_hash(decision)
    return decision
