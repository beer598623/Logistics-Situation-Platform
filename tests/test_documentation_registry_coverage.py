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

_WORDS_TO_INT = {
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


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


def test_historical_validation_doc_visible_prose_matches_the_report() -> None:
    """The marker test above binds only the hidden HTML-comment marker.
    Reverting the *visible* prose/table numbers back to the stale 9/81
    figures while leaving the marker untouched would still pass that test --
    verified by mutation during WO-042 review. This binds the reader-facing
    numbers directly."""
    import json

    report = json.loads((ROOT / "data" / "validation" / "validation_report.json").read_text())
    text = _doc_text("historical_validation.md")
    metrics = report["metrics"]

    intro_match = re.search(
        r"Measured across all (\w+) cases at once, (\d+) impact assessments in total",
        text,
    )
    assert intro_match, "expected the '## 4. Measured behaviours' intro sentence"
    case_count_word = intro_match.group(1).lower()
    assert case_count_word in _WORDS_TO_INT, f"unrecognised count word '{case_count_word}'"
    assert _WORDS_TO_INT[case_count_word] == len(report["cases"]), (
        f"intro sentence says '{case_count_word}' cases; report has {len(report['cases'])}"
    )
    assert int(intro_match.group(2)) == metrics["impacts_assessed"], (
        f"intro sentence says {intro_match.group(2)} impact assessments; "
        f"report says {metrics['impacts_assessed']}"
    )

    table_checks = {
        "Impacts assessed": metrics["impacts_assessed"],
        "Material impacts": metrics["material_impacts"],
        "Insufficient-evidence uses": metrics["insufficient_evidence_uses"],
        "No-material uses": metrics["no_material_uses"],
    }
    for row_label, expected in table_checks.items():
        row_match = re.search(rf"\|\s*{re.escape(row_label)}\s*\|\s*(\d+)\s*\|", text)
        assert row_match, f"expected a '| {row_label} | N |' table row"
        assert int(row_match.group(1)) == expected, (
            f"'{row_label}' row says {row_match.group(1)}; report says {expected}"
        )

    separation_match = re.search(r"([A-Za-z]+) cases demonstrate them genuinely diverging", text)
    assert separation_match, "expected the event/impact separation count sentence"
    word = separation_match.group(1).lower()
    assert word in _WORDS_TO_INT, f"unrecognised count word '{word}'"
    assert _WORDS_TO_INT[word] == len(metrics["event_impact_separation_examples"]), (
        f"doc says '{word}' cases diverge; report lists "
        f"{len(metrics['event_impact_separation_examples'])}"
    )


def test_historical_validation_doc_lists_every_case_id() -> None:
    import json

    report = json.loads((ROOT / "data" / "validation" / "validation_report.json").read_text())
    text = _doc_text("historical_validation.md")
    missing = [c["case_id"] for c in report["cases"] if c["case_id"] not in text]
    assert not missing, f"historical_validation.md omits: {missing}"
