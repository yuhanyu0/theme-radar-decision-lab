"""G1 experimental controlled-disclosure reader. No file/network/outcome inputs.

This is a finite grammar, not a general natural-language or financial model.
See PROTOCOL.md for the synthetic authority and arithmetic contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
import re
import sys

ALIASES = {
    "company": "company", "entity": "company",
    "period": "period", "fiscal period": "period",
    "published": "published", "issued": "published", "revision": "revision",
    "net debt": "net_debt_usd", "net borrowings": "net_debt_usd",
    "ebitda": "ebitda_usd", "operating ebitda": "ebitda_usd",
    "maximum leverage": "maximum_leverage", "covenant ceiling": "maximum_leverage",
}
FIELDS = ("net_debt_usd", "ebitda_usd", "maximum_leverage")
NUM = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MONEY = re.compile(rf"USD\s+({NUM})(?:\s+(dollars?|thousand|million|billion|k|m|b))?", re.I)
MULTIPLE = re.compile(rf"({NUM})\s*(?:x|×|times)", re.I)
SCALES = {"": 1, "dollar": 1, "dollars": 1, "thousand": 1000, "k": 1000,
          "million": 1000000, "m": 1000000, "billion": 1000000000, "b": 1000000000}


def _utc(value: str) -> datetime:
    d = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timezone required")
    return d.astimezone(timezone.utc)


def _number(field: str, text: str) -> Decimal:
    pattern = MULTIPLE if field == "maximum_leverage" else MONEY
    match = pattern.fullmatch(text.strip())
    if match is None:
        raise ValueError("unsupported numeric field")
    value = Decimal(match[1].replace(",", ""))
    if field != "maximum_leverage":
        value *= SCALES[(match[2] or "").lower()]
    if not value.is_finite() or abs(value) > Decimal("1e30"):
        raise ValueError("numeric range exceeded")
    return value


def _fmt(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_facts(query: dict, evidence: list[str]) -> dict:
    """Return content-derived facts/verdict only; unknowns do not become false."""
    if not isinstance(query, dict) or set(query) != {"company", "period", "as_of"}:
        raise ValueError("query must contain only company, period, as_of")
    if not all(isinstance(v, str) and v.strip() for v in query.values()):
        raise ValueError("query values must be nonempty strings")
    if not isinstance(evidence, list) or not all(isinstance(v, str) for v in evidence):
        raise TypeError("evidence must be a list of disclosure bodies")
    as_of = _utc(query["as_of"])
    observations: dict[str, list[tuple[int, Decimal]]] = {f: [] for f in FIELDS}
    errors: set[str] = set()
    for body in evidence:
        parsed: dict[str, list[str]] = {}
        for line in body.splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            field = ALIASES.get(" ".join(key.lower().split()))
            if field:
                parsed.setdefault(field, []).append(value.strip())
        # Ignore documents outside the explicit question, before reading values.
        if not parsed.get("company") or not parsed.get("period"):
            continue
        if query["company"].strip().upper() not in [v.upper() for v in parsed["company"]]:
            continue
        if query["period"].strip().upper() not in [v.upper() for v in parsed["period"]]:
            continue
        headers = ("company", "period", "published", "revision")
        if any(len(parsed.get(k, [])) != 1 for k in headers):
            errors.add("invalid_or_missing_header")
            continue
        try:
            available = _utc(parsed["published"][0])
            if available > as_of:
                continue
            revision_text = parsed["revision"][0]
            if re.fullmatch(r"\d+", revision_text) is None:
                raise ValueError("invalid revision")
            revision = int(revision_text)
        except (ValueError, OverflowError):
            errors.add("invalid_availability_or_revision")
            continue
        for field in FIELDS:
            for text in parsed.get(field, []):
                try:
                    with localcontext() as ctx:
                        ctx.prec = 80
                        value = _number(field, text)
                    observations[field].append((revision, value))
                except (ValueError, InvalidOperation):
                    errors.add("invalid_numeric:" + field)
    values: dict[str, Decimal] = {}
    conflicts: list[str] = []
    missing: list[str] = []
    for field in FIELDS:
        observed = observations[field]
        if not observed:
            missing.append(field)
            continue
        latest = max(r for r, _ in observed)
        unique = {v for r, v in observed if r == latest}
        if len(unique) != 1:
            conflicts.append(field)
        else:
            values[field] = next(iter(unique))
    facts = {field: _fmt(values[field]) for field in FIELDS if field in values}
    if errors:
        verdict, reasons = "UNKNOWN", sorted(errors)
    elif conflicts:
        verdict, reasons = "CONFLICT", ["conflicting_latest:" + f for f in conflicts]
    elif missing:
        verdict, reasons = "UNKNOWN", ["missing:" + f for f in missing]
    elif values["ebitda_usd"] <= 0 or values["net_debt_usd"] < 0 or values["maximum_leverage"] <= 0:
        verdict, reasons = "UNKNOWN", ["outside_synthetic_numeric_domain"]
    else:
        with localcontext() as ctx:
            ctx.prec = 80
            compliant = values["net_debt_usd"] <= values["maximum_leverage"] * values["ebitda_usd"]
        verdict, reasons = ("WITHIN_LIMIT" if compliant else "ABOVE_LIMIT"), []
    return {"verdict": verdict, "facts": facts, "reasons": reasons}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        if not isinstance(request, dict) or set(request) != {"query", "evidence"}:
            raise ValueError("reader input must contain only query and evidence")
        result = read_facts(request["query"], request["evidence"])
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
