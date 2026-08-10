# Situation Intelligence architecture (WO-047)

**Work Order:** WO-047 · **Issue:** [#89](https://github.com/beer598623/Logistics-Situation-Platform/issues/89)
**Design reference:** [Issue #88](https://github.com/beer598623/Logistics-Situation-Platform/issues/88)
(the full WO-046 architecture research; see especially
[comment 2](https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493)
for the Document/Claim/Event models and evidence grading, and
[comment 5](https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235531477)
for the reuse matrix, structural example, migration plan and this Work Order's exact
recommendation)
**Status:** Phase 1 in full, plus tooling for the manual-intake half of phase 2. No real
intake exercise performed — see §6.

This document is a concise, accurate summary of what this Work Order actually built. It does
not re-derive the full design rationale; Issue #88 is the authority for *why*, this document
and the code it describes are the authority for *what actually exists*.

## 1. Why: from a structured-data dashboard to a source-backed intelligence platform

Before this Work Order, the platform's primary intelligence unit was a numeric time series
(`fact_indicator`, `fact_trade`, `fact_port_transport`, `fact_cost`) or a `logistics_event`
built directly from `event_evidence` rows. Both are still fully intact and unchanged. What was
missing was a place for *a source-backed development to exist and be traceable without a
number attached to it* — a Document (the thing a publisher published) and a Claim (one
assertion, from one Document, about one thing, at one time). This Work Order adds both, as new,
additive contracts, and a deterministic adapter that projects a `(Claim, Document)` pair into
the existing `event_evidence` shape.

## 2. What was built

| # | Deliverable | File(s) |
|---|---|---|
| 1 | Document contract | `schemas/document.schema.json` |
| 2 | Claim contract | `schemas/claim.schema.json` |
| 3 | Additive enum extensions | `schemas/event_evidence.schema.json` (`claim_type` +3), `schemas/impact_assessment.schema.json` (`status` +2) |
| 4 | `logistics_event.schema.json` additive fields | `situation_state`, `claim_ids`, `evidence_grade`, `superseded_by`, `verified_facts`/`reported_claims`/`analytical_inferences`/`conflicting_claims` — all optional/nullable, no existing record touched |
| 5 | Claim × Document → `event_evidence` adapter | `analysis/claim_evidence_adapter.py` |
| 6 | Manual intake tooling | `scripts/manual_intake.py` |
| 7 | New `scripts/validate.py` rules | `analysis/claims.py`, wired into `scripts/validate.py`'s "Documents and Claims" section |
| — | Registry v0.4 (`classification`/`governance` blocks) | `schemas/source_contract.schema.json#/$defs/governance`, `config/sources.yaml` |
| 9 | Labelled synthetic fixtures + rule proofs | `tests/fixtures/situation_intelligence/`, `tests/test_validate_claim_rules.py` |
| 10 | This document, `docs/evidence_layers.md`, `docs/known_data_gaps.md` §10 | — |

Item 8 (Issue #89) — one real, human-curated intake exercise — is **explicitly deferred**: it
is blocked on Issue #89's D-2 (which source is the pilot?) and D-6 (who is the named
reviewer?), both unresolved human product decisions. `scripts/manual_intake.py` builds and
validates the capability against synthetic/fixture data only; `data/documents/` and
`data/claims/` are empty scaffolds (`{"documents": []}` / `{"claims": []}`).

## 3. The Document model

`schemas/document.schema.json` records *the act of publication* — never an interpretation of
it. Severity, impact and Thailand relevance are never Document properties; they belong to
Claims and Developments (`logistics_event`). Key properties:

- `document_id` (`DOC-YYYYMMDD-NNN`), `source_id`, `document_type` (12-value enum:
  `official_notice`, `advisory`, `circular`, `press_release`, `news_article`,
  `analysis_report`, `statistical_release`, `research_paper`, `newsletter`, `social_post`,
  `dataset_record`, `manual_transcription`).
- `evidence_layer` (`current_evidence` / `context` / `structural_research`) — see
  `docs/evidence_layers.md`.
- `publisher_is_originator` — false means this document is a syndication/aggregation; the
  schema then requires `originator_publisher`/`originator_document_url` non-null.
- `rights` — a **fail-closed** snapshot of the publication permission in effect at intake
  time (`publication_use` reused verbatim from `source_contract.schema.json`'s
  `qualification.publication_use` enum, `quotation_allowed`, `redistribution_status`,
  `decided_by`/`decided_at`/`basis`). `rights` and `rights.publication_use` are both schema-
  required, so a document with no rights block, or an incomplete one, fails validation
  outright — proven by `tests/test_validate_claim_rules.py::test_document_with_no_rights_block_fails_schema_validation`.
- `stored_content_location` is constrained to `type: "null"` in the schema itself — this is a
  public repository; no article body, cache or full response may ever be committed here.
- Reuses `observation_common.schema.json`'s `retrievalStatus`/`evidenceOrigin`/
  `contentHashScope`/`dataset` `$defs` unchanged, and the same
  retrieval_status↔retrieved_at pairing `allOf` rule already enforced on
  `event_evidence.schema.json`.

## 4. The Claim model

`schemas/claim.schema.json` is the object most of the design's guarantees are enforced on.
**One Claim = one assertion, from one Document, about one thing, at one time.** `document_id`
is required — a claim with no document cannot exist; this is the traceability guarantee.
`event_ids` is a 0..n array (not a single `event_id`), so a claim may be unattached, attached
to one Development, or attached to two after a split.

`claim_type` is a 9-value enum: the existing 6 `event_evidence` values plus 3 new ones
(`structural_finding`, `historical_fact`, `denial_or_correction`), added additively to
`event_evidence.schema.json` too so the adapter never needs a lossy remapping.
`denial_or_correction` matters specifically: without it, a source explicitly denying or
correcting a prior claim would have to be encoded as a plain `verified_fact` with
`relation: contradicts`, losing the fact that it is a *correction of a specific prior claim*.

`evidence_layer` and `independence_group` are **copied from the Document and frozen on the
claim** — so a later registry reclassification can never retroactively promote a published L3
claim to L1. This is the L3 firewall's enforcement point (§7). `attributed_to.is_named: false`
means the claim can never exceed `REPORTED` grade. `claim_scope: region` can never alone
support a Thailand-scope conclusion (enforced: §7).

### `corroboration_status`

| Value | Entry rule |
|---|---|
| `uncorroborated` | Exactly one independence group asserts it |
| `corroborated_dependent` | ≥2 documents but all share one `independence_group`, or all trace to one `originator_document_url` — **this is not corroboration** and is recorded as such |
| `corroborated_independent` | ≥2 documents from ≥2 distinct `independence_group` values |
| `officially_confirmed` | ≥1 primary L1 source with authority over the subject asserts it (`primary_for_this_claim: true` and registry authority) |
| `contradicted` | ≥1 claim with `relation: contradicts` and `contradiction_status: unresolved` |
| `not_assessed` | Default. Never treated as corroborated |

`corroborated_dependent` is the structural answer to "do not treat multiple publications
copying the same upstream report as independent confirmation" — twenty syndicated articles
produce a visible "20 reports, 1 independent origin" statement, never a spurious confidence
increase. `scripts/validate.py` enforces the half of `officially_confirmed`'s entry rule
checkable purely from the claim record: it can never be `officially_confirmed` without
`primary_for_this_claim: true` (§7).

## 5. The Claim × Document → `event_evidence` adapter

`event_evidence.schema.json` is **reused with an adapter, not replaced**.
`analysis/claim_evidence_adapter.py::project_event_evidence(claim, document, event_id,
registry)` is a pure function that deterministically builds one
`event_evidence`-schema-conformant dict. Consequence: `analysis/`,
`scripts/build_dashboard.py`, `scripts/validate.py` and every existing test keep working
unchanged — the entire new Document/Claim plane was built and validated **without touching a
single downstream consumer**.

Two derivations are heuristic rather than table lookups, and both are documented precisely in
the module's docstring:

- **`evidence_role`** — a discovery-source registry entry always yields `discovery_only`;
  anything not at the `current_evidence` layer, or attributed to an unnamed party, is
  `contextual`; otherwise `confirming`.
- **`strength` (A–D) / `strength_basis`** — a real, simple heuristic per Issue #88 comment 2
  §8.2, not a placeholder: `A` requires `primary_for_this_claim`, `current_evidence` layer,
  and `claim_type` in `{verified_fact, official_notice}`; `B` requires a named attribution or
  bare primacy; everything else is `C`; a discovery lead or L3 claim is always `D`.
  `strength_basis` is `expected_at_cutoff` for any fixture-origin Document, `verified` only
  when content was actually retrieved or human-reviewed. Full multi-signal grading (registry
  `authoritative_for` coverage, freshness-window interaction, the contradiction clock) is
  **deferred to a later phase** — this is deliberately the smallest heuristic that is still
  correct on real data, not a stub.

**Round-trip proof (acceptance A-2):** `tests/test_claim_evidence_adapter.py` reproduces three
of the 17 committed `event_evidence` records (`EVD-HVC-001-A`, `EVD-HVC-001-B`,
`EVD-HVC-004-B` — chosen for evidence-role diversity: confirming/A, discovery_only/D,
contextual/C) from hand-built synthetic Document+Claim records, asserting equality on every
field except five that are structurally exempted (with a documented reason each):
`evidence_id`, `source_id`/`intended_source_id` (the legacy `SYNTHETIC_FIXTURE` placeholder
concept does not exist in the Document model), `fixture_created_at` (no Document field),
`parser_version` and `licence_status` (both registry-derived rather than Document fields, so
a legacy fixture's authored values can legitimately disagree with today's registry state).

## 6. Manual intake (item 6; the real exercise is item 8, deferred)

`scripts/manual_intake.py::build_manual_intake(...)` builds one Document and one-or-more Claim
records from operator-supplied fields (title, publisher, url, published_at, source_id, a list
of claim paraphrases with their claim_type/claim_scope), validates every one against the new
schemas, and refuses (raises `ValueError`) unless the source's `access_method` is `manual` and
its `qualification.manual_intake_status` is `allowed` — today, only `MANUAL_NOTICE_INTAKE`
qualifies. `underlying_publisher_required` is enforced: a blank `publisher` is refused when the
registry requires one. `write_intake(...)` appends to `data/documents/documents.json` /
`data/claims/claims.json` in the existing `data/events/`-style single-combined-file layout.

**This Work Order writes no real content into `data/documents/` or `data/claims/`.**
`tests/test_manual_intake.py` exercises the full path against synthetic/fixture data and
writes only to `tmp_path`; a guard test
(`test_repository_data_documents_directory_has_no_real_content`) asserts both real files stay
empty. The real intake exercise (Issue #89 item 8, acceptance A-5/A-6) is a separate,
human-directed exercise waiting on D-2/D-6.

## 7. New `scripts/validate.py` rules (`analysis/claims.py`)

Each rule below is a pure function returning a list of problem strings, with a passing and a
failing fixture test in `tests/test_validate_claim_rules.py`:

| Rule | Function | Semantics |
|---|---|---|
| L3 firewall | `l3_firewall_problems` | (1) An L3 (`structural_research`) claim may never appear in an event's `verified_facts`. (2) An event whose entire `claim_ids` set is L3-only may not carry `situation_state` other than absent/`UNCERTAIN` |
| Independence counting | `independence_confirmation_problems` | `corroboration_status: officially_confirmed` requires `primary_for_this_claim: true` |
| No AI-invented dates | `ai_date_invention_problems` | For `extraction_method` starting `ai_`: a null `event_start_at` must pair with `event_date_precision: unknown`; a non-null date must pair with a real precision |
| RESOLVED gating | `resolved_situation_state_problems` | `situation_state: RESOLVED` requires ≥1 `claim_ids` entry whose `claim_type` is `official_notice`/`verified_fact`/`denial_or_correction` |
| Regional-scope Thailand relevance | `regional_scope_thailand_relevance_problems` | `claim_scope: region` cannot pair with `thailand_relevance_asserted: asserted_by_source` |
| Claim ↔ Document consistency | `claim_document_consistency_problems` | `evidence_layer`/`independence_group` must agree with the frozen-from Document |

The 600-character claim-text cap is already schema-enforced (`claim.schema.json`'s
`claim_text` `maxLength: 600`, matching `event_evidence.claim`) — no redundant
`validate.py` rule was added; `test_claim_text_over_600_chars_fails_schema_not_a_validate_rule`
confirms the schema itself catches it. Rights fail-closed composition is likewise
schema-enforced (§3) and proven directly rather than via a `validate.py` rule.

Because `data/documents/`/`data/claims/` are empty scaffolds (§6), the cross-file rules
(RESOLVED gating, L3 firewall's second sub-rule, claim↔document consistency) are exercised
only by the synthetic fixture tests today — `scripts/validate.py`'s own run against the real
repository trivially passes them with zero records, not because the rules are inert.

## 8. Registry v0.4

`schemas/source_contract.schema.json#/$defs/governance` adds an optional `governance` block
per source with a deliberately bounded subset of Issue #88 comment 5 §C's full field list:
`independence_group`, `evidence_layer`, `evidence_layer_basis`, `enabled_for_discovery`,
`enabled_for_ingestion`, `enabled_for_public_claims`. Populated for all 18 sources in
`config/sources.yaml` (version bumped `0.3` → `0.4`) with defaults that change **no** existing
`enabled`/`licence_status`/`qualification` determination:

- `independence_group` defaults to one group per source (`IG-<SOURCE_ID>`) — no syndication or
  common-ownership relationship among the 18 is currently established.
- `evidence_layer`: 8 sources (notice/hazard/discovery channels) assigned `current_evidence`;
  10 (statistical/benchmark series) assigned `context`. **Zero assigned `structural_research`**
  — see `docs/known_data_gaps.md` §10.
- `enabled_for_discovery`/`enabled_for_ingestion` are `false` for all 18 — this Work Order
  enables no automated discovery, ingestion, scheduling or network retrieval.
- `enabled_for_public_claims` is `true` only for `MANUAL_NOTICE_INTAKE`, mirroring its
  existing `qualification.manual_intake_status: allowed` + `licence_status: reviewed` — this
  records an existing determination in the new vocabulary and enables nothing new.

**Deferred, deliberately, rather than populated with placeholder values:** `source_type`,
`publisher_type`, `primary_or_secondary`, `geographies`/`topics`/`transport_modes` (already
partially covered by existing `qualification.geography`/`logistics_role`), `automation_allowed`,
`retrieval_status`, `publication_policy`, `copyright_policy`, `quotation_policy`,
`freshness_expectation`, `credibility_notes`.

## 9. What this Work Order explicitly did not do

No AI claim extraction. No clustering rules 5–8. No `mode_situation` computation. No Daily
Brief. No Dashboard change of any kind — `dashboard/public/**` and `scripts/build_dashboard.py`
are untouched. No source enabled, scheduled or contacted. No real content in
`data/documents/`/`data/claims/`. No existing `config/sources.yaml` determination changed. No
rename of `logistics_event`, its ID prefix or its directory.
