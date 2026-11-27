# ADR-0003: schema evolution (v1/v2) and unit handling
## Status
Accepted (hackathon)
## Context
Meters send two payload versions: v1 (meter_id, ts, energy, status, register) and v2
(+ voltage, firmware). Energy arrives in the meter's native unit — mostly Wh, ~15% of
meters report kWh. Billing needs one unit, and double conversion (kWh/1000) would
silently under-bill by 1000x.
## Decision
- Bronze stores the payload untouched + a per-event `schema_version` (payload field,
  else inferred from the presence of v2 fields).
- Silver has ONE superset schema: `voltage`/`firmware` are nullable (null for v1).
  An unknown `schema_version` (not 1|2) → quarantine `BAD_SCHEMA`.
- Unit: the event's `unit` field wins; `ref.dim_meter.unit` is the fallback when the
  field is absent. If both are present and disagree, or the unit is not Wh|kWh, the row
  is ambiguous → quarantine `BAD_SCHEMA`. Conversion happens in exactly one function
  (`src/silver/normalise.py::to_kwh`), called once per value, on energy and register alike.
- `source_unit` is kept on `silver.meter_readings` so every conversion is auditable.
## Options considered
- A. Separate silver tables per version — doubles downstream joins; rejected.
- B. Superset table with nullable v2 columns — simple, additive for a future v3; **chosen**.
- C. Trust the master flag only — breaks when a meter is re-flashed to report kWh; rejected
  in favour of event-first with a disagreement check.
## Consequences
- Adding v3 fields = add nullable columns; old rows unaffected.
- A meter master error surfaces as BAD_SCHEMA quarantine rows instead of wrong kWh.
- Verified on the seed: 0 mismatches between energy_kwh and raw energy for both units.
