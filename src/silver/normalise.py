"""Silver normalisation rules — pure functions, no DB (unit-testable with crafted rows).

Applied in order to each bronze event (CLAUDE.md §4/§5/§7):
  1. parse            missing/ill-typed field, bad schema_version, ts not on a
                      15-min boundary -> BAD_SCHEMA; unparseable value -> UNPARSEABLE
  2. ts -> UTC        reading_date is the UTC date of reading_ts (not the landing folder)
  3. meter master     meter_id not in ref.dim_meter -> UNKNOWN_METER
  4. UNIT RULE        event `unit` wins, master unit is the fallback; disagreement or
                      unknown unit -> BAD_SCHEMA (ambiguous). Wh / 1000 exactly once.
  5. energy < 0       -> NEGATIVE_ENERGY
  6. dedupe           (meter_id, reading_ts): first by bronze_event_id kept,
                      the rest -> DUPLICATE
  7. order + register per meter by reading_ts; register below the last accepted
                      register without a rollover flag -> REGISTER_DECREASE_NO_ROLLOVER
  8. gaps             every master meter expects 96 slots per UTC day; runs of slots
                      without a valid reading -> gaps. NEVER filled.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

INTERVAL = dt.timedelta(minutes=15)
SLOTS_PER_DAY = 96
WH_PER_KWH = Decimal(1000)
VALID_UNITS = ("Wh", "kWh")
REQUIRED = ("meter_id", "ts", "energy", "register")


@dataclass
class Reading:
    meter_id: str
    reading_ts: dt.datetime
    feeder_id: str
    zone_id: str
    energy_kwh: Decimal
    register_kwh: Decimal
    source_unit: str
    status: str | None
    voltage: Decimal | None
    firmware: str | None
    schema_version: int
    rollover: bool
    bronze_event_id: int
    raw: dict = field(repr=False)
    source_file: str | None = None

    @property
    def reading_date(self) -> dt.date:
        return self.reading_ts.date()


@dataclass
class Quarantined:
    reading_date: dt.date
    reason_code: str
    detail: str
    raw: dict
    meter_id: str | None = None
    reading_ts: dt.datetime | None = None
    bronze_event_id: int | None = None
    source_file: str | None = None


@dataclass
class Gap:
    meter_id: str
    interval_start: dt.datetime
    interval_end: dt.datetime  # exclusive
    missing_intervals: int
    feeder_id: str | None = None
    zone_id: str | None = None

    @property
    def reading_date(self) -> dt.date:
        return self.interval_start.date()


# --- helpers --------------------------------------------------------------
def to_kwh(value: Decimal, unit: str) -> Decimal:
    """Convert a native-unit value to kWh. Wh / 1000; kWh unchanged. Called ONCE."""
    if unit == "Wh":
        return value / WH_PER_KWH
    if unit == "kWh":
        return value
    raise ValueError(f"unknown unit {unit!r}")


def parse_ts_utc(value) -> dt.datetime:
    """ISO-8601 -> aware UTC datetime. Naive timestamps are taken as UTC."""
    if not isinstance(value, str):
        raise TypeError("ts is not a string")
    t = dt.datetime.fromisoformat(value.strip())
    if t.tzinfo is None:
        return t.replace(tzinfo=dt.UTC)
    return t.astimezone(dt.UTC)


def _num(value, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} is not numeric: {value!r}")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not numeric: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"{name} is not finite: {value!r}")
    return d


def _aligned(t: dt.datetime) -> bool:
    return t.second == 0 and t.microsecond == 0 and t.minute % 15 == 0


# --- rules 1-5: one event -------------------------------------------------
def parse_event(
    raw,
    meters: dict[str, dict],
    *,
    bronze_event_id: int | None = None,
    source_file: str | None = None,
    fallback_date: dt.date,
    bronze_schema_version: int | None = None,
) -> Reading | Quarantined:
    """Apply rules 1-5 to one raw event. Returns a Reading or a Quarantined."""

    def q(reason: str, detail: str, meter_id=None, ts=None) -> Quarantined:
        return Quarantined(
            reading_date=ts.date() if ts else fallback_date,
            reason_code=reason,
            detail=detail[:300],
            raw=raw if isinstance(raw, dict) else {"value": raw},
            meter_id=meter_id,
            reading_ts=ts,
            bronze_event_id=bronze_event_id,
            source_file=source_file,
        )

    # 1. shape
    if not isinstance(raw, dict):
        return q("BAD_SCHEMA", "event is not a JSON object")
    missing = [k for k in REQUIRED if raw.get(k) is None]
    meter_id = raw.get("meter_id")
    meter_id = meter_id if isinstance(meter_id, str) and meter_id else None
    if missing:
        return q("BAD_SCHEMA", f"missing fields: {missing}", meter_id)
    if meter_id is None:
        return q("BAD_SCHEMA", "meter_id is not a non-empty string")
    # payload field wins; else bronze's recorded version; else infer as bronze does
    sv = raw.get("schema_version", bronze_schema_version)
    if "schema_version" not in raw and sv is None:
        sv = 2 if ("voltage" in raw or "firmware" in raw) else 1
    if sv not in (1, 2) or isinstance(sv, bool):
        return q("BAD_SCHEMA", f"schema_version not 1|2: {sv!r}", meter_id)

    # 1/2. values + UTC
    try:
        ts = parse_ts_utc(raw["ts"])
    except (TypeError, ValueError) as exc:
        return q("UNPARSEABLE", f"ts: {exc}", meter_id)
    try:
        energy = _num(raw["energy"], "energy")
        register = _num(raw["register"], "register")
        voltage = (
            _num(raw["voltage"], "voltage") if raw.get("voltage") is not None else None
        )
    except (TypeError, ValueError) as exc:
        return q("UNPARSEABLE", str(exc), meter_id, ts)
    if not _aligned(ts):
        return q(
            "BAD_SCHEMA", f"ts not on a 15-min boundary: {raw['ts']}", meter_id, ts
        )

    # 3. meter master
    master = meters.get(meter_id)
    if master is None:
        return q("UNKNOWN_METER", f"{meter_id} not in ref.dim_meter", meter_id, ts)

    # 4. UNIT RULE
    ev_unit = raw.get("unit")
    if ev_unit is None:
        unit = master["unit"]
    elif ev_unit not in VALID_UNITS:
        return q("BAD_SCHEMA", f"unknown unit {ev_unit!r}", meter_id, ts)
    elif ev_unit != master["unit"]:
        return q(
            "BAD_SCHEMA",
            f"ambiguous unit: event={ev_unit} master={master['unit']}",
            meter_id,
            ts,
        )
    else:
        unit = ev_unit
    energy_kwh = to_kwh(energy, unit)
    register_kwh = to_kwh(register, unit)

    # 5. negative energy
    if energy_kwh < 0:
        return q("NEGATIVE_ENERGY", f"energy_kwh={energy_kwh}", meter_id, ts)

    firmware = raw.get("firmware")
    return Reading(
        meter_id=meter_id,
        reading_ts=ts,
        feeder_id=master["feeder_id"],
        zone_id=master["zone_id"],
        energy_kwh=energy_kwh,
        register_kwh=register_kwh,
        source_unit=unit,
        status=raw.get("status"),
        voltage=voltage,
        firmware=firmware if isinstance(firmware, str) and firmware else None,
        schema_version=int(sv),
        rollover=raw.get("rollover") is True,
        bronze_event_id=bronze_event_id if bronze_event_id is not None else 0,
        raw=raw,
        source_file=source_file,
    )


# --- rule 6 ---------------------------------------------------------------
def dedupe(readings: list[Reading]) -> tuple[list[Reading], list[Quarantined]]:
    """Keep the first copy per (meter_id, reading_ts) by bronze_event_id."""
    kept: dict[tuple[str, dt.datetime], Reading] = {}
    dups: list[Quarantined] = []
    for r in sorted(readings, key=lambda r: r.bronze_event_id):
        key = (r.meter_id, r.reading_ts)
        first = kept.get(key)
        if first is None:
            kept[key] = r
            continue
        dups.append(
            Quarantined(
                reading_date=r.reading_date,
                reason_code="DUPLICATE",
                detail=f"duplicate of bronze_event_id={first.bronze_event_id}",
                raw=r.raw,
                meter_id=r.meter_id,
                reading_ts=r.reading_ts,
                bronze_event_id=r.bronze_event_id,
                source_file=r.source_file,
            )
        )
    return list(kept.values()), dups


# --- rule 7 ---------------------------------------------------------------
def order_and_check_register(
    readings: list[Reading], prev_register: dict[str, Decimal] | None = None
) -> tuple[list[Reading], list[Quarantined]]:
    """Order by (meter_id, reading_ts); quarantine unflagged register decreases.

    prev_register: meter_id -> last accepted register_kwh before this batch
    (e.g. the previous day's last silver reading) for cross-day continuity.
    """
    last = dict(prev_register or {})
    ok: list[Reading] = []
    bad: list[Quarantined] = []
    for r in sorted(readings, key=lambda r: (r.meter_id, r.reading_ts)):
        before = last.get(r.meter_id)
        if before is not None and r.register_kwh < before and not r.rollover:
            bad.append(
                Quarantined(
                    reading_date=r.reading_date,
                    reason_code="REGISTER_DECREASE_NO_ROLLOVER",
                    detail=f"register_kwh {r.register_kwh} < previous {before}",
                    raw=r.raw,
                    meter_id=r.meter_id,
                    reading_ts=r.reading_ts,
                    bronze_event_id=r.bronze_event_id,
                    source_file=r.source_file,
                )
            )
            continue
        ok.append(r)
        last[r.meter_id] = r.register_kwh
    return ok, bad


# --- rule 8 ---------------------------------------------------------------
def find_gaps(
    readings: list[Reading], meters: dict[str, dict], day: dt.date
) -> list[Gap]:
    """Runs of 15-min slots on `day` (UTC) with no valid reading, per master meter."""
    present: dict[str, set[dt.datetime]] = {}
    for r in readings:
        present.setdefault(r.meter_id, set()).add(r.reading_ts)
    day_start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    slots = [day_start + i * INTERVAL for i in range(SLOTS_PER_DAY)]
    gaps: list[Gap] = []
    for meter_id in sorted(meters):
        have = present.get(meter_id, set())
        run_start: dt.datetime | None = None
        count = 0
        for s in slots + [None]:  # sentinel closes a trailing run
            if s is not None and s not in have:
                if run_start is None:
                    run_start, count = s, 0
                count += 1
                continue
            if run_start is not None:
                gaps.append(
                    Gap(
                        meter_id=meter_id,
                        interval_start=run_start,
                        interval_end=run_start + count * INTERVAL,
                        missing_intervals=count,
                        feeder_id=meters[meter_id].get("feeder_id"),
                        zone_id=meters[meter_id].get("zone_id"),
                    )
                )
                run_start = None
    return gaps


# --- whole day ------------------------------------------------------------
@dataclass
class DayResult:
    readings: list[Reading]
    quarantine: list[Quarantined]
    gaps: list[Gap]


def normalise_day(
    events: list[dict],
    meters: dict[str, dict],
    day: dt.date,
    prev_register: dict[str, Decimal] | None = None,
) -> DayResult:
    """Run rules 1-8 for one UTC day.

    events: dicts with keys raw, bronze_event_id, source_file, source_date,
    schema_version. Events whose UTC reading_date != day are ignored (they
    belong to another day's build); unparseable-ts events fall back to
    source_date.
    """
    readings: list[Reading] = []
    quarantine: list[Quarantined] = []
    for ev in sorted(events, key=lambda e: e["bronze_event_id"]):
        res = parse_event(
            ev["raw"],
            meters,
            bronze_event_id=ev["bronze_event_id"],
            source_file=ev.get("source_file"),
            fallback_date=ev.get("source_date") or day,
            bronze_schema_version=ev.get("schema_version"),
        )
        if res.reading_date != day:
            continue
        (readings if isinstance(res, Reading) else quarantine).append(res)

    readings, dups = dedupe(readings)
    readings, decreases = order_and_check_register(readings, prev_register)
    quarantine += dups + decreases
    quarantine.sort(key=lambda x: (x.bronze_event_id or 0, x.reason_code))
    return DayResult(readings, quarantine, find_gaps(readings, meters, day))
