# News, official notices and the event lifecycle

**Work Order:** WO-010 Gate G · **Status:** implemented
**Contracts:** `schemas/logistics_event.schema.json`, `schemas/event_evidence.schema.json`
**Logic:** `analysis/events.py`

## 1. Three event classes, separated at the contract level

| Class | What it is | What it may do |
|---|---|---|
| `direct_operational_event` | A Logistics operational event: port or terminal closure, port restriction, canal restriction, carrier rerouting, service suspension, capacity withdrawal, strike, customs or system outage, surcharge or fee change, sanction or regulation, reported congestion | May carry an impact conclusion when its chain is complete and its evidence supports it |
| `external_driver` | War and security, economic change, energy shock, trade policy, political decision, weather or natural hazard | **Contextual until a transmission mechanism is stated.** May carry an impact conclusion only with a complete chain |
| `discovery_lead` | An unconfirmed lead from a discovery source | May be displayed. May **never** carry a conclusion |

The separation is enforced: `analysis/events.py::external_driver_admission` returns
`False` for an external driver with an incomplete chain, and `validate_event` rejects any
material impact on such an event.

## 2. Evidence lifecycle

`lifecycle_status` takes one of eight values:

```
discovery_lead → reported_event → verified_event → operational_impact_observed
                                ↘ potential_impact → monitoring
                                ↘ insufficient_evidence          (terminal, legitimate)
                                                     → closed    (terminal, needs a basis)
```

`insufficient_evidence` and `closed` are legitimate terminal answers, not failures. A closed
event **must** record a `closure_basis`; `validate_event` rejects one that does not.

## 3. What every event retains

Event date, publication date, retrieval date, geography, node and chokepoint references,
modes, per-lane relevance with its basis, Thailand relevance with its basis, evidence
references, conflicting evidence, the transmission chain and its computed completeness,
nine-area impact assessments, event severity (separate from impact severity), lifecycle
status, last-reviewed time, closure basis, human-review state and clustering inputs.

Thailand relevance may be `none_established` — and when it is, the Dashboard says the
platform found no basis to assess an effect, which is different from finding there is none.

## 4. The transmission chain

```
external driver → operational change → Logistics mechanism → observable indicator → outcome
```

Completeness is **computed from which links are present**, never asserted by the author.
`validate_event` compares the declared `completeness` against the computed one and rejects a
mismatch.

Required links differ by class, deliberately:

- **External driver** — all five. A driver with no operational change is context.
- **Direct operational event** — the last four. It *is* the operational change, so requiring
  an upstream driver would force authors to invent a cause.
- **Discovery lead** — none. Its completeness is `not_applicable`: a lead is not an
  incomplete conclusion, it is not yet a conclusion at all.

## 5. Evidence roles

`event_evidence.schema.json` requires `evidence_role`:

| Role | Meaning |
|---|---|
| `confirming` | May support a material conclusion |
| `contextual` | Adds context; does not carry a conclusion |
| `discovery_only` | Structurally barred from being the sole support for a material impact |

The role survives promotion from intake to event evidence — a discovery lead stays a
discovery lead, which is the point of carrying the role through the intake layer.

Claims are capped at 600 characters by the contract and by both intake paths, so a full
copyrighted article can never enter the repository. `raw_snapshot_path` is always null in
the public repository.

## 6. Conflicting evidence

Where sources disagree, both positions are preserved in `conflicting_evidence` with a
`resolution_status` of `unresolved`, `resolved_by_primary_source`, `superseded` or
`confidence_reduced`. The platform does not silently select a preferred answer. Conflicts
are carried into the ChatGPT review package as a first-class field.

## 7. Deterministic clustering

`analysis/events.py::should_cluster` applies four rules in decreasing strength:

1. **Same source record** — same `source_id` and same non-null `source_record_id`.
2. **Same canonical URL** — after lower-casing scheme and host, stripping user-info, the
   default port, tracking parameters and the fragment, sorting remaining parameters, and
   removing a trailing slash.
3. **Same entity, type, date and geography** — matching `operator_or_entity` plus matching
   event type, event date and overlapping geography.
4. **Controlled title similarity ≥ 0.60** — Jaccard over normalized tokens, and **only**
   when event type, event date and geography already match.

Rules 3 and 4 both require type, date and geography first. **Two events never merge merely
because they concern the same country or the same conflict** — asserted directly by
`test_same_country_alone_does_not_cluster` and `test_same_conflict_alone_does_not_cluster`.

`cluster_key` is a SHA-256 over event type, event date, sorted geography, operator and
normalized title. `validate_event` recomputes it and rejects a record whose stored key does
not match, so a tampered or stale key cannot survive validation.

## 8. Current state

Eight events are recorded, all expanded from the authored historical validation cases: five
direct operational events, two external drivers (one admitted, one contextual) and one
discovery lead. Ten evidence items support them, every one carrying the publisher's original
URL and an explicit statement that the content was not retrieved under WO-010.
