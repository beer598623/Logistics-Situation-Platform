#!/usr/bin/env python3
from pathlib import Path
import json, sys
from jsonschema import Draft202012Validator, RefResolver, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validator(schema_name):
    schema = load(SCHEMAS / schema_name)
    resolver = RefResolver((SCHEMAS / schema_name).as_uri(), schema)
    return Draft202012Validator(schema, resolver=resolver, format_checker=FormatChecker())


def validate_item(item, schema_name, label):
    errors = sorted(validator(schema_name).iter_errors(item), key=lambda e: list(e.path))
    if errors:
        print(f"[FAIL] {label}")
        for err in errors:
            print("  -", "/".join(map(str, err.path)) or "<root>", err.message)
        return False
    print(f"[PASS] {label}")
    return True


def semantic_checks(event):
    problems=[]
    impacts=event.get("impact_assessments",[])
    areas=[x.get("area") for x in impacts]
    required={"warehouse","logistics","transport","import_export","inventory","cost","capacity","service","business_continuity"}
    if set(areas)!=required or len(areas)!=9:
        problems.append("impact_assessments must contain each of the nine areas exactly once")
    evidence_ids={e["evidence_id"] for e in event.get("evidence",[])}
    for impact in impacts:
        unknown=set(impact.get("evidence_ids",[]))-evidence_ids
        if unknown: problems.append(f"{impact.get('area')}: unknown evidence IDs {sorted(unknown)}")
        if impact.get("severity") in {"high","critical"} and impact.get("evidence_strength") not in {"A","B"}:
            problems.append(f"{impact.get('area')}: high/critical impact lacks primary-grade evidence")
        if impact.get("status") in {"observed","potential"} and impact.get("severity") != "none" and not impact.get("transmission_mechanism"):
            problems.append(f"{impact.get('area')}: missing transmission mechanism")
    if event.get("publication_status") == "No material impact detected" and not event.get("negative_operational_evidence"):
        problems.append("no-material-impact status requires negative operational evidence")
    return problems


def main():
    ok=True
    candidates=load(ROOT/"data/candidates/latest.json")
    for i,item in enumerate(candidates.get("candidates",[])):
        ok &= validate_item(item,"candidate_event.schema.json",f"candidate[{i}]")
    reviewed=load(ROOT/"data/reviewed/current_events.json")
    for i,item in enumerate(reviewed.get("events",[])):
        item_ok=validate_item(item,"reviewed_event.schema.json",f"reviewed_event[{i}]")
        for problem in semantic_checks(item):
            print(f"[FAIL] reviewed_event[{i}] semantic: {problem}")
            item_ok=False
        ok &= item_ok
    print("Validation successful." if ok else "Validation failed.")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
