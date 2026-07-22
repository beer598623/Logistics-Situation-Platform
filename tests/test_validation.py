from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_negative_control_is_no_material() -> None:
    data = json.loads((ROOT / "data/reviewed/current_events.json").read_text())
    event = data["events"][0]
    assert event["negative_operational_evidence"] is True
    assert event["publication_status"] == "No material impact detected"
    assert len(event["impact_assessments"]) == 9
    assert all(item["severity"] == "none" for item in event["impact_assessments"])


def test_no_missing_as_zero() -> None:
    text = (ROOT / "data/reviewed/current_events.json").read_text()
    assert '"unknown_value": 0' not in text


def test_dashboard_entry_exists() -> None:
    assert (ROOT / "dashboard/public/index.html").exists()
