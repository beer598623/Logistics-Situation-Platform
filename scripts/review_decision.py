#!/usr/bin/env python3
"""Record an explicit human decision on a returned ChatGPT assessment.

This is the only path by which an AI assessment can reach the Dashboard, and
it requires a human to run it and to name themselves.

The two decisions are deliberately asymmetric, which is the WO-010-R1
correction:

**Reject** touches nothing but the history. A rejection is a statement about
the *inbound* assessment; it says nothing about the assessment already
approved. Previously a rejection archived the approved assessment, which meant
declining a bad submission silently withdrew the good one that was live -- the
Dashboard would lose its AI Outlook because someone said "no" to something
else.

**Approve** re-runs every gate, archives the assessment it supersedes, and
installs the new one. Only after the new assessment passes.

Both are transactional. Every file this script may touch is captured before
any change and restored if anything raises, so a failure part-way through
leaves the repository exactly as it was rather than half-updated.

Usage::

    python scripts/review_decision.py --package-id PKG-20260724-001 \\
        --decision approve --reviewer 'A. Reviewer' [--note '...']
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections.abc import Iterable
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


class FileTransaction:
    """All-or-nothing writes across a fixed set of paths.

    Captures each path's current bytes (or its absence) on entry, and restores
    every one of them if the body raises. Without this, an exception between
    archiving the old assessment and writing the new one would leave the
    repository with neither.
    """

    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths = list(paths)
        self._snapshot: dict[Path, bytes | None] = {}

    def __enter__(self) -> FileTransaction:
        for path in self._paths:
            self._snapshot[path] = path.read_bytes() if path.exists() else None
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            return False
        self.rollback()
        return False

    def rollback(self) -> None:
        for path, original in self._snapshot.items():
            if original is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)

    def track(self, path: Path) -> None:
        """Bring a path that was not known up front under the transaction."""
        if path not in self._snapshot:
            self._snapshot[path] = path.read_bytes() if path.exists() else None
            self._paths.append(path)


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then rename.

    A rename within a directory is atomic, so a reader never observes a
    partially written approved assessment.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def load_history() -> dict[str, Any]:
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def next_revision(history: dict[str, Any], package_id: str) -> int:
    """One past the highest approved revision recorded for this package."""
    revisions = [
        int(entry.get("revision_number", 0))
        for entry in history["entries"]
        if entry.get("subject_id") == package_id and entry.get("action") == "approved"
    ]
    return max(revisions) + 1 if revisions else 0


def latest_approval_history_id(history: dict[str, Any], package_id: str) -> str | None:
    """The history entry a new approval supersedes, if any."""
    approvals = [
        entry
        for entry in history["entries"]
        if entry.get("subject_id") == package_id and entry.get("action") == "approved"
    ]
    return approvals[-1]["history_id"] if approvals else None


def unique_history_id(history: dict[str, Any], base: str) -> str:
    """A history ID that does not collide with an existing one.

    Two decisions on the same package on the same day used to produce the same
    ID, which silently made the audit trail ambiguous.
    """
    existing = {entry["history_id"] for entry in history["entries"]}
    if base not in existing:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def archive_target(package_id: str, timestamp: str) -> Path:
    """A free archive path for this package at this timestamp.

    The timestamp alone is not enough. Two approvals of the same package
    within the same second produced the same name, and the second move
    silently overwrote the first archived version -- losing exactly the
    history the archive exists to keep.
    """
    stamp = timestamp.replace(":", "").replace("-", "")
    base = ARCHIVE_DIR / f"{package_id}-superseded-{stamp}.json"
    if not base.exists():
        return base
    suffix = 2
    while (candidate := base.with_name(f"{base.stem}-{suffix}.json")).exists():
        suffix += 1
    return candidate


def archive_existing(package_id: str, timestamp: str, transaction: FileTransaction) -> str | None:
    """Move the currently approved assessment into the archive.

    Called only on the approve path, and only after the incoming assessment
    has passed every gate. The destination joins the transaction *before* the
    move, so its pre-move state -- non-existence -- is what a rollback
    restores. Tracking it afterwards would snapshot the archived copy and
    leave it behind on failure.
    """
    current = APPROVED_DIR / f"{package_id}.json"
    if not current.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = archive_target(package_id, timestamp)
    transaction.track(target)
    shutil.move(str(current), str(target))
    return str(target.relative_to(ROOT))


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
        print("\nNo file was changed.")
        return 1

    timestamp = _now()
    output = json.loads((INBOUND_DIR / f"{args.package_id}.json").read_text(encoding="utf-8"))
    approved_path = APPROVED_DIR / f"{args.package_id}.json"
    history = load_history()

    tracked = [HISTORY_PATH, approved_path]
    with FileTransaction(tracked) as transaction:
        archived: str | None = None
        revision = 0
        supersedes: str | None = None

        if args.decision == "approve":
            revision = next_revision(history, args.package_id)
            supersedes = latest_approval_history_id(history, args.package_id)
            archived = archive_existing(args.package_id, timestamp, transaction)
            write_atomic(
                approved_path,
                json.dumps(
                    {
                        "package_id": args.package_id,
                        "revision_number": revision,
                        "approved_at": timestamp,
                        "reviewer_record": args.reviewer,
                        "review_note": args.note,
                        "human_review_required": needs_review,
                        "human_review_status": "approved",
                        "supersedes_history_id": supersedes,
                        "assessment": output,
                    },
                    indent=2,
                )
                + "\n",
            )
            summary = (
                f"Approved AI assessment {args.package_id} revision {revision} "
                f"(highest severity claimed: {output.get('highest_severity_claimed')})."
            )
        else:
            # A rejection is a statement about the inbound assessment. It must
            # not disturb whatever is currently approved, so nothing here
            # touches the approved file or the archive.
            summary = f"Rejected inbound AI assessment {args.package_id}. {args.note}".strip()
            if problems:
                summary += f" Validation problems: {len(problems)}."

        history["entries"].append(
            {
                "history_id": unique_history_id(
                    history,
                    f"HIST-{timestamp[:10].replace('-', '')}-{_digest(output)[:6]}",
                ),
                "subject_type": (
                    "approved_assessment" if args.decision == "approve" else "review_package"
                ),
                "subject_id": args.package_id,
                "revision_number": revision,
                "recorded_at": timestamp,
                "action": "approved" if args.decision == "approve" else "rejected",
                "content_sha256": _digest(output),
                "supersedes_history_id": supersedes,
                "summary": summary,
                "changed_fields": [],
                "reviewer_record": args.reviewer,
                "archive_path": archived,
            }
        )
        write_atomic(HISTORY_PATH, json.dumps(history, indent=2) + "\n")

    print(
        f"[{args.decision.upper()}] {args.package_id} recorded by {args.reviewer} at {timestamp}."
    )
    if args.decision == "approve":
        print(f"Revision {revision} installed at {approved_path.relative_to(ROOT)}.")
        if archived:
            print(f"Previous approved assessment archived to {archived}.")
        print("Run python scripts/build_dashboard.py to publish the approved assessment.")
    else:
        if approved_path.exists():
            print(
                f"The currently approved assessment at {approved_path.relative_to(ROOT)} is "
                "unchanged. Rejecting a submission does not withdraw an existing approval."
            )
        else:
            print("No assessment is currently approved; none was withdrawn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
