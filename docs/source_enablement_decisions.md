# Source enablement decisions

**Work Order:** WO-010 Gate C · **Decision date:** 2026-07-24

One decision per source. Every one of them is the same decision, for reasons recorded per
source in `config/sources.yaml` and summarised in `docs/source_qualification_report.md`.

## Decision summary

| Source | Decision | Primary reason |
|---|---|---|
| `TH_CUSTOMS` | **Keep disabled** (WO-010, research carried by WO-029) | No stable machine-readable export confirmed; the mode-bearing candidate host (`catalog.customs.go.th`) has never delivered a byte (WO-029, environment access blocker); reuse terms unreviewed |
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
| `MPA_SG_STATISTICS` | **Keep disabled** (WO-026, extended WO-027 Parts A-D) | Reuse terms are the platform's first `reviewed` licence position, and the endpoint/field names are human-confirmed (WO-027 Part A) and now live-executed (WO-027 Part B, 2026-07-31); `container_throughput`'s unit/scale remains unverified and fail-closed by deliberate decision after reconciliation (WO-027 Part C) found strong but not primary-source-confirmed corroboration; enablement is a separate, later decision |
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
| `TH_CUSTOMS` | Reach `catalog.customs.go.th` (allowlisted but has never delivered a byte — TLS resets before any response, WO-029) and read the `ctm_06_18`/`ctm_06_17` field contract; decide whether to re-point `TH_CUSTOMS` at it or register a separate `TH_CUSTOMS_MODE` id; read and record reuse and redistribution terms |
| `EPPO_FUEL` | Confirm a machine-readable extraction path; read and record reuse terms |
| `GSCPI` | Confirm the published file URL; read and record reuse terms |
| `BOT_FX` | Decide how an API key is stored and injected without entering the repository, then validate |
| `WB_COMMODITY` | Add an XLSX parser (out of WO-010 scope), write its fixture test, then validate |
| `IMF_PORTWATCH` | Confirm the feature-service query URL and rate limits; resolve whether derived daily estimates may be republished or only linked |
| `UNCTAD_MARITIME` | Confirm a stable download URL; read and record reuse terms |
| Notice channels | Confirm a machine-readable feed **or** commit to the manual intake path; establish cadence before configuring any schedule |
| `NEWS_DISCOVERY` | Confirm the query endpoint and rate limits; confirm link-level redistribution is permitted |
| `PAT_STATISTICS` | Reach `catalog.port.co.th` (allowlisted but TLS resets before any response on all attempts so far, WO-032) and read its field contract and DataStore status directly, not via the `datagov.mot.go.th` mirror; resolve the container-unit contradiction between Bangkok (TEU) and Laem Chabang (boxes, self-contradicting its own multiplier field) from primary text, plausibly requiring a human to read the JPEG-format data dictionary; identify the specific Open Data Commons variant behind `license_id: "Open Data Common"` (`license_url` is currently null) and confirm it permits republication |
| `FBX_PUBLIC` | Confirm which figures are publicly reusable versus subscription-only; record route scope, unit and redistribution position before any value is committed |
| `MPA_SG_STATISTICS` | WO-027 Part B (live validation) is done. The personal-data check is only *partially* done: none of the fields the field-projected Part B requests actually returned can carry personal data, but that projected response cannot itself confirm either resource's complete schema — the broader confirmation still rests on the earlier human primary-source dataset-page reading (`docs/mpa_sg_statistics_qualification.md` §1 item 4), and a corresponding `enablement.blockers` entry remains. Remaining: that full-schema confirmation, plus a separately-authorized primary-source read of data.gov.sg's own field/dataset unit documentation for `container_throughput` — the scale-elimination reconciliation against official MPA annual totals (WO-027 Part C) corroborates but does not itself confirm the unit, so `unit_verified` stays `False` until that primary-source read happens |
| `TMD_CAP`, `GDACS` | Out of scope, and explicitly excluded from WO-010-R1. A separate Work Order and their own governance records apply. Neither was contacted |

