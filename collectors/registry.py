"""Load and validate source contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def load_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or ROOT / "config" / "sources.yaml"
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Source registry must be a mapping")
    return data


def validate_registry(data: dict[str, Any]) -> list[str]:
    schema = json.loads(
        (ROOT / "schemas" / "source_contract.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    messages = []
    for error in errors:
        location = "/".join(map(str, error.path)) or "<root>"
        messages.append(f"{location}: {error.message}")

    source_ids = [
        source.get("id")
        for source in data.get("sources", [])
        if isinstance(source, dict)
    ]
    if len(source_ids) != len(set(source_ids)):
        messages.append("sources: source IDs must be unique")
    return messages


def source_by_id(data: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in data.get("sources", []):
        if source.get("id") == source_id:
            return source
    raise KeyError(f"Unknown source ID: {source_id}")
