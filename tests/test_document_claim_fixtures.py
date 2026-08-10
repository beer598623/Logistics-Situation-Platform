"""Schema-validation tests for the labelled synthetic Document/Claim
fixtures (WO-047 / Issue #89, item 9).

See tests/fixtures/situation_intelligence/README.md for what these fixtures
are and are not.
"""

from __future__ import annotations

import json
from pathlib import Path

from analysis.contracts import schema_errors

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "situation_intelligence"


def _load(name: str) -> dict:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert payload.pop("_label").startswith("STRUCTURAL EXAMPLE")
    return payload


def test_document_fixture_validates():
    document = _load("document_structural_example.json")
    errors = schema_errors(document, "document.schema.json")
    assert errors == []


def test_claim_fixture_validates():
    claim = _load("claim_structural_example.json")
    errors = schema_errors(claim, "claim.schema.json")
    assert errors == []


def test_claim_fixture_references_the_document_fixture_consistently():
    document = _load("document_structural_example.json")
    claim = _load("claim_structural_example.json")
    assert claim["document_id"] == document["document_id"]
    assert claim["source_id"] == document["source_id"]
    assert claim["evidence_layer"] == document["evidence_layer"]
    assert claim["independence_group"] == document["independence_group"]
