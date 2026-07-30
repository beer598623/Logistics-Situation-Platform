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
    for name in ("source_qualification_report.md", "bundle1_architecture.md"):
        text = _doc_text(name)
        assert _registry_source_count_marker(text) == expected, (
            f"{name}'s registry-source-count marker is stale (registry has {expected} sources)"
        )


def test_no_source_became_enabled() -> None:
    registry = load_registry()
    assert all(source["enabled"] is False for source in registry["sources"])
