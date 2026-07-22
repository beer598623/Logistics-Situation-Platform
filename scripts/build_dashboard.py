#!/usr/bin/env python3
from pathlib import Path
import json, shutil
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/"dashboard/public"
DATA=PUBLIC/"data"
DATA.mkdir(parents=True, exist_ok=True)
for src,name in [
    (ROOT/"data/reviewed/current_events.json","current_events.json"),
    (ROOT/"data/indicators/latest.json","indicators.json"),
    (ROOT/"data/source_status/latest.json","source_status.json"),
    (ROOT/"innovation/solution_register.json","solutions.json")]:
    shutil.copyfile(src, DATA/name)
status={"built_at":datetime.now(timezone.utc).isoformat(),"methodology_version":"0.7"}
(DATA/"build_status.json").write_text(json.dumps(status,indent=2)+"\n",encoding="utf-8")
print(f"Dashboard data built at {PUBLIC}")
