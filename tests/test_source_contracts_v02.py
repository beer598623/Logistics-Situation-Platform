from __future__ import annotations

from pathlib import Path

import yaml

from collectors.registry import load_registry, source_by_id, validate_registry

ROOT = Path(__file__).resolve().parents[1]


def test_registry_is_still_schema_valid_after_v02_extension() -> None:
    registry = load_registry()
    assert validate_registry(registry) == []


def test_gdacs_remains_disabled() -> None:
    registry = load_registry()
    gdacs = source_by_id(registry, "GDACS")
    assert gdacs["enabled"] is False
    assert gdacs["required_for_publication"] is False


def test_tmd_cap_remains_disabled_unverified_and_pending_review() -> None:
    registry = load_registry()
    tmd = source_by_id(registry, "TMD_CAP")
    assert tmd["enabled"] is False
    assert tmd["required_for_publication"] is False
    assert tmd["machine_readable_status"] == "unverified"
    assert tmd["licence_status"] == "pending_review"


def test_all_sources_in_registry_remain_disabled() -> None:
    registry = load_registry()
    assert all(source["enabled"] is False for source in registry["sources"])


def test_gdacs_cadence_is_unknown_not_an_asserted_six_minutes() -> None:
    registry = load_registry()
    gdacs = source_by_id(registry, "GDACS")
    assert gdacs["expected_cadence_minutes"] is None


def test_gdacs_stable_identity_is_composite_eventtype_and_eventid() -> None:
    registry = load_registry()
    gdacs = source_by_id(registry, "GDACS")
    assert gdacs["stable_id_field"] == ["eventtype", "eventid"]
    assert gdacs["revision_id_field"] == "episodeid"


def test_gdacs_pagination_documents_the_100_record_cap() -> None:
    registry = load_registry()
    gdacs = source_by_id(registry, "GDACS")
    assert gdacs["pagination"]["type"] == "page_number"
    assert gdacs["pagination"]["page_size"] == 100
    assert gdacs["pagination"]["max_page_size"] == 100


def test_tmd_primary_endpoint_is_english_and_alternate_is_thai() -> None:
    registry = load_registry()
    tmd = source_by_id(registry, "TMD_CAP")
    assert tmd["endpoint"] == "https://www.tmd.go.th/en/api/xml/CAP"
    alternates = {entry["label"]: entry["url"] for entry in tmd["alternate_endpoints"]}
    assert alternates["thai_language_cap"] == "https://www.tmd.go.th/api/xml/CAP"


def test_tmd_records_both_copyright_and_policy_reference_urls_without_resolving_conflict() -> None:
    registry = load_registry()
    tmd = source_by_id(registry, "TMD_CAP")
    assert tmd["terms_url"] == "https://www.tmd.go.th/content/copyright"
    reference_labels = {entry["label"] for entry in tmd["reuse_reference_urls"]}
    assert "tmd_website_policy" in reference_labels
    limitations_text = " ".join(tmd["known_limitations"])
    assert "not fully aligned" in limitations_text
    assert tmd["licence_status"] == "pending_review"


def test_source_contract_schema_extension_is_additive_and_optional() -> None:
    """The v0.2 schema extension (alternate_endpoints, revision_id_field,
    reuse_reference_urls, pagination.max_page_size, composite
    stable_id_field) must stay optional so pre-existing single-source-id
    contracts (GSCPI, TH_CUSTOMS, EPPO_FUEL) remain valid untouched."""
    registry = load_registry()
    for source_id in ("GSCPI", "TH_CUSTOMS", "EPPO_FUEL"):
        source = source_by_id(registry, source_id)
        assert "alternate_endpoints" not in source
        assert "revision_id_field" not in source
        assert "reuse_reference_urls" not in source
        assert "max_page_size" not in source["pagination"]
    assert validate_registry(registry) == []


def test_last_reviewed_at_was_bumped_for_this_material_change() -> None:
    """The registry review date advances whenever the registry changes.

    Bumped from the WO-004 date to 2026-07-24 by WO-010, which added ten
    source candidates and the qualification/enablement records for the three
    pre-existing Bundle 1 candidates. The GDACS and TMD_CAP entries keep
    their own unchanged ``terms_reviewed_at`` dates, which this bump does not
    touch.
    """
    registry = load_registry()
    assert registry["last_reviewed_at"] == "2026-07-24"


def test_config_sources_yaml_parses_as_plain_yaml() -> None:
    raw = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    assert raw["sources"]
