# Historical analytical validation cases and results

**Work Order:** WO-010 Gate J · **Status:** implemented, 8/8 cases pass
**Authored cases:** `data/validation/historical_cases.json`
**Runner:** `scripts/run_historical_validation.py` · **Report:** `data/validation/validation_report.json`

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

## 3. The eight cases

| Case | Event | Cutoff | Class | Chain | Thailand relevance | Lanes | Result |
|---|---|---|---|---|---|---|---|
| `HVC-001` | Red Sea / Suez rerouting | 2024-01-15 | direct operational event | complete | medium | 3 | **pass** |
| `HVC-002` | Panama Canal transit restrictions | 2023-11-15 | direct operational event | complete | low | 1 | **pass** |
| `HVC-003` | Baltimore bridge collapse | 2024-04-05 | direct operational event | complete | **none established** | 2 | **pass** |
| `HVC-004` | Singapore elevated waiting times | 2024-06-10 | direct operational event | complete | medium | 5 | **pass** |
| `HVC-005` | Crude and product price shock | 2022-06-30 | external driver | complete | medium | 11 | **pass** |
| `HVC-006` | Baltic subsea cable damage | 2024-12-01 | external driver | **incomplete** | **none established** | 1 | **pass** |
| `HVC-007` | Pasir Panjang oil spill | 2024-06-20 | direct operational event | complete | low | 5 | **pass** |
| `HVC-008` | Unverified SE Asia terminal lead | 2026-07-24 | discovery lead | **not applicable** | **none established** | 0 | **pass** |

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

## 4. Measured behaviours

Measured across all eight cases at once, 72 impact assessments in total:

| Measure | Result |
|---|---|
| Traceability rate | **1.0** — every impact's evidence references resolve |
| Impacts assessed | 72 |
| Material impacts | 11 |
| Unsupported-causation count | **0** |
| Unsupported-causation rate | **0.0** |
| Geography leakage count | **0** — no lane relevance without a shared reference entity |
| Missing-as-zero count | **0** |
| Insufficient-evidence uses | 52 |
| No-material uses | 9 |
| No-material without negative evidence | **none** |
| Material impact on discovery-only evidence | **none** |
| Material impact on an inadmissible driver | **none** |
| Scenario completeness rate | **1.0** across all 11 lane outlooks |
| Scenario problems | none |
| Preparedness overreach count | **0** |

### Event / impact separation

Event severity and impact severity are stored as separate fields and neither is inferred
from the other. Four cases demonstrate them genuinely diverging:

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
