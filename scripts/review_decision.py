#!/usr/bin/env python3
"""Record an explicit human decision on a returned ChatGPT assessment.

This is the only path by which an AI assessment can reach the Dashboard, and
it requires a human to run it and to name themselves. The script:

* re-runs the import gates, so an assessment cannot be approved on the
  strength of a validation that happened before the file was last edited;
* archives whatever assessment it supersedes, so a prior view is preserved
  rather than silently rewritten;
* appends an entry to the assessment history;
* writes the approved assessment only on an approve decision.

A rejection is recorded just as durably as an approval. The record of what was
rejected, and why, is part of the audit trail.

Usage::

    python scripts/review_decision.py --package-id PKG-20260724-001 \\
        --decision approve --reviewer 'A. Reviewer' [--note '...']
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.import_review import review  # noqa: E402

INBOUND_DIR = ROOT / "data" / "review" / "inbound"
APPROVED_DIR = ROOT / "data" / "assessments" / "approved"
ARCHIVE_DIR = ROOT / "data" / "assessments" / "archive"
HISTORY_PATH = ROOT / "data" / "assessments" / "assessment_history.json"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def archive_existing(package_id: str, timestamp: str) -> str | None:
    """Move any currently approved assessment for this package into the archive."""
    current = APPROVED_DIR / f"{package_id}.json"
    if not current.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.replace(":", "").replace("-", "")
    target = ARCHIVE_DIR / f"{package_id}-superseded-{stamp}.json"
    shutil.move(str(current), str(target))
    return str(target.relative_to(ROOT))


def append_history(entry: dict[str, Any]) -> None:
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    history["entries"].append(entry)
    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--decision", required=True, choices=["approve", "reject"])
    parser.add_argument(
        "--reviewer",
        required=True,
        help="The human accountable for this decision. Recorded verbatim in the history.",
    )
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    accepted, problems, needs_review = review(args.package_id)

    if args.decision == "approve" and not accepted:
        print(f"[BLOCKED] Cannot approve {args.package_id}: it fails validation.")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    timestamp = _now()
    output = json.loads((INBOUND_DIR / f"{args.package_id}.json").read_text(encoding="utf-8"))
    archived = archive_existing(args.package_id, timestamp)

    if args.decision == "approve":
        APPROVED_DIR.mkdir(parents=True, exist_ok=True)
        approved = {
            "package_id": args.package_id,
            "approved_at": timestamp,
            "reviewer_record": args.reviewer,
            "review_note": args.note,
            "human_review_required": needs_review,
            "human_review_status": "approved",
            "assessment": output,
        }
        (APPROVED_DIR / f"{args.package_id}.json").write_text(
            json.dumps(approved, indent=2) + "\n", encoding="utf-8"
        )
        summary = (
            f"Approved AI assessment {args.package_id} "
            f"(highest severity claimed: {output.get('highest_severity_claimed')})."
        )
    else:
        summary = f"Rejected AI assessment {args.package_id}. {args.note}".strip()

    append_history(
        {
            "history_id": f"HIST-{timestamp[:10].replace('-', '')}-{_digest(output)[:6]}",
            "subject_type": "approved_assessment"
            if args.decision == "approve"
            else "review_package",
            "subject_id": args.package_id,
            "revision_number": 0,
            "recorded_at": timestamp,
            "action": "approved" if args.decision == "approve" else "rejected",
            "content_sha256": _digest(output),
            "supersedes_history_id": None,
            "summary": summary,
            "changed_fields": [],
            "reviewer_record": args.reviewer,
            "archive_path": archived,
        }
    )

    print(
        f"[{args.decision.upper()}] {args.package_id} recorded by {args.reviewer} at {timestamp}."
    )
    if archived:
        print(f"Previous approved assessment archived to {archived}.")
    if args.decision == "approve":
        print("Run python scripts/build_dashboard.py to publish the approved assessment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
