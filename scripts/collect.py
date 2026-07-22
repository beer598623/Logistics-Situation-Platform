#!/usr/bin/env python3
"""Validate collection contracts without enabling live network collection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.models import CollectionRun  # noqa: E402
from collectors.registry import load_registry, source_by_id, validate_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate contracts and emit run manifests",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Limit dry run to one or more source IDs",
    )
    args = parser.parse_args()

    if not args.dry_run:
        print(
            json.dumps(
                {
                    "status": "disabled",
                    "reason": "Live adapters are not enabled in v0.1.1.",
                }
            )
        )
        return 0

    registry = load_registry()
    errors = validate_registry(registry)
    if errors:
        print(json.dumps({"status": "invalid_contracts", "errors": errors}, indent=2))
        return 1

    selected = args.source or [source["id"] for source in registry["sources"]]
    runs = []
    for source_id in selected:
        source = source_by_id(registry, source_id)
        run = CollectionRun.dry_run(
            source_id=source_id,
            adapter_version=source["parser"],
            request_url=source["endpoint"],
        )
        runs.append(run.to_dict())

    print(
        json.dumps(
            {
                "status": "dry_run",
                "contracts": len(registry["sources"]),
                "runs": runs,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
