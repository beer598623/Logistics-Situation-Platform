# Historical analytical validation cases and results

**Work Order:** WO-010 Gate J, extended by WO-039 (HVC-009) and WO-041 (HVC-010) · **Status:** implemented, 10/10 cases pass
**Authored cases:** `data/validation/historical_cases.json`
**Runner:** `scripts/run_historical_validation.py` · **Report:** `data/validation/validation_report.json`

<!-- historical-validation-metrics: cases=10 impacts_assessed=90 material_impacts=21 insufficient_evidence_uses=60 -->
<!-- The marker above is checked against data/validation/validation_report.json by
     tests/test_documentation_registry_coverage.py so this doc's counts cannot drift
     silently again the way they did between WO-039 and WO-041 (see WO-042). -->

## 1. What this validates

Gate J asks whether the intelligence workflow reaches the *right* conclusion on cases whose
outcome is already documented. The runner replays each authored case through the same
`analysis/` code the live pipeline uses, and compares the result against expectations the
case declares up front: transmission completeness, Thailand relevance, lane relevance,
evidence classification, per-area impact disposition, and whether human review is required.

Several cases exist specifically to check that the platform reaches a **negative** answer
when the evidence supports one. A validation set in which everything is an impact would test
nothing.

## 2. No hindsight leakage

Each case records `assessment_cutoff` and `facts_known_at_cutoff`. The expectations are
compared only against what the case itself records at its own cutoff, so later knowledge
cannot inform the assessment. Each case additionally records its
`hindsight_limitation` — what was genuinely unknown at the time and must not be used.

**Evidence content was not retrieved under WO-010.** No source was reachable from the
execution environment, so each evidence item carries the publisher's original URL for
independent verification, `evidence_class: historical_validation_fixture`, and an explicit
statement that the content was not retrieved. Content hashes cover this repository's record
of the claim, not a retrieved publisher response.

## 3. The ten cases

| Case | Event | Cutoff | Class | Chain | Thailand relevance | Lanes | Result |
|---|---|---|---|---|---|---|---|
| `HVC-001` | Red Sea / Suez rerouting | 2024-01-15 | direct operational event | complete | medium | 3 | **pass** |
| `HVC-002` | Panama Canal transit restrictions | 2023-11-15 | direct operational event | complete | low | 1 | **pass** |
| `HVC-003` | Baltimore bridge collapse | 2024-04-05 | direct operational event | complete | **none established** | 2 | **pass** |
| `HVC-004` | Singapore elevated waiting times | 2024-06-10 | direct operational event | complete | medium | 5 | **pass** |
| `HVC-005` | Crude and product price shock | 2022-06-30 | external driver | complete | medium | 16 | **pass** |
| `HVC-006` | Baltic subsea cable damage | 2024-12-01 | external driver | **incomplete** | **none established** | 1 | **pass** |
| `HVC-007` | Pasir Panjang oil spill | 2024-06-20 | direct operational event | complete | low | 5 | **pass** |
| `HVC-008` | Unverified SE Asia terminal lead | 2026-07-24 | discovery lead | **not applicable** | **none established** | 0 | **pass** |
| `HVC-009` | Pakistan airspace closure / Thailand–Europe air services | 2019-03-06 | direct operational event | complete | medium | 5 | **pass** |
| `HVC-010` | Malaysia MCO closes the Thailand–Malaysia land border to general movement | 2020-03-18 | direct operational event | complete | medium | 6 | **pass** |

`HVC-005`'s lane count grew from 11 to 16 without any change to the case itself: it carries
`modes: ["sea", "road", "multimodal"]` from its original WO-010 authoring, so once WO-041
registered Land lanes, the five new Road lanes sharing its `country_ids` legitimately entered
its lane relevance at country-membership strength — the same registry-membership pattern
`HVC-009` already demonstrated for Air. This is expected behaviour, not drift in the case.

### Case mix against the Gate J requirement

| Required mixture | Case |
|---|---|
| Rerouting or chokepoint disruption | HVC-001 (Red Sea / Suez), HVC-002 (Panama) |
| Port restriction or closure | HVC-003 (Baltimore), HVC-007 (Pasir Panjang) |
| Congestion or capacity event | HVC-004 (Singapore) |
| Cost / energy pressure | HVC-005 (price shock) |
| Thailand relevance indirect or not established | HVC-003, HVC-006 |
| Insufficient evidence is the correct result | HVC-006, HVC-008 |
| No material impact is the correct result | HVC-007 |
| Airspace closure and Air-mode propagation | HVC-009 |
| Border closure and Land-mode propagation, with no Ocean or Air leakage | HVC-010 |

### What each negative case is for

- **HVC-003 — Baltimore.** A large, well-reported port closure with no established Thailand
  service relationship. The correct answer is `insufficient_evidence` across every impact
  area, **not** `no_material`: the platform has not assessed and disproved a Thailand effect,
  it has found no basis to assess one. The case checks that a big event does not manufacture
  a transmission chain.
- **HVC-006 — Baltic cables.** A widely reported security event with no operational change
  at any port, terminal, canal or carrier. Chain incomplete → contextual only, no impact
  conclusion, no lane admitted.
