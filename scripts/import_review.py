#!/usr/bin/env python3
"""Validate a returned ChatGPT assessment before any human decides on it.

Two gates run here, in order:

1. **Schema.** The reply must match ``schemas/review_package_output.schema.json``.
2. **Rejection rules.** ``analysis.review_package.validate_output`` applies the
   Gate I checks: unknown evidence, missing transmission mechanisms,
   missing-as-zero, a proxy presented as a quotation, a real-time congestion
   claim without operational evidence, unsupported causation, preparedness
   overreach, and scenario completeness.

Passing both gates does **not** publish anything and does not mean the
assessment is approved. It means the assessment is eligible for a human
decision, which ``scripts/review_decision.py`` records separately. A High or
Critical conclusion additionally requires an explicit human-review record and
can never be published autonomously.

Usage::

    python scripts/import_review.py --package-id PKG-20260724-001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.contracts import schema_errors  # noqa: E402
from analysis.review_package import requires_human_review, validate_output  # noqa: E402

PACKAGE_DIR = ROOT / "data" / "review" / "packages"
INBOUND_DIR = ROOT / "data" / "review" / "inbound"


def load_pair(package_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    package_path = PACKAGE_DIR / f"{package_id}.json"
    output_path = INBOUND_DIR / f"{package_id}.json"
    if not package_path.exists():
        raise SystemExit(f"No input package found at {package_path.relative_to(ROOT)}")
    if not output_path.exists():
        raise SystemExit(
            f"No returned assessment found at {output_path.relative_to(ROOT)}. Save the "
            "structured ChatGPT reply there first."
        )
    return (
        json.loads(package_path.read_text(encoding="utf-8")),
        json.loads(output_path.read_text(encoding="utf-8")),
    )


def review(package_id: str) -> tuple[bool, list[str], bool]:
    """Return ``(accepted, problems, needs_human_review)``."""
    package, output = load_pair(package_id)

    problems = [
        f"schema: {message}"
        for message in schema_errors(output, "review_package_output.schema.json")
    ]
    problems.extend(validate_output(output, package))
    return not problems, problems, requires_human_review(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", required=True)
    args = parser.parse_args()

    accepted, problems, needs_review = review(args.package_id)

    if problems:
        print(f"[REJECT] {len(problems)} rejection rule(s) fired:")
        for problem in problems:
            print(f"  - {problem}")

    if not accepted:
        print("\nThe assessment is rejected and must not be approved or published.")
        return 1

    print("[PASS] The returned assessment satisfies the schema and every rejection rule.")
    print("This is eligibility for human review, not approval.")
    if needs_review:
        print(
            "\n[HUMAN REVIEW REQUIRED] The assessment claims a High or Critical conclusion. "
            "It cannot be published without an explicit human-review record recorded by "
            "scripts/review_decision.py."
        )
    print(
        f"\nNext: python scripts/review_decision.py --package-id {args.package_id} "
        "--decision approve|reject --reviewer '<name or record>'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