## Schedule policy

`expected_cadence_minutes` is null for every notice channel, so `schedule_justified` is
`false` and **no automated collection schedule is configured for any of them**. Unknown
cadence means no automated schedule until cadence is justified — that rule is applied, not
merely stated. Monthly sources record a monthly, manually triggered schedule; nothing in
this repository polls a monthly source more often than monthly.

## The enablement gate (hardened by WO-010-R1)

`scripts/validate.py::source_contract_checks` blocks `enabled: true` unless **every** one of
these holds. Each is covered by a negative test in
`tests/test_current_publication_boundary.py`, so a gate that stops being enforced fails CI.

**Qualification**

| Gate | Requirement |
|---|---|
| `access_cost` | `free` or `free_with_registration`. `paid` is refused outright under the free-only policy |
| `paywall_status` | not `full` |
| `reuse_status` | reviewed — not null, `unknown` or `restricted` |
| `redistribution_status` | resolved — not null, `unknown` or `prohibited` |
| `prototype_eligibility` | exactly `eligible` |
| `observed_freshness` | recorded from an independent observation, not a claimed cadence alone |
| `publication_cadence` | recorded |

**Enablement**

| Gate | Requirement |
|---|---|
| `blockers` | empty |
| `machine_readable_status` | `verified` |
| `licence_status` | `reviewed` |
| `endpoint` | present |
| `fixture_test_exists` / `fixture_test_reference` | both present, and the reference names a real test |
| `live_validation_status` | `completed` with a cited `live_validation_reference`, or `not_required` **only** for a genuinely manual, non-network contract |
| `parser_fails_closed` | true |
| `response_bounded` | true |
| `schedule_justified` | true |
| `public_repository_safe` | true |

Series compatibility is checked separately: a series' source must declare a logistics role
compatible with what the series measures, every `source_id` and `intended_source_id` must
exist in the registry, and one series may never resolve to two sources.

### Publication use (WO-010-R2)

`reuse_status` answered "may we read this". The platform was acting on "may we
republish this". Those are different permissions, and every source now records
the second separately as `qualification.publication_use`:
`raw_values_permitted`, `derived_values_only`, `bounded_claim_and_link_only`,
`metadata_link_only`, `internal_validation_only` or `publication_prohibited`.

Validation enforces the disposition against the source's own terms, for every
source whether enabled or not: it may not exceed what `redistribution_status`
allows, an `unknown` reuse status permits nothing beyond a metadata link, an
enabled source that may publish nothing is a contradiction, an unresolved rate
limit cannot justify a collection schedule, and an allowed manual intake must
require every record to name the underlying publisher.

**Current dispositions.** Every source whose redistribution position is
unresolved records `internal_validation_only`: not knowing whether republication
is permitted is not permission. `MANUAL_NOTICE_INTAKE` records
`bounded_claim_and_link_only` and is the one allowed manual intake path —
`manual_intake_status: allowed`, `underlying_publisher_required: true` — so a
human-reviewed notice can reach the current view without the source being
enabled. `NEWS_DISCOVERY` records `metadata_link_only`.

Applying the rate-limit rule surfaced six sources (`EPPO_FUEL`, `BOT_FX`,
`IMF_PORTWATCH`, `NEWS_DISCOVERY`, `PAT_STATISTICS`, `FBX_PUBLIC`) that claimed
a justified collection schedule while their rate limits were unresolved. All six
now record `schedule_justified: false` and carry the blocker that explains it.

**All seventeen sources remain disabled under WO-010-R1 and WO-010-R2.** No
source was contacted.

## Governance

- The enablement gate is enforced by `scripts/validate.py`, so a source cannot be flipped to
  `enabled: true` while a blocker remains without failing CI.
- `AGENTS.md` already forbids enabling a source whose `machine_readable_status` is not
  `verified` or whose `licence_status` is not `reviewed`. WO-010 does not weaken that rule.
- Live source contact remains confined to the human-triggered `manual-live-source-test`
  workflow.
