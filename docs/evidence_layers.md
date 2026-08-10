# Evidence layers: L1 / L2 / L3 (WO-047)

**Work Order:** WO-047 · **Issue:** [#89](https://github.com/beer598623/Logistics-Situation-Platform/issues/89)
**Design reference:** [Issue #88 comment 2](https://github.com/beer598623/Logistics-Situation-Platform/issues/88#issuecomment-5235496493)
Section 3.2 (the L3 firewall), Section 3.3 (source layering).
**Contracts:** `schemas/document.schema.json`, `schemas/claim.schema.json`,
`schemas/source_contract.schema.json#/$defs/governance`
**Logic:** `analysis/claims.py::l3_firewall_problems`

## 1. Why this axis exists, and why it is not `dataset`

The platform already has a publication-surface axis, `dataset`
(`current_publication`/`technical_demo`/`historical_validation` — see
`docs/evidence_provenance_and_datasets.md`). `evidence_layer` answers a different question:
*regardless of which publication surface a record sits on, how current is what the source
itself is reporting?*

A statistical baseline series (say, a global supply-chain pressure index) can legitimately be
`current_publication`-dataset and still describe *context*, not a current operational event. A
historical research paper about how port outages generally propagate to feeder schedules can
never be current-publication evidence of any specific event, however carefully it is filed.
Conflating the two axes would let a context-layer or research-layer source masquerade as
current operational evidence simply by sitting in the right file. Keeping them orthogonal
prevents that.

## 2. The three layers

| Layer | Meaning | May it support a current condition? |
|---|---|---|
| `current_evidence` (L1) | The source reports operational conditions, hazards or events directly — an official notice, an advisory, a news report of a named primary source, a discovery lead | Yes, subject to the usual corroboration/grading rules |
| `context` (L2) | A periodic statistical or benchmark series, or a characterisation, used as background for interpretation — not a direct report of an operational event | Only as context; never alone establishes that an event happened |
| `structural_research` (L3) | Historical or structural research about *how the system behaves in general* — never about a specific current event | **Never.** L3 material may supply the *mechanism* for a transmission chain, but can never establish that anything is currently happening |

`evidence_layer` is set on the Document (inherited from the source's registry
`governance.evidence_layer`, overridable **downward only** — e.g. a normally L1 publisher's
opinion piece recorded as L2), then **copied onto every Claim built from it and frozen there**.
A later registry reclassification can never retroactively promote an already-published L3
claim to L1 — this is what "frozen on the claim" buys.

## 3. The L3 firewall

Four points from Issue #88 comment 2 Section 3.2, restated against what this Work Order
actually implements:

1. **`evidence_layer` is frozen on the Claim at creation.** A future change to a source's
   registry-default layer cannot retroactively reclassify a claim already built from it.
2. **An L3 claim can never appear as a verified fact.** Enforced by
   `analysis/claims.py::l3_firewall_problems` rule 1: a claim whose `evidence_layer` is
   `structural_research` must never appear in an event's `verified_facts` array, regardless of
   its own `claim_type`.
3. **An L3-only claim set cannot make a Development "active".** Enforced by rule 2: an event
   whose *entire* (non-empty) `claim_ids` set is `structural_research`-layer may not carry a
   `situation_state` other than absent or `UNCERTAIN`.
4. **L3 material may supply mechanism, never occurrence.** A Claim × Document →
   `event_evidence` projection of an L3 claim always derives `evidence_role: contextual`
   (`analysis/claim_evidence_adapter.py::_evidence_role`) — it can inform a transmission
   chain's `logistics_mechanism` link, but is excluded from grading (see the item-level
   `strength` derivation, which always grades an L3 claim `D`).

Both rules are proven with passing and failing synthetic fixtures in
`tests/test_validate_claim_rules.py` (`test_l3_claim_in_verified_facts_fails` /
`test_l3_only_claim_set_with_active_situation_state_fails` and their passing counterparts), and
wired into `scripts/validate.py`'s "Documents and Claims" section.

## 4. No L3 source is currently registered

**Zero of the 18 sources in `config/sources.yaml` are assigned `governance.evidence_layer:
structural_research`.** 8 are `current_evidence`, 10 are `context`; see
`docs/known_data_gaps.md` §10 for the full breakdown and consequence. The L3 firewall exists
and is tested — it has simply never had a real record to fire on, because no
historical-research-paper or structural-analysis publisher has been qualified for this
platform yet.

## 5. Relationship to item-level evidence grading

`evidence_layer` is a coarse, three-value classification made at the Document/Claim level.
The item-level `event_evidence.strength` (A–D) and the Development-level `evidence_grade`
(`CONFIRMED`/`CORROBORATED`/`REPORTED`/`ANALYTICAL_INFERENCE`, on `schemas/logistics_event.
schema.json` as an optional, derived field) are finer-grained and computed from the full claim
set, not from `evidence_layer` alone. `evidence_layer` is a **ceiling**: an L3 claim is always
graded `D` at the item level and can never contribute to a grade above `ANALYTICAL_INFERENCE`
at the Development level — but an L1 (`current_evidence`) claim is not automatically graded
`A`; it still has to earn it (primary, authoritative, fresh, uncontradicted, verified).

**Full Development-level grade computation was built by WO-049** (Issue #92) —
`analysis/claim_evidence_adapter.py`'s item-level `_full_strength` (reading registry
`authoritative_for`/`publisher_authority` coverage via `authority_covers()`, the freshness
window via `freshness_state()`, and `claim.contradiction_status`) and
`analysis/grading.py::compute_evidence_grade` (the pure function over a Development's eligible
claim set). See `docs/situation_synthesis.md` §§3–4 for the full rule tables, the real
per-source freshness numbers, and why the grade ladder is deliberately not monotone in document
count. The WO-047 placeholder heuristic this section originally described still runs, unchanged,
but only for fixture-context Documents (`evidence_origin` in `{synthetic_test_fixture,
historical_validation_fixture}`) — kept that way specifically so the three committed round-trip
fixtures in `tests/test_claim_evidence_adapter.py` (acceptance A-2) keep grading exactly as
they did before WO-049.
