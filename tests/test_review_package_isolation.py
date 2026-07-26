"""Review-package isolation and approval binding (WO-010-R2 §2, §3, §8, §9).

WO-010 built one combined review package: every record the repository held,
handed to ChatGPT alongside a request for a current assessment. A synthetic
freight series and a 2021 canal closure travelled in the same payload as the
question "what is the situation now", and nothing on the way back could tell
which was which.

R2 makes the current package a filtered artifact and binds any approval to the
exact package it was produced from. These tests cover both halves: what the
default package contains, and what the approval gate refuses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_review_package as builder  # noqa: E402
import scripts.review_decision as decision  # noqa: E402
from analysis.provenance import (  # noqa: E402
    CURRENT_PUBLICATION,
    HISTORICAL_VALIDATION,
    TECHNICAL_DEMO,
)
from analysis.review_package import (  # noqa: E402
    CURRENT_INTELLIGENCE,
    ENGINE_DEMONSTRATION,
    build_input_package,
    has_operational_condition_evidence,
    package_hash,
    package_provenance_problems,
    requires_human_review,
    validate_output,
)
from tests.positive_path import TEST_REGISTRY, manual_notice_evidence  # noqa: E402

PACKAGE_ID = "PKG-20260724-001"


# ---------------------------------------------------------------------------
# §2 What the default package contains
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def current_package():
    return builder.build(PACKAGE_ID)


@pytest.fixture(scope="module")
def demo_package():
    return builder.build(PACKAGE_ID, surface=TECHNICAL_DEMO)


def test_the_default_surface_is_the_current_view(current_package):
    assert current_package["dataset"] == CURRENT_PUBLICATION
    assert current_package["package_purpose"] == CURRENT_INTELLIGENCE


def test_the_current_package_carries_no_fixture_or_historical_record(current_package):
    for item in current_package["evidence_records"]:
        assert item["evidence_origin"] in {"live_retrieved", "human_reviewed_manual"}
        assert item["dataset"] == CURRENT_PUBLICATION
    for group in ("active_operational_events", "external_drivers"):
        for event in current_package[group]:
            assert event["dataset"] == CURRENT_PUBLICATION
    for indicator in current_package["key_indicators"]:
        assert indicator["dataset"] == CURRENT_PUBLICATION


def test_with_zero_qualified_evidence_the_current_package_is_empty(current_package):
    """Empty by filtering. The repository holds 90 cost observations, 8 events
    and 10 evidence items; none of them qualifies, so none of them travels."""
    assert current_package["key_indicators"] == []
    assert current_package["active_operational_events"] == []
    assert current_package["external_drivers"] == []
    assert current_package["evidence_records"] == []


def test_every_lane_in_the_current_package_is_insufficient(current_package):
    lanes = current_package["lane_status"]
    assert len(lanes) == 11
    for lane in lanes:
        assert lane["attention_level"] == "insufficient_evidence"
        assert lane["overall_direction"] == "insufficient_evidence"
        assert lane["data_gaps"]


def test_the_empty_package_says_no_current_conclusion_can_be_drawn(current_package):
    gaps = " ".join(current_package["data_gaps"])
    assert "No current directional conclusion can be produced" in gaps
    assert "coverage gap and not a finding that conditions are normal" in gaps


def test_the_package_records_what_it_excluded(current_package):
    summary = current_package["provenance_summary"]
    assert summary["excluded_fixture_record_count"] > 0
    assert summary["evidence"]["record_count"] == 0
    assert summary["events"]["record_count"] == 0


def test_the_package_records_its_cutoffs_and_hash(current_package):
    # WO-010-R6 §6: zero acquisition-bound evidence means source_cutoff is
    # honestly null, never silently replaced with data_cutoff_at/as_of_time.
    assert current_package["source_cutoff"] is None
    assert current_package["data_cutoff_at"]
    assert len(current_package["package_sha256"]) == 64


def test_the_package_hash_covers_its_contents(current_package):
    assert package_hash(current_package) == current_package["package_sha256"]
    tampered = {
        **current_package,
        "data_gaps": [*current_package["data_gaps"], "an added line"],
    }
    assert package_hash(tampered) != current_package["package_sha256"]


def test_the_demonstration_surface_is_a_separate_artifact(demo_package):
    assert demo_package["dataset"] == TECHNICAL_DEMO
    assert demo_package["package_purpose"] == ENGINE_DEMONSTRATION
    # It still contains the fixtures -- that is what it is for.
    assert demo_package["evidence_records"]
    assert demo_package["key_indicators"]


def test_the_two_surfaces_do_not_share_contents(current_package, demo_package):
    current_ids = {item["evidence_id"] for item in current_package["evidence_records"]}
    demo_ids = {item["evidence_id"] for item in demo_package["evidence_records"]}
    assert current_ids & demo_ids == set()


# ---------------------------------------------------------------------------
# §8 The validator inspects provenance, not only ID existence
# ---------------------------------------------------------------------------


def _package(**overrides):
    kwargs = {
        "package_id": PACKAGE_ID,
        "generated_at": "2026-07-24T00:00:00Z",
        "data_cutoff_at": "2026-07-24T00:00:00Z",
        "source_health": {"overall_status": "insufficient", "coverage_message": "x"},
        "key_indicators": [],
        "lane_status": [],
        "events": [],
        "evidence": [manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1")],
        "previous_assessments": [],
        "data_gaps": [],
        "dataset": CURRENT_PUBLICATION,
        "source_cutoff": "2026-07-24T00:00:00Z",
    }
    kwargs.update(overrides)
    return build_input_package(**kwargs)


def _output(*, package=None, **overrides):
    """An output pre-bound to ``package`` (or a fresh default ``_package()``).

    Binding it by default, rather than leaving the five ``input_*`` fields
    absent, means a test only has to override what it is actually testing --
    a mismatched hash, a stale cutoff -- instead of restating every binding
    field by hand to get past ``binding_problems`` first.
    """
    bound_to = package if package is not None else _package()
    out = {
        "package_id": PACKAGE_ID,
        "methodology_version": "0.8",
        "produced_at": "2026-07-24T01:00:00Z",
        "model_reference": "human-run ChatGPT session",
        "input_package_sha256": bound_to["package_sha256"],
        "input_dataset": bound_to["dataset"],
        "input_package_purpose": bound_to["package_purpose"],
        "input_data_cutoff_at": bound_to["data_cutoff_at"],
        "input_source_cutoff": bound_to["source_cutoff"],
        "current_situation": {
            "current_direction": "insufficient_evidence",
            "current_disposition": "insufficient_evidence",
            "evidence_ids": [],
            "indicator_ids": [],
            "statement": "Coverage is insufficient.",
        },
        "key_changes": [],
        "lane_assessments": [],
        "verified_facts": [],
        "reported_claims": [],
        "analytical_inference": [],
        "conflicting_evidence": [],
        "transmission_chains": [],
        "observed_impacts": [],
        "potential_impacts": [],
        "scenarios": [],
        "evidence_references": [],
        "data_gaps": [],
        "conditional_preparedness_options": [],
        "highest_severity_claimed": "none",
    }
    out.update(overrides)
    return out


def test_a_fixture_evidence_item_in_a_current_package_is_rejected():
    package = _package(
        evidence=[
            manual_notice_evidence(
                evidence_id="EVD-1",
                dataset=HISTORICAL_VALIDATION,
                evidence_origin="historical_validation_fixture",
            )
        ]
    )
    problems = package_provenance_problems(package, registry=TEST_REGISTRY)
    assert any("is present in a current-intelligence package" in item for item in problems)


def test_a_not_retrieved_item_without_human_review_cannot_be_a_current_fact():
    package = _package(
        evidence=[
            manual_notice_evidence(
                evidence_id="EVD-1",
                evidence_origin="live_retrieved",
                retrieval_status="not_retrieved",
            )
        ]
    )
    problems = package_provenance_problems(package, registry=TEST_REGISTRY)
    assert any("cannot be used as a verified current fact" in item for item in problems)


def test_a_package_whose_dataset_and_purpose_disagree_is_rejected():
    package = {**_package(), "package_purpose": ENGINE_DEMONSTRATION}
    problems = package_provenance_problems(package, registry=TEST_REGISTRY)
    assert any("disagree" in item for item in problems)


def test_citing_evidence_excluded_from_the_current_package_is_rejected():
    """The ID exists in the package. That was the whole check before R2."""
    package = _package(
        evidence=[
            manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1"),
            manual_notice_evidence(
                evidence_id="EVD-OLD",
                dataset=HISTORICAL_VALIDATION,
                evidence_origin="historical_validation_fixture",
            ),
        ]
    )
    output = _output(
        evidence_references=["EVD-OLD"],
        verified_facts=[{"statement": "A notice was published.", "evidence_ids": ["EVD-OLD"]}],
    )
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("cannot support a current claim" in item for item in problems)


def test_a_severity_claim_without_eligible_evidence_is_rejected():
    package = _package(evidence=[])
    output = _output(highest_severity_claimed="high")
    problems = validate_output(output, package, registry=TEST_REGISTRY)
    assert any("no evidence eligible to support a current conclusion" in item for item in problems)


def test_an_operational_condition_claim_needs_eligible_current_evidence():
    """A historical notice is still a notice. It is not a notice about now."""
    historical = _package(
        evidence=[
            {
                **manual_notice_evidence(
                    evidence_id="EVD-1",
                    dataset=HISTORICAL_VALIDATION,
                    evidence_origin="historical_validation_fixture",
                ),
                "scope_supported": "node",
            }
        ]
    )
    assert has_operational_condition_evidence(historical, registry=TEST_REGISTRY) is False

    current = _package(
        evidence=[{**manual_notice_evidence(evidence_id="EVD-1"), "scope_supported": "node"}]
    )
    assert has_operational_condition_evidence(current, registry=TEST_REGISTRY) is True


# ---------------------------------------------------------------------------
# §3 / §9 The approval gate, with the transaction intact
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    inbound = tmp_path / "inbound"
    approved = tmp_path / "approved"
    archive = tmp_path / "archive"
    packages = tmp_path / "packages"
    for directory in (inbound, approved, archive, packages):
        directory.mkdir()
    history = tmp_path / "assessment_history.json"
    history.write_text(
        json.dumps({"version": "0.8", "generated_at": "2026-07-24T00:00:00Z", "entries": []})
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(decision, "INBOUND_DIR", inbound)
    monkeypatch.setattr(decision, "PACKAGE_DIR", packages)
    monkeypatch.setattr(decision, "APPROVED_DIR", approved)
    monkeypatch.setattr(decision, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(decision, "HISTORY_PATH", history)
    monkeypatch.setattr(decision, "ROOT", tmp_path)
    monkeypatch.setattr(decision, "load_registry", lambda: TEST_REGISTRY)

    def _review(package_id):
        """Stand in for ``scripts.import_review.review`` against ``TEST_REGISTRY``.

        The real ``review()`` loads its own registry straight from
        ``config/sources.yaml``, which knows nothing about the fictitious
        sources these tests use, so it cannot be called as-is here. This
        mirrors its second gate -- ``validate_output`` -- against the test
        registry instead, and skips the first (JSON Schema) gate, which these
        deliberately minimal fixtures were never meant to satisfy.
        """
        package = json.loads((packages / f"{package_id}.json").read_text(encoding="utf-8"))
        output = json.loads((inbound / f"{package_id}.json").read_text(encoding="utf-8"))
        problems = validate_output(output, package, registry=TEST_REGISTRY)
        return not problems, problems, requires_human_review(output)

    monkeypatch.setattr(decision, "review", _review)

    return {
        "root": tmp_path,
        "inbound": inbound,
        "packages": packages,
        "approved": approved,
        "archive": archive,
        "history": history,
        "approved_file": approved / f"{PACKAGE_ID}.json",
    }


def _install(workspace, package, output):
    (workspace["packages"] / f"{PACKAGE_ID}.json").write_text(
        json.dumps(package, indent=2) + "\n", encoding="utf-8"
    )
    (workspace["inbound"] / f"{PACKAGE_ID}.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _approve(monkeypatch, reviewer="C. Reviewer"):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_decision.py",
            "--package-id",
            PACKAGE_ID,
            "--decision",
            "approve",
            "--reviewer",
            reviewer,
        ],
    )
    return decision.main()


def test_a_valid_current_package_can_be_approved(workspace, monkeypatch):
    _install(workspace, _package(), _output())
    assert _approve(monkeypatch) == 0

    record = json.loads(workspace["approved_file"].read_text(encoding="utf-8"))
    assert record["input_dataset"] == CURRENT_PUBLICATION
    assert record["input_package_purpose"] == CURRENT_INTELLIGENCE
    assert record["input_package_sha256"] == _package()["package_sha256"]
    assert record["input_evidence_ids"] == ["EVD-1"]
    assert record["input_evidence_origin_summary"] == {"human_reviewed_manual": 1}
    assert record["validation_status"] == "passed"
    assert record["superseded"] is False
    assert record["output_sha256"]
    assert record["input_source_cutoff"] == "2026-07-24T00:00:00Z"
    assert record["input_data_cutoff_at"] == "2026-07-24T00:00:00Z"


def test_a_demonstration_package_cannot_be_approved_as_current(workspace, monkeypatch, capsys):
    """The reviewer typed `approve`. That is not enough."""
    _install(workspace, builder.build(PACKAGE_ID, surface=TECHNICAL_DEMO), _output())
    before = _snapshot(workspace["root"])

    assert _approve(monkeypatch) == 1

    out = capsys.readouterr().out
    assert "only a 'current_publication' package may be approved" in out
    assert "No file was changed." in out
    assert _snapshot(workspace["root"]) == before
    assert not workspace["approved_file"].exists()


def test_a_package_edited_after_generation_cannot_be_approved(workspace, monkeypatch, capsys):
    package = _package()
    package["data_gaps"] = ["someone added a line after the hash was taken"]
    _install(workspace, package, _output())
    before = _snapshot(workspace["root"])

    assert _approve(monkeypatch) == 1
    assert "has changed since it was generated" in capsys.readouterr().out
    assert _snapshot(workspace["root"]) == before


def test_an_assessment_produced_against_another_package_version_is_refused(
    workspace, monkeypatch, capsys
):
    package = _package()
    _install(workspace, package, _output(package=package, input_package_sha256="d" * 64))
    assert _approve(monkeypatch) == 1
    assert "does not match the input package's package_sha256" in capsys.readouterr().out


def test_a_different_data_cutoff_requires_an_explicit_supersession(workspace, monkeypatch, capsys):
    package = _package()
    _install(
        workspace,
        package,
        _output(package=package, input_data_cutoff_at="2026-06-01T00:00:00Z"),
    )
    assert _approve(monkeypatch) == 1
    assert "does not match the input package's data_cutoff_at" in capsys.readouterr().out


def test_an_output_citing_fixture_evidence_cannot_be_approved(workspace, monkeypatch, capsys):
    package = _package(
        evidence=[
            manual_notice_evidence(evidence_id="EVD-1", event_id="EVT-1"),
            manual_notice_evidence(
                evidence_id="EVD-OLD",
                dataset=HISTORICAL_VALIDATION,
                evidence_origin="historical_validation_fixture",
            ),
        ]
    )
    _install(workspace, package, _output(package=package, evidence_references=["EVD-OLD"]))
    before = _snapshot(workspace["root"])

    assert _approve(monkeypatch) == 1
    assert "excluded from this current package's citable set" in capsys.readouterr().out
    assert _snapshot(workspace["root"]) == before


def test_current_claims_with_zero_qualified_evidence_cannot_be_approved(
    workspace, monkeypatch, capsys
):
    package = _package(evidence=[])
    _install(
        workspace,
        package,
        _output(
            package=package,
            highest_severity_claimed="moderate",
            verified_facts=[{"statement": "Congestion is elevated.", "evidence_ids": []}],
        ),
    )
    out_code = _approve(monkeypatch)
    printed = capsys.readouterr().out
    assert out_code == 1
    assert "the package holds no eligible evidence or indicator" in printed
    assert "verified_facts" in printed


def test_a_blocked_approval_leaves_an_existing_approval_untouched(workspace, monkeypatch):
    """§9: the R1 transaction guarantee still holds when the *new* reason for
    blocking is provenance rather than a rejection rule."""
    _install(workspace, _package(), _output())
    assert _approve(monkeypatch) == 0
    good = workspace["approved_file"].read_bytes()

    _install(workspace, builder.build(PACKAGE_ID, surface=TECHNICAL_DEMO), _output())
    before = _snapshot(workspace["root"])
    assert _approve(monkeypatch, reviewer="D. Reviewer") == 1

    assert workspace["approved_file"].read_bytes() == good
    assert _snapshot(workspace["root"]) == before


def test_a_rollback_leaves_no_temporary_or_orphan_file(workspace, monkeypatch):
    _install(workspace, _package(), _output())
    assert _approve(monkeypatch) == 0
    before = _snapshot(workspace["root"])

    real_write = decision.write_atomic

    def _explode(path, text):
        if path.name.startswith("assessment_history"):
            raise OSError("simulated history failure")
        return real_write(path, text)

    monkeypatch.setattr(decision, "write_atomic", _explode)
    with pytest.raises(OSError, match="simulated history failure"):
        _approve(monkeypatch, reviewer="E. Reviewer")

    after = _snapshot(workspace["root"])
    assert after == before
    assert not [name for name in after if name.endswith(".tmp") or ".json.tmp" in name]
    assert len(list(workspace["archive"].glob("*.json"))) == 0
