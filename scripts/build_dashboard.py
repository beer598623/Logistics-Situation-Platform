#!/usr/bin/env python3

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "dashboard/public"
DATA = PUBLIC / "data"
DATA.mkdir(parents=True, exist_ok=True)

for source, name in [
    (ROOT / "data/reviewed/current_events.json", "current_events.json"),
    (ROOT / "data/indicators/latest.json", "indicators.json"),
    (ROOT / "data/source_status/latest.json", "source_status.json"),
    (ROOT / "innovation/solution_register.json", "solutions.json"),
]:
    shutil.copyfile(source, DATA / name)

status = {
    "built_at": datetime.now(UTC).isoformat(),
    "methodology_version": "0.7",
}
(DATA / "build_status.json").write_text(
    json.dumps(status, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Dashboard data built at {PUBLIC}")