- **HVC-007 — Pasir Panjang.** The one legitimate use of `no_material`: an actual
  assessment against explicit negative operational evidence, where the operating authority
  stated navigation and berthing were unaffected.
- **HVC-008 — discovery lead.** Checks that a lead is representable, visible, and
  structurally unable to support any conclusion.
- **HVC-004 — Singapore.** Checks that a congestion conclusion comes from an
  operational-condition notice and never from throughput. The case explicitly records that
  port-call estimates did *not* fall during the period — the pressure was invisible in
  volume data.
- **HVC-009 — Pakistan airspace closure.** The Air foundation's end-to-end proof case: an
  `airspace_closure` event resolves to `LANE-AIR-TH-EUR` through the airspace chokepoint that
  lane actually records (`CHK-SASIA-AIRSPACE`), and to no Ocean lane at all. Transport and
  service impacts, backed by the operator's own cancellation announcement, are `observed`;
  capacity and cost consequences stay `potential` with the gap named, never quantified from a
  source the platform does not hold. No `air-freight-pass`, AEROTHAI or passenger-traffic
  figure is used anywhere in the record.
- **HVC-010 — Malaysia MCO border closure.** The Land foundation's end-to-end proof case,
  proving two things at once. First, that a border closure is not a freight stoppage: goods
  movement was expressly exempted at Bukit Kayu Hitam under reduced staffing, so
  `import_export` resolves `potential`, never `observed`, everywhere in the record. Second,
  that mode scoping holds for Land exactly as it does for Air: the event carries
  `country_ids: ["TH","MY"]`, which every Ocean lane touching Malaysia also carries, yet
  tagged `modes: ["road","border"]` it resolves `LANE-ROAD-TH-MY` and
  `LANE-BORDER-TH-CROSSINGS` at `medium` relevance (via `NODE-THSDK`/`CHK-THSDK-BKH`) and the
  other three cross-border/domestic Road lanes at `low` (via country membership only), and
  resolves **no Ocean lane and no Air lane at all**.

## 4. Measured behaviours

Measured across all ten cases at once, 90 impact assessments in total:

| Measure | Result |
|---|---|
| Traceability rate | **1.0** — every impact's evidence references resolve |
| Impacts assessed | 90 |
| Material impacts | 21 |
| Unsupported-causation count | **0** |
| Unsupported-causation rate | **0.0** |
| Geography leakage count | **0** — no lane relevance without a shared reference entity |
| Missing-as-zero count | **0** |
| Insufficient-evidence uses | 60 |
| No-material uses | 9 |
| No-material without negative evidence | **none** |
| Material impact on discovery-only evidence | **none** |
| Material impact on an inadmissible driver | **none** |
| Scenario completeness rate | **1.0** across all 11 lane outlooks |
| Scenario problems | none |
| Preparedness overreach count | **0** |

### Event / impact separation

Event severity and impact severity are stored as separate fields and neither is inferred
from the other. Six cases demonstrate them genuinely diverging:

- `EVT-20190227-001` — event severity high, worst impact severity moderate
- `EVT-20200318-001` — event severity high, worst impact severity moderate
- `EVT-20231030-001` — event severity moderate, worst impact severity low
- `EVT-20231218-001` — event severity high, worst impact severity moderate
- `EVT-20240326-001` — event severity **high**, worst impact severity **none**
- `EVT-20240614-002` — event severity low, worst impact severity none

The Baltimore case is the clearest: a high-severity event with no Thailand impact severity
at all. If severity were being inferred, those two numbers could not differ.

## 5. Running it

```bash
python scripts/run_historical_validation.py              # prints per-case results
python scripts/run_historical_validation.py --write-report   # also refreshes the report
```

`tests/test_derived_outputs.py::test_historical_validation_passes` runs it in CI.

## 6. Known limitation of this validation

These cases validate the **workflow**, not the platform's live accuracy. They are authored
records of what was publicly known at each cutoff, with evidence content not retrieved. They
demonstrate that the analysis code reaches the documented conclusion from the documented
inputs; they cannot demonstrate that live collection would produce those inputs, because no
source is enabled.

## 7. How these cases are kept out of the current view (WO-010-R1)

Every record built from a historical case is marked so the current-publication code can
exclude it without knowing anything about cases:

| Record | Marking |
|---|---|
| Event | `dataset: historical_validation`, `active_as_of: null`, `active_basis: null` |
| Evidence | `evidence_origin: historical_validation_fixture`, `retrieval_status: not_retrieved`, `retrieved_at: null` |
| Evidence hash | `content_hash_scope: authored_claim_record` — the hash covers the claim text this repository wrote, not any publisher response |
| Evidence source | `source_id: SYNTHETIC_FIXTURE` with `intended_source_id` naming the publisher a real implementation would use |
| Evidence strength | `strength_basis: expected_at_cutoff` — the strength a qualified source *would* have carried, recorded separately from a strength verified against a retrieved document |

On the Dashboard these appear only in panels headed "Historical validation", each showing
the case ID and the assessment cutoff it was assessed at. They contribute nothing to a
current direction, attention level, active event or chokepoint notice, and
`scripts/validate.py` fails the build if they ever do.

See `docs/evidence_provenance_and_datasets.md` for the full vocabulary.
