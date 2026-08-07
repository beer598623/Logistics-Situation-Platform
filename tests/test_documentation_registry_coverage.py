"""WO-011: doc/registry consistency for the source-qualification record.

``docs/source_qualification_report.md`` is the Gate C qualification record and
is supposed to be the complete register of every candidate considered. It
previously omitted two registered sources (``PAT_STATISTICS``, ``FBX_PUBLIC``)
added by WO-010-R1 -- these tests make that class of drift a CI failure rather
than something only caught by a manual audit.
"""

from __future__ import annotations

import re
from pathlib import Path

from collectors.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]


def _doc_text(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def _registry_source_count_marker(text: str) -> int:
    match = re.search(r"<!--\s*registry-source-count:\s*(\d+)\s*-->", text)
    assert match, "expected a '<!-- registry-source-count: N -->' marker"
    return int(match.group(1))


def test_qualification_report_names_every_registered_source() -> None:
    registry = load_registry()
    text = _doc_text("source_qualification_report.md")
    missing = [s["id"] for s in registry["sources"] if s["id"] not in text]
    assert not missing, f"source_qualification_report.md omits: {missing}"


def test_enablement_decisions_names_every_registered_source() -> None:
    registry = load_registry()
    text = _doc_text("source_enablement_decisions.md")
    missing = [s["id"] for s in registry["sources"] if s["id"] not in text]
    assert not missing, f"source_enablement_decisions.md omits: {missing}"


def test_documented_contract_count_matches_registry() -> None:
    registry = load_registry()
    expected = len(registry["sources"])
    for name in (
        "source_qualification_report.md",
        "bundle1_architecture.md",
        "production_readiness_roadmap.md",
    ):
        text = _doc_text(name)
        assert _registry_source_count_marker(text) == expected, (
            f"{name}'s registry-source-count marker is stale (registry has {expected} sources)"
        )


def test_no_source_became_enabled() -> None:
    registry = load_registry()
    assert all(source["enabled"] is False for source in registry["sources"])


# ---------------------------------------------------------------------------
# WO-042: historical_validation.md's headline counts vs. the validation report
#
# docs/historical_validation.md still said "nine cases" / "81 impact
# assessments" after WO-041 added HVC-010 as its tenth case -- the doc was
# simply never regenerated. This binds it to the machine-generated report the
# same way the tests above bind the qualification docs to the registry.
# ---------------------------------------------------------------------------


def _historical_validation_metrics_marker(text: str) -> dict[str, int]:
    match = re.search(
        r"<!--\s*historical-validation-metrics:\s*"
        r"cases=(\d+)\s+impacts_assessed=(\d+)\s+material_impacts=(\d+)\s+"
        r"insufficient_evidence_uses=(\d+)\s*-->",
        text,
    )
    assert match, "expected a '<!-- historical-validation-metrics: ... -->' marker"
    return {
        "cases": int(match.group(1)),
        "impacts_assessed": int(match.group(2)),
        "material_impacts": int(match.group(3)),
        "insufficient_evidence_uses": int(match.group(4)),
    }


def test_historical_validation_doc_counts_match_the_report() -> None:
    import json

    report = json.loads((ROOT / "data" / "validation" / "validation_report.json").read_text())
    marker = _historical_validation_metrics_marker(_doc_text("historical_validation.md"))
    assert marker["cases"] == len(report["cases"]), (
        f"doc claims {marker['cases']} cases; report has {len(report['cases'])}"
    )
    for key in ("impacts_assessed", "material_impacts", "insufficient_evidence_uses"):
        assert marker[key] == report["metrics"][key], (
            f"historical_validation.md's {key} marker is stale "
            f"(doc says {marker[key]}, report says {report['metrics'][key]})"
        )


def test_historical_validation_doc_lists_every_case_id() -> None:
    import json

    report = json.loads((ROOT / "data" / "validation" / "validation_report.json").read_text())
    text = _doc_text("historical_validation.md")
    missing = [c["case_id"] for c in report["cases"] if c["case_id"] not in text]
    assert not missing, f"historical_validation.md omits: {missing}"
