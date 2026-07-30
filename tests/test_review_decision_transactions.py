"""Approval-state safety for AI assessments (WO-010-R1 §5).

The defect these tests exist to prevent: rejecting an inbound assessment used
to archive the assessment that was already approved. Declining a bad
submission silently withdrew the good one that was live, and the Dashboard
lost its AI Outlook because someone said "no" to something else.

Every test drives ``scripts/review_decision.main`` through a redirected set of
paths under ``tmp_path``, so nothing here touches the repository's own review
data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.review_decision as decision  # noqa: E402
from analysis.review_package import build_input_package  # noqa: E402
from tests.positive_path import TEST_REGISTRY, manual_notice_evidence  # noqa: E402

PACKAGE_ID = "PKG-20260724-001"


def _current_package(package_id: str = PACKAGE_ID) -> dict:
    """A valid current-publication input package for the approval gate.

    R2 binds an approval to the exact package it was produced from, so these
    transaction tests need a real package on disk rather than an inbound
    assessment alone.
    """
    return build_input_package(
        package_id=package_id,
        generated_at="2026-07-24T00:00:00Z",
        data_cutoff_at="2026-07-24T00:00:00Z",
        source_health={"overall_status": "insufficient", "coverage_message": "x"},
        key_indicators=[],
        lane_status=[],
        events=[],
        evidence=[manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1")],
        previous_assessments=[],
        data_gaps=["no live source"],
        dataset="current_publication",
        source_cutoff="2026-07-24T00:00:00Z",
    )


INBOUND_ASSESSMENT = {
    "package_id": PACKAGE_ID,
    "current_situation": "Coverage is insufficient across every lane.",
    "highest_severity_claimed": "low",
}

EXISTING_APPROVAL = {
    "package_id": PACKAGE_ID,
    "revision_number": 0,
    "approved_at": "2026-07-01T00:00:00Z",
    "reviewer_record": "A. Earlier Reviewer",
    "review_note": "First approval.",
    "human_review_required": False,
    "human_review_status": "approved",
    "supersedes_history_id": None,
    "assessment": {"package_id": PACKAGE_ID, "current_situation": "The original assessment."},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A self-contained review workspace with the module pointed at it."""
    inbound = tmp_path / "inbound"
    approved = tmp_path / "approved"
    archive = tmp_path / "archive"
    for directory in (inbound, approved, archive):
        directory.mkdir()
    history_path = tmp_path / "assessment_history.json"
    history_path.write_text(
        json.dumps(
            {
                "version": "0.8",
                "generated_at": "2026-07-24T00:00:00Z",
                "entries": [
                    {
                        "history_id": "HIST-20260701-aaaaaa",
                        "subject_type": "approved_assessment",
                        "subject_id": PACKAGE_ID,
                        "revision_number": 0,
                        "recorded_at": "2026-07-01T00:00:00Z",
                        "action": "approved",
                        "content_sha256": "0" * 64,
                        "supersedes_history_id": None,
                        "summary": "First approval.",
                        "changed_fields": [],
                        "reviewer_record": "A. Earlier Reviewer",
                        "archive_path": None,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (inbound / f"{PACKAGE_ID}.json").write_text(
        json.dumps(INBOUND_ASSESSMENT, indent=2) + "\n", encoding="utf-8"
    )

    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / f"{PACKAGE_ID}.json").write_text(
        json.dumps(_current_package(), indent=2) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(decision, "INBOUND_DIR", inbound)
    monkeypatch.setattr(decision, "PACKAGE_DIR", packages)
    monkeypatch.setattr(decision, "load_registry", lambda: TEST_REGISTRY)
    monkeypatch.setattr(decision, "APPROVED_DIR", approved)
    monkeypatch.setattr(decision, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(decision, "HISTORY_PATH", history_path)
    monkeypatch.setattr(decision, "ROOT", tmp_path)

    return {
        "root": tmp_path,
        "inbound": inbound,
        "approved": approved,
        "archive": archive,
        "history": history_path,
        "packages": packages,
        "approved_file": approved / f"{PACKAGE_ID}.json",
    }


def _install_existing_approval(workspace):
    workspace["approved_file"].write_text(
        json.dumps(EXISTING_APPROVAL, indent=2) + "\n", encoding="utf-8"
    )
    return workspace["approved_file"].read_bytes()


def _gate(monkeypatch, *, accepted=True, problems=(), needs_review=False):
    monkeypatch.setattr(
        decision, "review", lambda package_id: (accepted, list(problems), needs_review)
    )


def _run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["review_decision.py", *args])
    return decision.main()


def _history(workspace):
    return json.loads(workspace["history"].read_text(encoding="utf-8"))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# 1. Reject with an existing approval preserves it.
# ---------------------------------------------------------------------------


def test_rejecting_a_submission_leaves_the_approved_assessment_byte_for_byte(
    workspace, monkeypatch, capsys
):
    before = _install_existing_approval(workspace)
    _gate(monkeypatch, accepted=False, problems=["schema: something is wrong"])

    code = _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "reject",
        "--reviewer",
        "B. Reviewer",
        "--note",
        "The narrative contains a point forecast.",
    )

    assert code == 0
    assert workspace["approved_file"].read_bytes() == before
    assert list(workspace["archive"].iterdir()) == []
    assert "unchanged" in capsys.readouterr().out


def test_rejecting_records_the_decision_in_history_without_touching_the_approval(
    workspace, monkeypatch
):
    _install_existing_approval(workspace)
    _gate(monkeypatch, accepted=False, problems=["schema: something is wrong"])

    _run(
        monkeypatch, "--package-id", PACKAGE_ID, "--decision", "reject", "--reviewer", "B. Reviewer"
    )

    entries = _history(workspace)["entries"]
    assert entries[-1]["action"] == "rejected"
    assert entries[-1]["subject_type"] == "review_package"
    assert entries[-1]["reviewer_record"] == "B. Reviewer"
    assert entries[-1]["archive_path"] is None
    # The earlier approval entry is untouched and still the latest approval.
    approvals = [entry for entry in entries if entry["action"] == "approved"]
    assert len(approvals) == 1
    assert approvals[0]["history_id"] == "HIST-20260701-aaaaaa"


def test_rejecting_when_nothing_is_approved_withdraws_nothing(workspace, monkeypatch, capsys):
    _gate(monkeypatch, accepted=False, problems=["schema: something is wrong"])

    _run(
        monkeypatch, "--package-id", PACKAGE_ID, "--decision", "reject", "--reviewer", "B. Reviewer"
    )

    assert not workspace["approved_file"].exists()
    assert "none was withdrawn" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. Approve archives the prior version and installs the new one.
# ---------------------------------------------------------------------------


def test_approving_archives_the_previous_version_and_installs_the_new_one(workspace, monkeypatch):
    previous = _install_existing_approval(workspace)
    _gate(monkeypatch)

    code = _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "C. Reviewer",
    )

    assert code == 0
    installed = json.loads(workspace["approved_file"].read_text(encoding="utf-8"))
    assert installed["assessment"] == INBOUND_ASSESSMENT
    assert installed["reviewer_record"] == "C. Reviewer"

    archived = list(workspace["archive"].glob("*.json"))
    assert len(archived) == 1
    assert archived[0].read_bytes() == previous


def test_approving_with_nothing_approved_yet_archives_nothing(workspace, monkeypatch):
    _gate(monkeypatch)

    _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "C. Reviewer",
    )

    assert workspace["approved_file"].exists()
    assert list(workspace["archive"].iterdir()) == []
    assert _history(workspace)["entries"][-1]["archive_path"] is None


# ---------------------------------------------------------------------------
# 3. An invalid approval changes no file.
# ---------------------------------------------------------------------------


def test_an_approval_that_fails_validation_changes_nothing(workspace, monkeypatch, capsys):
    _install_existing_approval(workspace)
    before = _snapshot(workspace["root"])
    _gate(monkeypatch, accepted=False, problems=["rejection rule: unknown evidence reference"])

    code = _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "C. Reviewer",
    )

    assert code == 1
    assert _snapshot(workspace["root"]) == before
    assert "No file was changed." in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. A write failure changes no file.
# ---------------------------------------------------------------------------


def test_a_failure_between_archiving_and_writing_rolls_everything_back(workspace, monkeypatch):
    """Without the transaction this is the state that loses an approval: the
    old file has been archived and the new one was never written."""
    _install_existing_approval(workspace)
    before = _snapshot(workspace["root"])
    _gate(monkeypatch)

    real_write = decision.write_atomic

    def _explode(path, text):
        if path.name.startswith(PACKAGE_ID):
            raise OSError("simulated disk failure")
        return real_write(path, text)

    monkeypatch.setattr(decision, "write_atomic", _explode)

    with pytest.raises(OSError, match="simulated disk failure"):
        _run(
            monkeypatch,
            "--package-id",
            PACKAGE_ID,
            "--decision",
            "approve",
            "--reviewer",
            "C. Reviewer",
        )

    after = _snapshot(workspace["root"])
    assert after == before, "the approved assessment and history must be restored intact"


def test_a_failure_while_writing_history_rolls_back_the_installed_assessment(
    workspace, monkeypatch
):
    _install_existing_approval(workspace)
    before = _snapshot(workspace["root"])
    _gate(monkeypatch)

    real_write = decision.write_atomic

    def _explode(path, text):
        if path.name.startswith("assessment_history"):
            raise OSError("simulated history failure")
        return real_write(path, text)

    monkeypatch.setattr(decision, "write_atomic", _explode)

    with pytest.raises(OSError, match="simulated history failure"):
        _run(
            monkeypatch,
            "--package-id",
            PACKAGE_ID,
            "--decision",
            "approve",
            "--reviewer",
            "C. Reviewer",
        )

    assert _snapshot(workspace["root"]) == before


# ---------------------------------------------------------------------------
# 5. Revision and supersession history are correct.
# ---------------------------------------------------------------------------


def test_each_approval_increments_the_revision_and_names_what_it_supersedes(workspace, monkeypatch):
    _install_existing_approval(workspace)
    _gate(monkeypatch)

    _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "C. Reviewer",
    )
    first = json.loads(workspace["approved_file"].read_text(encoding="utf-8"))
    assert first["revision_number"] == 1
    assert first["supersedes_history_id"] == "HIST-20260701-aaaaaa"

    # A second, different submission for the same package.
    (workspace["inbound"] / f"{PACKAGE_ID}.json").write_text(
        json.dumps({**INBOUND_ASSESSMENT, "current_situation": "Revised."}, indent=2) + "\n",
        encoding="utf-8",
    )
    _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "D. Reviewer",
    )
    second = json.loads(workspace["approved_file"].read_text(encoding="utf-8"))
    assert second["revision_number"] == 2

    entries = _history(workspace)["entries"]
    approvals = [entry for entry in entries if entry["action"] == "approved"]
    assert [entry["revision_number"] for entry in approvals] == [0, 1, 2]
    assert approvals[2]["supersedes_history_id"] == approvals[1]["history_id"]
    assert len(list(workspace["archive"].glob("*.json"))) == 2


