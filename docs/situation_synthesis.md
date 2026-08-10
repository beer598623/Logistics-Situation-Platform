# Situation synthesis: grading, `mode_situation`, and the contradiction clock (WO-049)

**Work Order:** WO-049 · **Issue:** [#92](https://github.com/beer598623/Logistics-Situation-Platform/issues/92)
**Design reference:** [Issue #91](https://github.com/beer598623/Logistics-Situation-Platform/issues/91)
(comment 1, "design part 1", for clustering and item/Development-level grading; comment 2,
"design part 2", for `mode_situation` and the Daily Brief; comment 3, the recommendation this
Work Order's scope mirrors).
**Status:** Items 1–8 and 10–13 of Issue #92's scope shipped, offline, against fixtures and the
still-empty `data/documents/`/`data/claims/` scaffolds. Item 9 (the real intake exercise) is
deferred — see `docs/known_data_gaps.md` §11.

This document is the companion to `docs/situation_intelligence_architecture.md` (the
Document/Claim contracts, WO-047) and `docs/evidence_layers.md` (the L1/L2/L3 axis). It covers
what WO-049 added on top of both: full item-level grading, the Development-level `evidence_grade`
computation, `mode_situation` (Gate 0 plus five ordered rules), the `conflicting_evidence[]`
extension, and `situation_state` transitions. It does not re-derive the design rationale — Issue
#91 is the authority for *why*; this document and the code it describes are the authority for
*what actually exists*.

## 1. What this Work Order added, and where

| # | Deliverable | File(s) |
|---|---|---|
| 1 | Publisher identity plane: `governance.channel_role`, `document.publisher_authority`, `claim.assertion.predicate_class` | `schemas/source_contract.schema.json`, `schemas/document.schema.json`, `schemas/claim.schema.json`, `config/sources.yaml` (v0.5), `scripts/manual_intake.py` |
| 2 | Full item-level A/B/C/D grading: `authority_covers()`, `freshness_state()`, contradiction-aware strength | `analysis/claim_evidence_adapter.py` |
| 3 | Development-level `evidence_grade` (pure function) + downgrade-only `grade_override` | `analysis/grading.py`, `schemas/logistics_event.schema.json` |
| 4 | `assertion_group_id` + the minimal claim→Development attachment path (rules 3, 6, 7 only) | `analysis/attachment.py`, `schemas/claim.schema.json` |
| 5 | `mode_situation.schema.json` + its computation (Gate 0, five ordered rules) | `analysis/situations.py`, `schemas/mode_situation.schema.json`, `scripts/build_situations.py`, `data/situations/situations.json` |
| 6 | `conflicting_evidence[]` extension (7 fields + 2 `resolution_status` values) + the status-change-vs-contradiction rule | `schemas/logistics_event.schema.json`, `analysis/situation_validation.py` |
| 7 | `situation_state` transitions for `EMERGING`/`ACTIVE`/`DEVELOPING`/`UNCERTAIN`/`RESOLVED` | `analysis/grading.py` |
| 8 | Four `impact_assessment` basis fields: `watch_trigger`, `no_material_basis`, `not_relevant_basis`, `supporting_claim_ids` | `schemas/impact_assessment.schema.json` |
| 10 | `scripts/validate.py` rules (explainability walk, `grade_override` refusal, authority-coverage-for-A/CONFIRMED, the conduit rule, shared-independence-group-without-basis, `mode_situation.status_basis` non-empty, plus the item-8 basis-field rule below) | `analysis/situation_validation.py`, wired into `scripts/validate.py` |
| 11 | `merge_status` vocabulary fix | `schemas/logistics_event.schema.json`, unchanged `collectors/event_identity.py` |
| 13 | Labelled synthetic fixtures, plus 3 new historical-validation-style cases | `tests/test_attachment.py`, `tests/test_grading.py`, `tests/test_build_situations.py`, `tests/test_validate_situation_rules.py`, `tests/test_situation_synthesis_historical_cases.py` |

Item 9 (one real Port Authority of Thailand notice) is deferred — `docs/known_data_gaps.md` §11.
Items not in this list (clustering rules S1/S5/S6/S7/S8, the merge/split engine, the Daily
Brief, any Dashboard change) were explicitly out of scope for this Work Order and remain
unbuilt.

## 2. The publisher identity plane, briefly

Two structural blockers existed in the registry WO-047 shipped: every Document ingested through
`MANUAL_NOTICE_INTAKE` carried the *same* `independence_group` regardless of who actually
published the underlying notice (making `corroborated_independent` unreachable), and
`MANUAL_NOTICE_INTAKE.authoritative_for` is `[]` (making grade A / `evidence_grade: CONFIRMED`
unreachable). Both are fixed by one registry field and two Document fields:

- `governance.channel_role` (`originator_channel` | `conduit`) — `originator_channel` for 17 of
  the 18 registered sources (the source itself is the publisher); `conduit` for
  `MANUAL_NOTICE_INTAKE` (a transcription channel for arbitrary underlying publishers).
- `document.publisher_authority` — required, non-null, human-decided, whenever the source is a
  `conduit`. Absent or null is **fail-closed**: a claim from such a Document can never exceed
  grade B (`analysis/claim_evidence_adapter.py::authority_covers`).
- `document.independence_group`, for a `conduit` source, is derived from the underlying
  publisher (`IG-PUB-<normalised publisher>`) rather than copied from the source
  (`scripts/manual_intake.py`, the B-1 fix) — so two Documents transcribed through the same
  conduit from two genuinely distinct publishers land in two distinct independence groups, and
  two Documents from the *same* underlying publisher (e.g. its official notice channel and its
  press-office mirror) can be told to collapse onto one, via
  `underlying_publisher_identity_key` (`tests/test_situation_synthesis_historical_cases.py::
  test_case_a_syndicated_pair_yields_one_independence_group`).

`claim.assertion.predicate_class` (a 10-value enum — `berth_or_facility_availability`,
`transit_or_passage`, `service_schedule`, `capacity_or_equipment`, `customs_or_clearance`,
`tariff_or_fee`, `sanction_or_regulation`, `hazard_or_security`, `labour_action`,
`structural_finding`) is what makes authority coverage decidable by set membership rather than
string matching:

```
authority_covers(claim, document) :=
      claim.assertion.predicate_class ∈ document.publisher_authority.authority_scope.predicate_classes
  AND (   claim.node_ids       ∩ scope.node_ids       ≠ ∅
       OR claim.chokepoint_ids ∩ scope.chokepoint_ids ≠ ∅
       OR (claim.node_ids = ∅ AND claim.chokepoint_ids = ∅
           AND claim.country_ids ∩ scope.country_ids ≠ ∅) )
```

All 18 sources in `config/sources.yaml` (registry v0.5) carry `channel_role` explicitly; the
diff from v0.4 is additive-only (one field per source) and changes no existing `enabled`,
`licence_status`, `qualification` or `authoritative_for` value.

## 3. Item-level A/B/C/D grading, in full

`analysis/claim_evidence_adapter.py::_full_strength` (reached via `item_strength`, and via
`project_event_evidence`'s `strength` field for every non-fixture-origin Document) now reads
three inputs the WO-047 placeholder heuristic did not:

| Grade | Requires |
|---|---|
| **A** | `primary_for_this_claim` and `evidence_layer: current_evidence` and `claim_type ∈ {verified_fact, official_notice}` and `authority_covers()` and `freshness_state() == fresh` and no unresolved contradiction and `strength_basis == verified` and attribution is not explicitly unnamed |
| **B** | The A conditions hold except **exactly one** of `authority_covers()` / `freshness_state() == fresh`; or `evidence_layer: current_evidence` with a *named* attribution; or `primary_for_this_claim` with a `claim_type` outside `{verified_fact, official_notice}` |
| **C** | Everything else |
| **D** | A discovery lead, an L3 (`structural_research`) claim, a discovery-source registry entry, a paywalled or retrieval-failed Document |

A fixture-context Document (`evidence_origin` in `{synthetic_test_fixture,
historical_validation_fixture}`) still takes the original WO-047 placeholder heuristic
unchanged — this is what keeps `tests/test_claim_evidence_adapter.py`'s three committed
round-trip fixtures (acceptance A-2) grading exactly as they did before this Work Order; real
evidence always takes the full heuristic above.

### Freshness — no new field, the real numbers

`freshness_state(document, registry)` reads `source.max_stale_minutes`, already required and
populated on all 18 sources. The reference instant is the Document's `published_at`, falling
back to `retrieved_at`, falling back to `updated_at`; when none is set, the state is `unknown`,
treated exactly as `stale`/`expired` for grading and capping purposes.

| State | Condition |
|---|---|
| `fresh` | age ≤ 1× `max_stale_minutes` |
| `ageing` | 1× < age ≤ 2× |
| `stale` | 2× < age ≤ 4× |
| `expired` | age > 4×, or reference instant unknown |

The real per-source windows, from `config/sources.yaml` as merged (unchanged by this Work
Order — `max_stale_minutes` was already populated at WO-047):

| Source(s) | `evidence_layer` | `max_stale_minutes` | fresh | ageing | stale | expired |
|---|---|---|---|---|---|---|
| `GDACS`, `TMD_CAP` | current_evidence | 180 | ≤ 3 h | 3–6 h | 6–12 h | > 12 h |
| `PAT_NOTICE`, `ACP_ADVISORY`, `SCA_CIRCULAR`, `MPA_SG_NOTICE` | current_evidence | 20 160 | ≤ 14 d | 14–28 d | 28–56 d | > 56 d |
| `MANUAL_NOTICE_INTAKE` | current_evidence | 43 200 | ≤ 30 d | 30–60 d | 60–120 d | > 120 d |
| `NEWS_DISCOVERY` | current_evidence | 10 080 | ≤ 7 d | 7–14 d | 14–28 d | > 28 d |
| `EPPO_FUEL`, `BOT_FX` | context | 10 080 | ≤ 7 d | 7–14 d | 14–28 d | > 28 d |
| `IMF_PORTWATCH`, `FBX_PUBLIC` | context | 20 160 | ≤ 14 d | 14–28 d | 28–56 d | > 56 d |
| `GSCPI` | context | 52 560 | ≤ 36.5 d | 36.5–73 d | 73–146 d | > 146 d |
| `WB_COMMODITY` | context | 89 280 | ≤ 62 d | 62–124 d | 124–248 d | > 248 d |
| `TH_CUSTOMS`, `MPA_SG_STATISTICS`, `PAT_STATISTICS` | context | 105 120 | ≤ 73 d | 73–146 d | 146–292 d | > 292 d |
| `UNCTAD_MARITIME` | context | 262 080 | ≤ 182 d | 182–364 d | 364–728 d | > 728 d |

**`expected_cadence_minutes` is `null` for every one of the four official-notice channels
(`PAT_NOTICE`, `ACP_ADVISORY`, `SCA_CIRCULAR`, `MPA_SG_NOTICE`), for the two hazard-alert
channels (`GDACS`, `TMD_CAP`), and for `MANUAL_NOTICE_INTAKE`** — see `docs/known_data_gaps.md`
§11 for the precise statement (it is not quite "every L1 source": `NEWS_DISCOVERY`, an
automated discovery channel rather than a notice-issuing authority, has a non-null value
reflecting its own polling interval). This "unknown publisher cadence" position is the real
state of every source through which this platform could actually publish a current-evidence
claim today, and it is one of `mode_situation`'s standing `confidence_reductions`.

## 4. Development-level `evidence_grade`

`analysis/grading.py::compute_evidence_grade` computes `logistics_event.evidence_grade`
(`CONFIRMED | CORROBORATED | REPORTED | ANALYTICAL_INFERENCE | null`) from the eligible claim
set `Q(E)` — every claim in the event's `claim_ids` that is `current_publication`-dataset,
`review_status: approved`, not superseded, from a Document whose source has
`governance.enabled_for_public_claims: true`, with `strength_basis: verified`. Evaluated in
order, first match wins:

1. **CONFIRMED** — at least one strength-A claim of type `verified_fact`/`official_notice`,
   authoritative, fresh, uncontradicted.
2. **CORROBORATED** — not CONFIRMED, and the modal `assertion_group_id` is backed by ≥2
   independence groups at strength A or B, with no disqualifying claim type.
3. **REPORTED** — a reporting-class claim from a `current_evidence`- or `context`-layer
   Document, ≥1 independence group.
4. **ANALYTICAL_INFERENCE** — everything else with a non-empty `Q(E)`.
5. **`null`** — `Q(E)` is empty, or every eligible claim is a `discovery_lead`.

Two caps then apply, worse result wins (§2.7 of design part 1): an unresolved `existence`/
`status_change` contradiction on the core assertion caps CONFIRMED/CORROBORATED at REPORTED;
the freshness clock caps a `stale` contributor at REPORTED and an `ageing` one at CORROBORATED
(from CONFIRMED). `grade_override` (`logistics_event.schema.json`, new) may only move the grade
*down* the order `CONFIRMED > CORROBORATED > REPORTED > ANALYTICAL_INFERENCE > null` — an
upward or lateral override fails `scripts/validate.py`'s dedicated rule
(`analysis/grading.py::grade_override_problems`).

Worth stating plainly, because it is not the intuitive shape: **the grade ladder is not
monotone in document count.** One primary, authoritative, fresh, uncontradicted official notice
reaches CONFIRMED on its own — CORROBORATED needs ≥2 independence groups, which a single
publisher's notice can never supply, however many times it is quoted. Adding a second
*syndicated* report of the same notice leaves the grade at CONFIRMED; adding a second
*independent* publisher's confirmation also leaves it at CONFIRMED (nothing ranks above it) but
raises `mode_situation`'s `confidence`. CORROBORATED is a rung a single-source pilot skips
entirely, by design.

### `situation_state` transitions

`analysis/grading.py::compute_situation_state` proposes one of the five values this Work Order's
pilot can reach (`EMERGING`, `ACTIVE`, `DEVELOPING`, `UNCERTAIN`, `RESOLVED`; `STABLE`/`EASING`
are on the schema from WO-047 but their transition triggers are not implemented here). Every
transition is a proposal a human record approves, except `UNCERTAIN`, which fires autonomously
because it can only ever increase caution — an unresolved `existence`/`status_change`
contradiction, or a contributing claim past its freshness window. `RESOLVED` additionally stays
behind the pre-existing G-13 gate, `analysis/claims.py::resolved_situation_state_problems`,
unchanged.

## 5. `mode_situation`: Gate 0 and the five statuses

`analysis/situations.py::compute_mode_situation` computes one `mode_situation.schema.json`
record per `(mode, geography)` pair — today, exactly one target,
`{mode: sea, geography_id: GEO-CTY-TH, country_code: TH}`
(`scripts/build_situations.py::_SITUATION_TARGETS`) — written to
`data/situations/situations.json`. It is computed deterministically from already-approved
`logistics_event`/`claim`/`document` records; it is never authored directly, and it consumes
the existing nine-area `impact_assessment` machinery rather than recomputing it.

### Gate 0 — eight conditions, five reused verbatim

An event contributes only if all eight hold:

| # | Condition | Source |
|---|---|---|
| 1–5 | Current-surface, lifecycle-eligible, not closed/ended, backed by publishable evidence, activity confirmed with a basis | `analysis/events.py::is_active_at`, reused **verbatim** |
| 6 | `situation_state ∈ {EMERGING, ACTIVE, DEVELOPING, STABLE, EASING}`, **or** `UNCERTAIN` with an unresolved `existence`/`status_change` contradiction (in which case it contributes to rule 2 only) | `analysis/situations.py::_situation_state_eligible` |
| 7 | `freshness_state ∈ {fresh, ageing}` (the *worst* state among the event's `Q(E)` claims) | `analysis/situations.py::_event_freshness_state` |
| 8 | A geography link to the target country: `country_code` in the event's `country_ids`, or a node/chokepoint on a Lane whose `country_ids` include it, or a matching `lane_relevance` entry | `analysis/situations.py::_has_thailand_link` |

Every event Gate 0 rejects lands in `excluded_event_ids` with a human-readable reason —
`is_active_at`'s own reason string for conditions 1–5, a dedicated string for 6–8. On the real
repository, all ten committed events are `dataset: historical_validation` and are excluded at
condition 1, exactly as `data/situations/situations.json` shows today.

### The five statuses — first match wins, no arithmetic

| Order | `status` | Fires when |
|---|---|---|
| 1 | `confirmed_disruption` | An eligible CONFIRMED event has an `observed` impact area at severity ≥ moderate, is `fresh`, and carries no capping contradiction |
| 2 | `mixed_evidence` | An eligible event carries an unresolved `existence`/`status_change` contradiction |
| 3 | `elevated_watch` | An eligible CONFIRMED/CORROBORATED/REPORTED event has a `potential`/`elevated_watch` area at severity ≥ moderate; **or a CONFIRMED event whose nine areas are all still `insufficient_evidence`**; or an event that met rule 1 but has drifted to `ageing` |
| 4 | `no_material_impact_detected` | ≥1 eligible event has `negative_operational_evidence: true` and an area at `no_material` with a `no_material_basis`, **and** the coverage minimum (≥1 qualifying Document from an `enabled_for_public_claims`, `current_evidence`-layer source within its freshness window) is met |
| 5 | `insufficient_current_evidence` | Default — no eligible event, or the coverage minimum is unmet |

Rule 3's second clause is the one that matters most for this Work Order: **a CONFIRMED
Development whose nine impact areas are all still `insufficient_evidence` — the honest,
unassessed state of a brand-new Development — yields `elevated_watch`, never silence and never
a false `confirmed_disruption`.** It is what makes a real current-situation output reachable
without a review-package round trip: `data/situations/situations.json`'s single committed
record is `insufficient_current_evidence` today only because there is no real Document yet
(item 9, deferred); feeding it one qualifying CONFIRMED Development with unassessed impact areas
changes the answer to `elevated_watch` by this same rule, with no other code path.

`confidence` (`low`/`medium`/`high`) starts from the status and is stepped down by an unresolved
contradiction among contributing evidence, by a not-fully-fresh contributor, or by a single
independence group; it is stepped up by ≥2 independence groups; and every step is named in
`confidence_reductions`, never left implicit.

### The explainability walk

Every `mode_situation` record with a non-`insufficient_current_evidence` status must satisfy,
with no null link:

```
status → status_basis[].event_id → logistics_event.evidence_grade → logistics_event.claim_ids
       → claim.document_id → document.source_id (resolves in config/sources.yaml)
       → document.canonical_url (non-null)
```

Enforced by `analysis/situation_validation.py::explainability_walk_problems`, wired into
`scripts/validate.py`, and proven with both a genuine failing fixture (a Document with no
`canonical_url`; an unresolved `source_id`) and a genuine passing one in
`tests/test_validate_situation_rules.py`.

## 6. The `conflicting_evidence[]` extension

Seven additive fields on `logistics_event.conflicting_evidence[]` (all 10 committed events carry
`conflicting_evidence: []`, so none is touched): `contradiction_type` (8-value enum — only
`existence` and `status_change` cap the grade and force `UNCERTAIN`; the other six are recorded
and displayed without degrading anything), `claim_ids_side_a`/`claim_ids_side_b`,
`independence_groups_a`/`independence_groups_b`, `first_detected_at`/`last_reviewed_at`, and
`resolution_basis` (required, non-empty, whenever `resolution_status != "unresolved"` — no
contradiction may leave `unresolved` without a stated reason, and none may be resolved without
one either). Two additive `resolution_status` values: `escalated_for_verification`,
`resolved_as_status_change`.

**The status-change-vs-contradiction rule** (`analysis/situation_validation.py::
is_status_change`, design part 2 §3.6's hardest rule): a newer claim that opposes an older one
is a *status change*, not a contradiction, iff it is strictly newer by `published_at`, its
`claim_type ∈ {official_notice, verified_fact, denial_or_correction}`, and its publisher's
`authority_scope` covers the assertion. Otherwise it is a contradiction and stays `unresolved`
until a human decides. `tests/test_validate_situation_rules.py`'s
`status_change_classification_problems` proves this both ways: a mislabelled bare, unnamed news
report marked `status_change` is caught; a genuine authoritative newer notice is not.

## 6a. The `impact_assessment` basis-field rule (item 8, made a genuine checked rule)

Each of the four new `impact_assessment` fields (§1 item 8) is optional and nullable on the
schema itself. Three of them additionally carry a "required by `scripts/validate.py`
convention" description on the schema field — that convention is enforced by
`analysis/situation_validation.py::impact_assessment_basis_problems`, wired into
`scripts/validate.py` alongside the other event-semantics checks: `watch_trigger` is required
whenever `status: elevated_watch`, `no_material_basis` whenever `status: no_material`,
`not_relevant_basis` whenever `status: not_relevant` — but **only for a
`current_publication`-dataset event.** Nine of the 90 assessments WO-047 already committed use
`status: no_material` with no basis recorded (all on `EVT-20240614-002`, a
`historical_validation`-dataset fixture predating these fields); scoping the rule to
`current_publication` keeps that fixture valid while still holding every assessment this
platform could actually publish today to the convention its own schema field claims.

## 7. What is deliberately not built here

- **`gaps[]` is always `[]`.** WO-045's `#ocean-major-gaps` derivation is a Dashboard-facing
  mechanism this Work Order does not touch; `mode_situation.gaps` is reserved for it.
- **Development↔Development relatedness** (rule 2's second clause — two distinct events with
  opposed predicate classes over the same node/chokepoint) is not computed; only a single
  event's own unresolved `conflicting_evidence` is checked.
- **Clustering rules S1/S5/S6/S7/S8** and any merge/split engine — `analysis/attachment.py`
  implements only rules 3, 6 and 7 of design part 1 §1.4 (attach to the one Development, or
  leave honestly unattached). See the module's own docstring for why building more now would
  repeat `analysis/events.py::should_cluster`'s fate — a second engine nothing calls.
- **The Daily Brief** and any Dashboard change of any kind — `dashboard/public/**` and
  `scripts/build_dashboard.py` are untouched by this Work Order; `mode_situation` is computed
  and validated under `data/`, not rendered.
