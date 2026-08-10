# Situation Intelligence (WO-047 / Issue #89) fixtures

Synthetic test fixtures only. Every publisher, place, node and lane below is
invented (`SYNTH-`/`STRUCTURAL EXAMPLE`-labelled) and does not describe any
real port, authority, carrier or disruption — following the "STRUCTURAL
EXAMPLE — NOT CURRENT INTELLIGENCE" convention established in Issue #88
comment 5 Section 19.

- `document_structural_example.json` — a `document.schema.json`-conformant
  fixture. Carries a `_label` key (not part of the schema; strip it before
  schema validation, as `tests/test_document_claim_fixtures.py` does) that
  makes the synthetic/non-real nature of the record impossible to miss even
  if the file is opened outside its test.
- `claim_structural_example.json` — a `claim.schema.json`-conformant fixture
  referencing the document above by `document_id`, with matching
  `evidence_layer`/`independence_group` (both frozen copies, per Issue #88
  comment 2 Section 6.2).

See `tests/test_document_claim_fixtures.py` for the schema-validation test
and `tests/test_validate_claim_rules.py` for the semantic-rule tests these
two fixtures exist to support.
