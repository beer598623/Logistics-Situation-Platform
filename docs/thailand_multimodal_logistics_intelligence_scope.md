# Thailand-Centric Multimodal Logistics Intelligence — Scope and Architecture

**Work Order:** WO-009A
**Authorized baseline:** `7039b0b4513f3469a6ce649cb1e845a36e359a2a`
**Execution type:** Architecture, governance and documentation reset only

## 1. Status

This document is the binding architecture baseline for the platform, superseding the prior
broad hazard-oriented implementation priority. It replaces no historical evidence: WO-002
through WO-008 technical evidence, decisions, and Issue history remain valid and unchanged.
WO-009A does not implement source ingestion, live collection, AI automation, or Dashboard
screens. No Phase 1 implementation is authorized until this document receives independent
review and acceptance.

## 2. Product decision and scope

**Product:** Thailand-Centric Multimodal Logistics Intelligence & Outlook Dashboard.

**Primary analytical question:**

> How are Logistics flows into, out of and within Thailand changing, and what current or
> emerging events may affect routes, capacity, time, cost, service and continuity?

The platform uses Thailand as the primary analytical viewpoint while covering Logistics
connections to global origins, destinations, transport corridors, and external events. The
platform may cover any country, port, airport, chokepoint, or corridor when it has a
plausible relationship with Thailand Logistics.

The initial implementation priority is **Ocean Logistics**, selected for data availability
and operational relevance. Ocean is the first module, not the permanent limit of the
product — see Section 5 (Multimodal roadmap).

## 3. Approved product principles

The following are binding project principles. They apply to every layer, module, and future
Work Order unless a later, explicitly authorized Work Order revises them.

### 3.1 Thailand-centric

Every analytical object (Lane, event, indicator, outlook) must be evaluable for its
relationship to Thailand Logistics, even when its geography is elsewhere.

### 3.2 Multimodal

The common architecture must support Ocean and port Logistics, Air cargo, Road freight,
Rail freight, Border and cross-border flows, and inland connections and warehouse context.
No module may be designed in a way that structurally excludes another mode.

### 3.3 Logistics-first

Core indicators and events must concern Logistics directly: trade and cargo flow, port
throughput, vessel and transport activity, freight capacity, transport availability, transit
time and delay, service reliability, border and customs operations, fuel/freight/Logistics
cost pressure, and port/airport/road/rail/carrier operational notices.

### 3.4 Externally informed

External events (war and security, sanctions, economic change, energy and commodity
shocks, trade regulation, political decisions, weather and natural hazards) may be included
only as context. An external event must not be labelled as a Logistics impact without a
stated transmission mechanism or operational evidence.

**Required reasoning chain:**

```
External driver → operational change → Logistics mechanism → observable indicator → impact or scenario
```

Every material conclusion that links an external driver to a Logistics outcome must show
each link in this chain explicitly, or must be presented as an unresolved hypothesis rather
than a conclusion.

### 3.5 Evidence-linked

The platform must distinguish, for every material conclusion:

- Verified fact
- Official notice or forecast
- Reported claim
- Analytical inference
- Scenario
- Confirmed operational impact
- Conflicting evidence
- Insufficient evidence

Every material conclusion must retain source and freshness information (source identity,
retrieval time, publication time, known limitations).

### 3.6 Scenario-based

The platform must not present unsupported point predictions as facts. Outlooks should
normally contain: base case, deterioration case, improvement case, time horizon, trigger
conditions, confidence, and data gaps.

### 3.7 Free-only

The public Prototype must maintain:

```
Paid-source dependency = 0
```

Core sources and infrastructure must use only free public data, free APIs, free
registration where acceptable, public CSV/XLSX/JSON/XML/RSS, public official notices,
publicly readable news or operator statements, open-source software, free
public-repository hosting and automation within applicable limits, and human-triggered
ChatGPT analysis. Paid sources may be recorded only as optional discovery leads — see
`docs/source_priority_framework.md` Priority 4. They must not be necessary to verify or
publish a conclusion.

## 4. Public Intelligence Core versus Private Decision Overlay

The architecture separates two environments. This boundary is binding for every future
Work Order.

### 4.1 Public Intelligence Core

