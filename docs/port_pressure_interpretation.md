# Port pressure interpretation limitations

**Work Order:** WO-010 Gate F · **Status:** implemented and enforced

## 1. The rule

**Port throughput growth does not prove congestion.** A volume metric measures how much
cargo moved. It says nothing about how long anything waited.

Permitted wording, in increasing strength:

| Wording | Requires |
|---|---|
| *Volume pressure* | A throughput or port-call series moving against its documented threshold |
| *Elevated operational risk* | A structural exposure, e.g. a lane transiting a chokepoint with an open notice |
| *Official disruption notice* | A notice published by the operating authority |
| *Congestion supported by operational evidence* | A source that directly measures an operational condition — waiting time, berth occupancy |
| *Insufficient evidence* | Anything less |

## 2. Claims the platform never makes

Truck delay, berth delay, yard congestion, and real-time port congestion are **never**
claimed, because no source in the registry measures any of them and none is monitored live.

This is checked mechanically. `tests/test_dashboard_build.py::test_congestion_language_only_ever_appears_as_a_disclaimer`
splits every dashboard payload into sentences and requires that any sentence containing
"congestion", "congested", "berth delay", "yard congestion", "truck delay" or "real-time"
also contains a negation — so the words can appear in a disclaimer or a limitation, and
nowhere else.

## 3. How the contract carries the distinction

`schemas/port_transport_observation.schema.json` requires `operational_interpretation` on
every record:

| Value | Meaning |
|---|---|
| `volume_only` | Measures how much moved. Can **never** on its own support a congestion, delay or capacity-shortage conclusion |
| `operational_condition` | Directly measures an operational condition such as waiting time or berth occupancy |
| `service_quality` | Measures service outcome such as schedule reliability |
| `structural_capacity` | Measures structural capability rather than current condition |

`scripts/validate.py` forces `container_throughput`, `cargo_throughput` and `vessel_calls`
to be recorded as `volume_only`. A record claiming otherwise fails validation.

The threshold rule that reads these series, `PORT-VOLUME-YOY-V1`, states in its own
description that it measures volume only and that congestion is never produced by it. A
test asserts that wording is present.

## 4. Currently registered port series

| Series | Metric | Interpretation | Resolution |
|---|---|---|---|
| `laem_chabang_container_throughput` | container throughput | `volume_only` | node |
| `bangkok_port_container_throughput` | container throughput | `volume_only` | node |
| `thailand_port_calls` | vessel calls | `volume_only` | country |

All three are currently derived from labelled synthetic fixtures. **No
`operational_condition` series is registered at all**, which is precisely why no congestion
statement is made.

## 5. The one case where congestion is asserted, and why

Historical validation case HVC-004 (elevated waiting times at Singapore) records
`capacity: observed` at moderate severity. That conclusion rests on an **operational-condition
notice from the port authority**, not on throughput. The case's own limitation says so
directly:

> Supported by an operational-condition notice from the port authority. Port call counts
> alone would not have supported this conclusion: throughput measures how much moved, not
> how long anything waited.

The case also records that estimated port calls did **not** fall during the period — the
pressure was invisible in volume data. That is the whole point of the case: it checks that
the platform reaches a congestion conclusion only through the right kind of evidence.

## 6. Estimates versus reported statistics

`IMF_PORTWATCH` figures are model-derived estimates from vessel tracking, not
port-authority reported throughput. They are labelled as estimates in the source contract's
limitations and must never be presented as official port statistics.
