"""Shared JSON Schema loading and validation.

Extracted so that ``scripts/validate.py``, ``scripts/import_review.py`` and
the test suite all validate against the same registry and the same format
checker, rather than each building their own and drifting apart.

Every schema in ``schemas/`` is registered twice -- once by file URI and once
by bare filename -- so a ``$ref`` of either form resolves.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def schema_registry() -> Registry:
    registry = Registry()
    for schema_path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = load_json(schema_path)
        registry = registry.with_resource(schema_path.as_uri(), Resource.from_contents(schema))
        registry = registry.with_resource(schema_path.name, Resource.from_contents(schema))
    return registry


@lru_cache(maxsize=64)
def validator(schema_name: str) -> Draft202012Validator:
    schema = load_json(SCHEMAS / schema_name)
    return Draft202012Validator(
        schema,
        registry=schema_registry(),
        format_checker=FormatChecker(),
    )


def schema_errors(item: Any, schema_name: str) -> list[str]:
    """Return human-readable schema errors, ordered by location."""
    errors = sorted(validator(schema_name).iter_errors(item), key=lambda error: list(error.path))
    return [
        f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
    ]