Organization-neutral information: trade trends, port and transport activity, public freight
benchmarks, fuel and FX context, operational events, lane assessments, scenario outlooks,
and general preparedness options. This may be stored in the public repository when
licensing permits.

### 4.2 Private Decision Overlay

Optional future local-only inputs: shipment plans, freight quotations, booking and cut-off
dates, container demand, tractor availability, turnaround time, warehouse capacity,
inventory exposure, and customer commitments. **Private data must not be committed to the
public repository.**

The public core may identify operational pressure. Company-specific resource decisions
require private operational inputs supplied outside the public repository (see Phase 7 in
`docs/thailand_multimodal_logistics_mvp_roadmap.md`).

## 5. Multimodal roadmap (module coverage)

The common architecture must support all of the following, though they are implemented in
phases (see `docs/thailand_multimodal_logistics_mvp_roadmap.md`):

- Sea
- Air
- Road
- Rail
- Border and cross-border transport
- Import
- Export
- Domestic freight
- Cost and capacity context
- Logistics operational news
- Relevant economic, geopolitical, regulatory and energy drivers

Ocean is the first operational module because of data availability and operational
relevance. Its data model, entity names, and conventions must remain generalizable to Air,
Road, Rail, and Border modules — no Ocean-only assumption may be hard-coded into a shared
entity (see Section 7).

## 6. Data-layer architecture

The platform is organized into four connected layers.

### Layer 1 — Logistics Baseline

Thailand import and export; port throughput; domestic freight by mode; global and regional
trade; maritime activity and connectivity; air-cargo demand and capacity; fuel and
commodity prices; exchange rates; Logistics cost; global supply-chain pressure.

### Layer 2 — Logistics Operational Events

Port or terminal closure; port congestion supported by operational evidence; canal
restriction; carrier rerouting; airport or cargo-terminal interruption; road, rail or border
closure; strike; customs or booking-system outage; sanction or trade restriction; capacity
withdrawal; surcharge or fee change.

### Layer 3 — External Drivers

Geopolitical conflict; macroeconomic change; energy shock; regulation; weather or natural
hazards. These remain contextual until linked to a Logistics mechanism (Section 3.4).

### Layer 4 — Assessment and Outlook

Current situation; observed impact; potential impact; Thailand relevance; lane relevance;
transmission mechanism; near-term scenarios; evidence strength; confidence; triggers;
preparedness options; known limitations.

## 7. Lane-centred analytical model

A **Lane** is a primary analytical object. It may represent: Thailand to a destination
country; Thailand to a port or airport group; Thailand through a chokepoint; Thailand to a
regional market; a cross-border corridor; or a domestic port-to-inland connection.

**Minimum Lane attributes:**

- Origin
- Destination
- Mode
- Geography
- Relevant ports, airports, borders or inland nodes
- Chokepoints
- Trade-flow indicators
- Capacity indicators
- Cost indicators
- Active operational events
- External drivers
- Current assessment
- Scenario outlook
- Confidence
- Data gaps

The first Ocean module should later select approximately 8–12 high-priority Lane groups.
**This Work Order does not select them.** Lane selection is a Phase 2 (Ocean MVP) activity.

## 8. Minimum common data architecture (conceptual)

The following conceptual entities define the shared data architecture across all modes and
phases. **No database migrations or implementation code are created under WO-009A** — these
are named and described only, for future Phase 1 implementation.

| Entity | Role |
|---|---|
| `dim_source` | Registry of every data source: identity, access method, licence status, freshness contract, known limitations. |
| `dim_geography` | Country/region/administrative geography reference. |
| `dim_country` | Country reference, including Thailand-relevance flags. |
| `dim_transport_mode` | Sea, Air, Road, Rail, Border/cross-border, inland. |
| `dim_logistics_node` | Ports, airports, border crossings, inland terminals, warehouse hubs. |
| `dim_lane` | Lane definitions per Section 7. |
| `dim_chokepoint` | Straits, canals, and other bottleneck geographies relevant to one or more lanes. |
| `fact_indicator_observation` | Layer 1 baseline indicator observations (trade, cost, capacity, FX, fuel, pressure indices). |
| `fact_trade_observation` | Trade-flow-specific observations (import/export volumes and values). |
| `fact_port_or_transport_observation` | Port throughput, vessel activity, transport-mode-specific operational observations. |
| `fact_cost_observation` | Freight, fuel, and Logistics cost observations. |
| `fact_event` | Layer 2/3 event records (operational events and external drivers). |
| `fact_event_evidence` | Evidence items supporting a `fact_event` (source, retrieval time, evidence class per Section 3.5). |
| `fact_lane_assessment` | Layer 4 current-situation assessment per lane. |
| `fact_impact_assessment` | Layer 4 observed/potential impact assessment, always evidence-linked (Section 3.5) and never asserting an unsupported operational impact. |
| `fact_preparedness_option` | Conditional preparedness options (Public Core, organization-neutral only). |
| `fact_source_health` | Per-source freshness/availability status, distinct from `dim_source`'s static contract fields. |
| `fact_assessment_history` | Historical record of assessments and outlooks, to preserve auditability and avoid silent revision. |

