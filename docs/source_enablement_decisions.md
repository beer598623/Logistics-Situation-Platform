# Source enablement decisions

**Work Order:** WO-010 Gate C · **Decision date:** 2026-07-24

One decision per source. Every one of them is the same decision, for reasons recorded per
source in `config/sources.yaml` and summarised in `docs/source_qualification_report.md`.

## Decision summary

| Source | Decision | Primary reason |
|---|---|---|
| `TH_CUSTOMS` | **Keep disabled** | No stable machine-readable export confirmed; no live validation; reuse terms unreviewed |
| `EPPO_FUEL` | **Keep disabled** | Client-rendered page, extraction path unconfirmed; no live validation; reuse terms unreviewed |
| `GSCPI` | **Keep disabled** | No published download URL confirmed by observation; no live validation; reuse terms unreviewed |
| `BOT_FX` | **Keep disabled** | Requires an API key; no credential-handling mechanism exists and WO-010 introduces none |
| `WB_COMMODITY` | **Keep disabled** | Published as XLSX; no XLSX parser exists and none is added. No fixture test |
| `IMF_PORTWATCH` | **Keep disabled** | No ArcGIS query endpoint confirmed; no live validation; republication position unresolved |
| `UNCTAD_MARITIME` | **Keep disabled** | No stable download URL confirmed; no live validation; reuse terms unreviewed |
| `PAT_NOTICE` | **Keep disabled** | No machine-readable feed confirmed; cadence unknown so no schedule can be justified |
| `ACP_ADVISORY` | **Keep disabled** | Same, plus advisories are commonly PDF and no PDF parser exists |
| `SCA_CIRCULAR` | **Keep disabled** | Same |
| `MPA_SG_NOTICE` | **Keep disabled** | No machine-readable feed confirmed; reuse terms unreviewed |
| `MANUAL_NOTICE_INTAKE` | **Keep disabled** | The path exists and is tested, but no notice has been recorded through it, so it currently contributes no coverage |
| `NEWS_DISCOVERY` | **Keep disabled** | No query endpoint confirmed; reuse terms unreviewed. Discovery-only in any case |
| `TMD_CAP` | **Unchanged, disabled** | Outside the Bundle 1 source core. Governed by Issue #15; WO-010 must not modify it |
| `GDACS` | **Unchanged, disabled** | Outside the Bundle 1 source core. Same |

## What was done instead of enabling

Per the Work Order's fallback rules (Section 8), each blocked source was handled as follows
rather than halting the bundle:

1. **Kept disabled**, with `live_validation_status: not_performed`.
2. **Exact unresolved issue recorded** in `enablement.blockers` — not a general "pending",
   but the specific thing that is missing.
3. **Fixture-first adapter implemented** where useful. Twelve of the thirteen Bundle 1
   candidates have a named fixture test, referenced from their own enablement record so the
   claim is checkable. `WB_COMMODITY` does not, and says so.
4. **Bounded manual intake implemented** for official notices with no machine-readable feed
   (`MANUAL_NOTICE_INTAKE`).
5. **Live coverage marked insufficient** everywhere it surfaces.
6. **Contracts, tests, analysis, review package and Dashboard behaviour implemented in
   full**, so the capability is reviewable even though the data is not live.
7. **No invented operational values.** Every synthetic value carries
   `evidence_class: synthetic_test_fixture` and a limitation stating it is not a published
   statistic.

## What would change each decision

| Source | To enable, a reviewer must additionally |
|---|---|
| `TH_CUSTOMS` | Confirm a stable machine-readable export URL by controlled live test; read and record the reuse and redistribution terms |
| `EPPO_FUEL` | Confirm a machine-readable extraction path; read and record reuse terms |
| `GSCPI` | Confirm the published file URL; read and record reuse terms |
| `BOT_FX` | Decide how an API key is stored and injected without entering the repository, then validate |
| `WB_COMMODITY` | Add an XLSX parser (out of WO-010 scope), write its fixture test, then validate |
| `IMF_PORTWATCH` | Confirm the feature-service query URL and rate limits; resolve whether derived daily estimates may be republished or only linked |
| `UNCTAD_MARITIME` | Confirm a stable download URL; read and record reuse terms |
| Notice channels | Confirm a machine-readable feed **or** commit to the manual intake path; establish cadence before configuring any schedule |
| `NEWS_DISCOVERY` | Confirm the query endpoint and rate limits; confirm link-level redistribution is permitted |
| `TMD_CAP`, `GDACS` | Out of scope. A separate Work Order and their own governance records apply |

## Schedule policy

`expected_cadence_minutes` is null for every notice channel, so `schedule_justified` is
`false` and **no automated collection schedule is configured for any of them**. Unknown
cadence means no automated schedule until cadence is justified — that rule is applied, not
merely stated. Monthly sources record a monthly, manually triggered schedule; nothing in
this repository polls a monthly source more often than monthly.

## Governance

- The enablement gate is enforced by `scripts/validate.py`, so a source cannot be flipped to
  `enabled: true` while a blocker remains without failing CI.
- `AGENTS.md` already forbids enabling a source whose `machine_readable_status` is not
  `verified` or whose `licence_status` is not `reviewed`. WO-010 does not weaken that rule.
- Live source contact remains confined to the human-triggered `manual-live-source-test`
  workflow.
