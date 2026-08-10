#!/usr/bin/env python3
"""Compute mode_situation records (WO-049 / Issue #92 item 5).

Reads the version-controlled events, evidence, documents, claims and source
registry; computes one ``mode_situation`` record per configured
``(mode, geography)`` pair via ``analysis/situations.py::compute_mode_situation``;
writes ``data/situations/situations.json`` in the existing ``data/events/``-
style single-combined-file layout.

Deliberately pinned to a fixed ``DATA_CUTOFF`` rather than the wall clock --
the same discipline ``scripts/build_analysis.py`` and
``scripts/build_dashboard.py`` already use -- so the committed output is
reproducible byte-for-byte. This script does not touch ``dashboard/public/**``
or any file ``scripts/build_dashboard.py`` writes; ``mode_situation`` is
computed and validated here, not rendered.

Usage::

    python scripts/build_situations.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from analysis.situations import compute_mode_situation  # noqa: E402

#: Matches scripts/build_analysis.py / scripts/build_dashboard.py's own
#: pinned cutoff, so a mode_situation computed in the same build shares
#: exactly the as-of time the rest of the current-publication surface does.
DATA_CUTOFF = datetime(2026, 7, 24, tzinfo=UTC)

SITUATIONS_PATH = ROOT / "data" / "situations" / "situations.json"

#: The one (mode, geography) pair this Work Order's pilot computes.
#: Additional pairs are a later Work Order's concern -- Land/Air/Rail modes
#: have no Document/Claim evidence plane yet.
_SITUATION_TARGETS = [
    {"mode": "sea", "geography_id": "GEO-CTY-TH", "country_code": "TH"},
]


def _load(path: Path, key: str) -> list:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get(key, [])


def build_situations(*, as_of: datetime = DATA_CUTOFF) -> dict:
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    events = _load(ROOT / "data/events/events.json", "events")
    evidence = _load(ROOT / "data/events/event_evidence.json", "evidence")
    documents = _load(ROOT / "data/documents/documents.json", "documents")
    claims = _load(ROOT / "data/claims/claims.json", "claims")

    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    documents_by_id = {item["document_id"]: item for item in documents}
    claims_by_id = {item["claim_id"]: item for item in claims}

    situations = [
        compute_mode_situation(
            mode=target["mode"],
            geography_id=target["geography_id"],
            country_code=target["country_code"],
            events=events,
            evidence_by_id=evidence_by_id,
            claims_by_id=claims_by_id,
            documents_by_id=documents_by_id,
            registry=registry,
            as_of=as_of,
        )
        for target in _SITUATION_TARGETS
    ]
    return {"situations": situations}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without writing.")
    args = parser.parse_args()

    payload = build_situations()
    serialized = json.dumps(payload, indent=2) + "\n"

    if args.check:
        if not SITUATIONS_PATH.exists():
            print(f"[FAIL] {SITUATIONS_PATH} does not exist.")
            return 1
        current = SITUATIONS_PATH.read_text(encoding="utf-8")
        if current != serialized:
            print(f"[FAIL] {SITUATIONS_PATH} is stale; run scripts/build_situations.py to refresh.")
            return 1
        print(f"[PASS] {SITUATIONS_PATH} is up to date ({len(payload['situations'])} record(s)).")
        return 0

    SITUATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITUATIONS_PATH.write_text(serialized, encoding="utf-8")
    print(f"Wrote {SITUATIONS_PATH.relative_to(ROOT)} ({len(payload['situations'])} record(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