## 9. External-driver admission rules

An external driver (Layer 3) may be admitted into a Lane assessment or outlook only when a
Logistics mechanism can be stated. The required chain (Section 3.4) must be shown:

```
External driver → operational change → Logistics mechanism → observable indicator → impact or scenario
```

If any link in the chain is missing, the driver must be recorded as contextual only (Layer
3) and must not be presented as a Logistics impact. Conflicting or insufficient evidence
must be recorded explicitly (Section 3.5), never silently omitted or resolved by inference.

## 10. AI role and Human Review boundary

**ChatGPT's approved role** (human-triggered only, per the free-only principle, Section
3.7):

- Summarize source-backed changes
- Cluster related reports
- Separate facts, claims and inference
- Identify conflicting evidence
- Build transmission chains (Section 3.4/9)
- Assess Lane and Thailand relevance
- Produce scenario-based outlooks (Section 3.6)
- Generate conditional preparedness options
- Identify data gaps

**ChatGPT must not:**

- Invent missing exposure
- Treat missing data as zero
- Produce unsupported causal claims
- Present an external hazard as an operational impact without linkage
- Present a freight proxy as an actual shipment quotation
- Claim real-time congestion without real-time operational evidence
- Automatically publish High or Critical assessments
- Provide mandatory instructions for every organization
- Use private information (Section 4.2) in the public core
- Rely on paid sources for a material conclusion

**Human Review boundary:** any High or Critical assessment requires human review before
publication. This boundary is binding regardless of which module or phase produces the
assessment.

## 11. Dashboard information architecture (planned modules)

The following modules are the planned Dashboard information architecture. **No Dashboard
pages are created under WO-009A.**

1. Thailand Logistics Situation
2. Ocean Logistics
3. Air Cargo
4. Land, Rail and Border
5. Trade and Flow
6. Cost and Freight Pressure
7. Events and External Drivers
8. AI Outlook and Preparedness
9. Sources and Methodology

Innovation Radar is deferred outside the MVP. A general weather Dashboard is outside the
MVP.

## 12. Related documents

- `docs/thailand_multimodal_logistics_mvp_roadmap.md` — implementation phases and MVP
  acceptance criteria.
- `docs/source_priority_framework.md` — source-priority matrix and free-only qualification
  framework.
- `methodology/project_scope.md` — prior methodology-level scope statement; this document
  narrows and supersedes its product-priority framing without invalidating its independence
  and public-source constraints.
- `methodology/source_policy.md` — general source-priority ordering; refined for Logistics
  by `docs/source_priority_framework.md`.
- `docs/gdacs_tmd_cap_pilot.md`, `docs/tmd_rss_discovery_hardening.md`,
  `docs/tmd_candidate_cap_validation.md`, `docs/tmd_candidate_evidence_contract.md`,
  `docs/source_health_and_event_identity.md` — prior technical evidence, retained unchanged
  as historical record (see Section 13).

## 13. Relationship to prior hazard-oriented work (WO-002 through WO-008)

This scope reset changes the platform's **implementation priority**, not its historical
record. GDACS and TMD_CAP technical evidence, adapters, and governance history (WO-002
through WO-008, Issue #15) remain valid and are not deleted, edited, or reinterpreted by
this document. TMD's disposition is addressed separately in the Issue #15 scope-reset
comment required by WO-009A Section 9; see that comment for the current TMD status. GDACS
remains disabled and is described in this architecture as an optional external hazard
signal (Layer 3), not a first-phase core Logistics source.