# ---------------------------------------------------------------------------
# 6. Repeated decisions do not create duplicate history IDs.
# ---------------------------------------------------------------------------


def test_repeated_decisions_on_the_same_day_get_distinct_history_ids(workspace, monkeypatch):
    """The ID is derived from the date and a content digest, so two decisions
    on the same unchanged payload used to collide and make the audit trail
    ambiguous."""
    _gate(monkeypatch, accepted=False, problems=["schema: something is wrong"])

    for _ in range(3):
        _run(
            monkeypatch,
            "--package-id",
            PACKAGE_ID,
            "--decision",
            "reject",
            "--reviewer",
            "B. Reviewer",
        )

    ids = [entry["history_id"] for entry in _history(workspace)["entries"]]
    assert len(ids) == len(set(ids)) == 4


def test_an_approval_and_a_rejection_of_the_same_payload_do_not_collide(workspace, monkeypatch):
    _gate(monkeypatch, accepted=False, problems=["schema: something is wrong"])
    _run(
        monkeypatch, "--package-id", PACKAGE_ID, "--decision", "reject", "--reviewer", "B. Reviewer"
    )
    _gate(monkeypatch)
    _run(
        monkeypatch,
        "--package-id",
        PACKAGE_ID,
        "--decision",
        "approve",
        "--reviewer",
        "C. Reviewer",
    )

    ids = [entry["history_id"] for entry in _history(workspace)["entries"]]
    assert len(ids) == len(set(ids)) == 3
