from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

from .ledger import canonical_hash


@dataclass(frozen=True)
class RadarDailySnapshot:
    signal_date: str
    leaders_v1: dict[str, float]
    challengers_v2: dict[str, float]
    challengers_v3: dict[str, float]
    migration_risers: dict[str, float]
    migration_fallers: dict[str, float]
    risk_line: dict[str, float]
    risk_percentiles: dict[str, float]
    regime: str | None
    bundle_root_sha256: str | None
    source_ref: str
    source_blob_sha: str | None = None
    source_commit_sha: str | None = None

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(
            {
                "signal_date": self.signal_date,
                "leaders_v1": self.leaders_v1,
                "challengers_v2": self.challengers_v2,
                "challengers_v3": self.challengers_v3,
                "migration_risers": self.migration_risers,
                "migration_fallers": self.migration_fallers,
                "risk_line": self.risk_line,
                "risk_percentiles": self.risk_percentiles,
                "regime": self.regime,
                "bundle_root_sha256": self.bundle_root_sha256,
                "source_ref": self.source_ref,
                "source_blob_sha": self.source_blob_sha,
                "source_commit_sha": self.source_commit_sha,
            }
        )


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _pairs_from_line(line: str) -> dict[str, float]:
    pairs: dict[str, float] = {}
    pattern = r"([A-Za-z0-9_\-]+)\s*\((-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\)"
    for name, value in re.findall(pattern, line):
        pairs[name] = float(value)
    return pairs


def _bullet_pairs(block: str, *, strip_axis: bool = False) -> dict[str, float]:
    output: dict[str, float] = {}
    pattern = (
        r"\s*-\s+(?:\*\*)?([A-Za-z0-9_\-]+)(?:\*\*)?\s*[:(]\s*"
        r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\)?"
    )
    for line in block.splitlines():
        match = re.match(pattern, line)
        if not match:
            continue
        name = match.group(1)
        if strip_axis and name.startswith("axis_"):
            name = name[5:]
        output[name] = float(match.group(2))
    return output


def parse_radar_daily_markdown(
    text: str,
    *,
    source_ref: str,
    source_blob_sha: str | None = None,
    source_commit_sha: str | None = None,
) -> RadarDailySnapshot:
    date_match = re.search(r"Theme Radar Daily Brief\s*[—-]\s*(\d{4}-\d{2}-\d{2})", text)
    if not date_match:
        raise ValueError("Radar log is missing the expected Daily Brief date")
    signal_date = date_match.group(1)
    date.fromisoformat(signal_date)

    leaders = _bullet_pairs(_section(text, "Leaders (v1) — W=63"))

    challengers_block = _section(text, "Challengers — W=63")
    v2: dict[str, float] = {}
    v3: dict[str, float] = {}
    for line in challengers_block.splitlines():
        if "v2:" in line.lower():
            v2 = _pairs_from_line(line)
        elif "v3:" in line.lower():
            v3 = _pairs_from_line(line)

    migration_block = _section(text, "Migration (20D slope) — W=63")
    risers_text = migration_block
    fallers_text = ""
    if "**Top fallers:**" in migration_block:
        risers_text, fallers_text = migration_block.split("**Top fallers:**", 1)
    if "**Top risers:**" in risers_text:
        risers_text = risers_text.split("**Top risers:**", 1)[1]
    risers = _bullet_pairs(risers_text, strip_axis=True)
    fallers = _bullet_pairs(fallers_text, strip_axis=True)

    risk = _bullet_pairs(_section(text, "Risk line (W=63)"))

    regime_match = re.search(r"\*\*Regime:\*\*\s*`([^`]+)`", text)
    regime = regime_match.group(1) if regime_match else None

    percentiles: dict[str, float] = {}
    pct_match = re.search(r"Percentiles \(W=63 history\):\s*([^\n]+)", text)
    if pct_match:
        for name, value in re.findall(
            r"([A-Za-z0-9_]+)=(-?\d+(?:\.\d+)?)", pct_match.group(1)
        ):
            percentiles[name] = float(value)

    bundle_match = re.search(r"BUNDLE_ROOT_SHA256:\*\*\s*`([0-9a-fA-F]{64})`", text)
    bundle = bundle_match.group(1).lower() if bundle_match else None

    if not leaders or not risers or not risk:
        raise ValueError("Radar log parsed incompletely; refuse silent partial ingestion")

    return RadarDailySnapshot(
        signal_date=signal_date,
        leaders_v1=leaders,
        challengers_v2=v2,
        challengers_v3=v3,
        migration_risers=risers,
        migration_fallers=fallers,
        risk_line=risk,
        risk_percentiles=percentiles,
        regime=regime,
        bundle_root_sha256=bundle,
        source_ref=source_ref,
        source_blob_sha=source_blob_sha,
        source_commit_sha=source_commit_sha,
    )


class GitHubRadarClient:
    """Minimal read-only client for a separate/private Radar repository.

    Authentication comes only from an environment variable. No token is persisted
    into Decision Lab output. For cross-repository private reads, use a fine-grained
    token with read-only Contents access to the Radar repository.
    """

    def __init__(
        self,
        repository: str = "yuhanyu0/theme-radar-log",
        *,
        token_env: str = "RADAR_REPO_TOKEN",
    ) -> None:
        self.repository = repository
        self.token = os.environ.get(token_env)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "theme-radar-decision-lab",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub read failed: HTTP {exc.code} for {url}") from exc

    def fetch_daily(self, signal_date: str, *, ref: str = "main") -> RadarDailySnapshot:
        date.fromisoformat(signal_date)
        path = f"logs/{signal_date}.md"
        content_url = f"https://api.github.com/repos/{self.repository}/contents/{path}?ref={ref}"
        payload = self._json(content_url)
        download_url = payload.get("download_url")
        if not download_url:
            raise RuntimeError(f"Radar file {path} has no downloadable text URL")

        request = urllib.request.Request(download_url, headers=self._headers())
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")

        commits_url = (
            f"https://api.github.com/repos/{self.repository}/commits?path={path}&per_page=1"
        )
        commits = self._json(commits_url)
        commit_sha = commits[0]["sha"] if isinstance(commits, list) and commits else None
        return parse_radar_daily_markdown(
            text,
            source_ref=f"github:{self.repository}:{path}@{ref}",
            source_blob_sha=payload.get("sha"),
            source_commit_sha=commit_sha,
        )
