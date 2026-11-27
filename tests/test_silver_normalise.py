"""Unit tests for silver normalisation rules (src/silver/normalise.py).

Pure functions, crafted rows, no database. Test names state the rule and the
result. Rules: CLAUDE.md §4 (UNIT/TIME/GAPS), §5 (DQ), §7 (defect mechanisms).
Feature code is not modified by these tests.
"""

import datetime as dt
import random
from decimal import Decimal

import pytest

from src.silver.normalise import (
    SLOTS_PER_DAY,
    Quarantined,
    Reading,
    dedupe,
    find_gaps,
    normalise_day,
    order_and_check_register,
    parse_event,
    to_kwh,
)

DAY = dt.date(2025, 9, 1)
UTC = dt.UTC
METERS = {
    "MWH": {"unit": "Wh", "feeder_id": "F01", "zone_id": "Z01"},
    "MKWH": {"unit": "kWh", "feeder_id": "F01", "zone_id": "Z01"},
}


def ev(meter="MWH", ts="2025-09-01T00:00:00Z", energy=1500, register=9000, **extra):
    e = {"meter_id": meter, "ts": ts, "energy": energy, "register": register}
    e.update(extra)
    return e


def parse(raw, meters=METERS, **kw):
    kw.setdefault("fallback_date", DAY)
    return parse_event(raw, meters, **kw)


def slot(i, day=DAY):
    return dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + i * dt.timedelta(minutes=15)


def ts_str(i, day=DAY):
    return slot(i, day).strftime("%Y-%m-%dT%H:%M:%SZ")


def reading(meter="MWH", i=0, register="10", rollover=False, eid=1, energy="0.1"):
    r = parse(ev(meter, ts_str(i), energy=1, register=1), bronze_event_id=eid)
    assert isinstance(r, Reading)
    r.register_kwh = Decimal(register)
    r.energy_kwh = Decimal(energy)
    r.rollover = rollover
    return r


def full_day_events(meter="MWH", skip=(), start_eid=1, register_step=100):
    """Bronze-shaped events for every slot of DAY except `skip`."""
    out = []
    for i in range(SLOTS_PER_DAY):
        if i in skip:
            continue
        out.append(
            {
                "bronze_event_id": start_eid + i,
                "source_file": "2025-09-01/F01.json",
                "source_date": DAY,
                "schema_version": 1,
                "raw": ev(meter, ts_str(i), energy=100, register=1000 + register_step * i),
            }
        )
    return out


def assert_q(res, reason):
    assert isinstance(res, Quarantined), f"expected quarantine {reason}, got {res}"
    assert res.reason_code == reason


# --- UNIT RULE (CLAUDE.md §4) ---------------------------------------------
def test_wh_energy_is_converted_to_kwh_by_dividing_by_1000():
    r = parse(ev("MWH", energy=1500, unit="Wh"))
    assert r.energy_kwh == Decimal("1.5") and r.source_unit == "Wh"


def test_kwh_meter_energy_is_not_double_converted():
    r = parse(ev("MKWH", energy=1.5, register=42.25, unit="kWh"))
    assert r.energy_kwh == Decimal("1.5")
    assert r.register_kwh == Decimal("42.25")


def test_register_is_converted_with_the_same_unit_rule_as_energy():
    r = parse(ev("MWH", energy=250, register=1234567.8, unit="Wh"))
    assert r.register_kwh == Decimal("1234.5678")


def test_missing_unit_field_falls_back_to_meter_master_unit():
    assert parse(ev("MWH", energy=2000)).energy_kwh == Decimal(2)
    assert parse(ev("MKWH", energy=2)).energy_kwh == Decimal(2)


def test_unit_disagreeing_with_meter_master_is_quarantined_bad_schema():
    assert_q(parse(ev("MWH", unit="kWh")), "BAD_SCHEMA")
    assert_q(parse(ev("MKWH", unit="Wh")), "BAD_SCHEMA")


def test_unknown_unit_is_quarantined_bad_schema():
    assert_q(parse(ev("MWH", unit="MWh")), "BAD_SCHEMA")


def test_to_kwh_rejects_unknown_unit():
    with pytest.raises(ValueError):
        to_kwh(Decimal(1), "J")


def test_decimal_conversion_is_exact_no_float_drift():
    assert parse(ev("MWH", energy=0.1)).energy_kwh == Decimal("0.0001")


# --- TIME RULE (CLAUDE.md §4) ---------------------------------------------
def test_offset_timestamp_is_normalised_to_utc():
    r = parse(ev(ts="2025-09-01T05:30:00+05:30"))
    assert r.reading_ts == dt.datetime(2025, 9, 1, 0, 0, tzinfo=UTC)


def test_reading_date_is_the_utc_date_not_the_local_date():
    r = parse(ev(ts="2025-09-02T02:00:00+05:30"))
    assert r.reading_date == dt.date(2025, 9, 1)


def test_naive_timestamp_is_treated_as_utc():
    r = parse(ev(ts="2025-09-01T10:15:00"))
    assert r.reading_ts == dt.datetime(2025, 9, 1, 10, 15, tzinfo=UTC)


def test_timestamp_not_on_15_min_boundary_is_quarantined_bad_schema():
    assert_q(parse(ev(ts="2025-09-01T00:07:00Z")), "BAD_SCHEMA")
    assert_q(parse(ev(ts="2025-09-01T00:15:30Z")), "BAD_SCHEMA")


def test_unparseable_timestamp_is_quarantined_unparseable():
    assert_q(parse(ev(ts="yesterday-ish")), "UNPARSEABLE")
    assert_q(parse(ev(ts=1693526400)), "UNPARSEABLE")


def test_quarantine_without_parsed_ts_uses_fallback_source_date():
    q = parse(ev(ts="garbage"), fallback_date=dt.date(2025, 9, 3))
    assert q.reading_date == dt.date(2025, 9, 3)


# --- shape / parse (BAD_SCHEMA vs UNPARSEABLE) ----------------------------
@pytest.mark.parametrize("field", ["meter_id", "ts", "energy", "register"])
def test_missing_required_field_is_quarantined_bad_schema(field):
    raw = ev()
    del raw[field]
    assert_q(parse(raw), "BAD_SCHEMA")


@pytest.mark.parametrize("field", ["meter_id", "ts", "energy", "register"])
def test_null_required_field_is_quarantined_bad_schema(field):
    assert_q(parse(ev(**{field: None}) if field != "meter_id" else {**ev(), "meter_id": None}), "BAD_SCHEMA")


def test_non_object_event_is_quarantined_bad_schema():
    q = parse(["not", "a", "dict"])
    assert_q(q, "BAD_SCHEMA")
    assert q.raw == {"value": ["not", "a", "dict"]}


def test_non_string_meter_id_is_quarantined_bad_schema():
    assert_q(parse(ev(meter=123)), "BAD_SCHEMA")


@pytest.mark.parametrize("bad", ["abc", True, "NaN", "Infinity", [1]])
def test_non_numeric_energy_is_quarantined_unparseable(bad):
    assert_q(parse(ev(energy=bad)), "UNPARSEABLE")


def test_non_numeric_voltage_is_quarantined_unparseable():
    assert_q(parse(ev(voltage="high", schema_version=2)), "UNPARSEABLE")


def test_numeric_string_energy_is_accepted():
    assert parse(ev(energy="1500")).energy_kwh == Decimal("1.5")


@pytest.mark.parametrize("sv", [0, 3, "2", True])
def test_schema_version_other_than_1_or_2_is_quarantined_bad_schema(sv):
    assert_q(parse(ev(schema_version=sv)), "BAD_SCHEMA")


def test_missing_schema_version_is_inferred_from_v2_fields():
    assert parse(ev()).schema_version == 1
    assert parse(ev(voltage=231.0, firmware="fw-3.0.0")).schema_version == 2


def test_bronze_recorded_schema_version_is_used_when_payload_lacks_it():
    assert parse(ev(), bronze_schema_version=2).schema_version == 2


# --- v1 / v2 --------------------------------------------------------------
def test_v1_event_has_null_voltage_and_firmware():
    r = parse(ev(schema_version=1))
    assert r.voltage is None and r.firmware is None and r.schema_version == 1


def test_v2_event_keeps_voltage_and_firmware():
    r = parse(ev(schema_version=2, voltage=229.4, firmware="fw-2.3.1"))
    assert r.voltage == Decimal("229.4") and r.firmware == "fw-2.3.1"


def test_reading_is_enriched_with_feeder_and_zone_from_master():
    r = parse(ev("MKWH", energy=1))
    assert (r.feeder_id, r.zone_id) == ("F01", "Z01")


# --- DQ: unknown meter, negative energy (CLAUDE.md §5) ---------------------
def test_unknown_meter_is_quarantined_unknown_meter():
    q = parse(ev("M99999"))
    assert_q(q, "UNKNOWN_METER")
    assert q.meter_id == "M99999" and q.raw["meter_id"] == "M99999"


def test_negative_energy_is_quarantined_negative_energy():
    assert_q(parse(ev(energy=-5)), "NEGATIVE_ENERGY")


def test_zero_energy_is_accepted_not_quarantined():
    assert parse(ev(energy=0)).energy_kwh == 0


def test_quarantine_preserves_raw_row_and_bronze_lineage():
    raw = ev(energy=-1)
    q = parse(raw, bronze_event_id=77, source_file="2025-09-01/F01.json")
    assert q.raw == raw and q.bronze_event_id == 77 and q.source_file == "2025-09-01/F01.json"


# --- DEDUPE (CLAUDE.md §7) ------------------------------------------------
def test_duplicate_reading_is_deduped_first_copy_kept():
    a, b = reading(eid=5), reading(eid=9)
    kept, dups = dedupe([b, a])
    assert [r.bronze_event_id for r in kept] == [5]
    assert len(dups) == 1 and dups[0].reason_code == "DUPLICATE"
    assert dups[0].bronze_event_id == 9


def test_triplicate_reading_yields_one_row_and_two_duplicate_quarantines():
    kept, dups = dedupe([reading(eid=i) for i in (3, 1, 2)])
    assert len(kept) == 1 and len(dups) == 2


def test_same_ts_different_meters_are_not_duplicates():
    kept, dups = dedupe([reading("MWH", eid=1), reading("MKWH", eid=2)])
    assert len(kept) == 2 and dups == []


def test_invalid_first_copy_does_not_block_valid_second_copy():
    events = full_day_events(skip=(0,))
    events.append({"bronze_event_id": 1000, "source_file": "x", "source_date": DAY,
                   "schema_version": 1, "raw": ev(ts=ts_str(0), energy=-1, register=1000)})
    events.append({"bronze_event_id": 1001, "source_file": "x", "source_date": DAY,
                   "schema_version": 1, "raw": ev(ts=ts_str(0), energy=1, register=1000)})
    res = normalise_day(events, {"MWH": METERS["MWH"]}, DAY)
    assert slot(0) in {r.reading_ts for r in res.readings}
    assert [q.reason_code for q in res.quarantine] == ["NEGATIVE_ENERGY"]


# --- ORDER + REGISTER (CLAUDE.md §5/§7) -----------------------------------
def test_out_of_order_events_are_ordered_by_meter_and_reading_ts():
    events = full_day_events("MWH") + full_day_events("MKWH", start_eid=500)
    random.Random(1).shuffle(events)
    res = normalise_day(events, METERS, DAY)
    keys = [(r.meter_id, r.reading_ts) for r in res.readings]
    assert keys == sorted(keys) and len(keys) == 2 * SLOTS_PER_DAY


def test_out_of_order_arrival_does_not_cause_false_register_decrease():
    events = full_day_events()
    events.reverse()  # newest first, by bronze id order
    for n, e in enumerate(events):
        e["bronze_event_id"] = n
    res = normalise_day(events, {"MWH": METERS["MWH"]}, DAY)
    assert res.quarantine == [] and len(res.readings) == SLOTS_PER_DAY


def test_register_decrease_without_rollover_is_quarantined():
    ok, bad = order_and_check_register(
        [reading(i=0, register="100"), reading(i=1, register="50"), reading(i=2, register="101")]
    )
    assert [r.reading_ts for r in ok] == [slot(0), slot(2)]
    assert len(bad) == 1 and bad[0].reason_code == "REGISTER_DECREASE_NO_ROLLOVER"
    assert bad[0].reading_ts == slot(1)


def test_register_decrease_with_rollover_flag_is_kept():
    ok, bad = order_and_check_register(
        [reading(i=0, register="99999"), reading(i=1, register="0.5", rollover=True),
         reading(i=2, register="0.7")]
    )
    assert len(ok) == 3 and bad == []
    assert ok[1].rollover is True


def test_equal_register_is_not_a_decrease():
    ok, bad = order_and_check_register([reading(i=0, register="10"), reading(i=1, register="10")])
    assert len(ok) == 2 and bad == []


def test_register_after_quarantined_decrease_is_compared_to_last_accepted():
    ok, bad = order_and_check_register(
        [reading(i=0, register="100"), reading(i=1, register="50"), reading(i=2, register="60")]
    )
    # 60 < last accepted 100 -> also a decrease
    assert [b.reading_ts for b in bad] == [slot(1), slot(2)] and len(ok) == 1


def test_register_decrease_across_days_uses_previous_day_register():
    ok, bad = order_and_check_register([reading(i=0, register="5")], {"MWH": Decimal(10)})
    assert ok == [] and bad[0].reason_code == "REGISTER_DECREASE_NO_ROLLOVER"


def test_register_check_is_per_meter_not_global():
    ok, bad = order_and_check_register(
        [reading("MWH", i=0, register="1000"), reading("MKWH", i=1, register="1")]
    )
    assert len(ok) == 2 and bad == []


# --- GAPS (CLAUDE.md §4: recorded, never filled) --------------------------
def test_missing_interval_recorded_as_gap_not_filled():
    res = normalise_day(full_day_events(skip=range(30, 46)), {"MWH": METERS["MWH"]}, DAY)
    assert len(res.readings) == SLOTS_PER_DAY - 16  # nothing interpolated
    assert {r.reading_ts for r in res.readings}.isdisjoint({slot(i) for i in range(30, 46)})
    [g] = res.gaps
    assert (g.interval_start, g.interval_end, g.missing_intervals) == (slot(30), slot(46), 16)


def test_complete_day_has_no_gaps():
    assert normalise_day(full_day_events(), {"MWH": METERS["MWH"]}, DAY).gaps == []


def test_separate_missing_runs_become_separate_gaps():
    gaps = normalise_day(full_day_events(skip=(3, 4, 50)), {"MWH": METERS["MWH"]}, DAY).gaps
    assert [(g.interval_start, g.missing_intervals) for g in gaps] == [(slot(3), 2), (slot(50), 1)]


def test_leading_and_trailing_gaps_are_recorded():
    gaps = normalise_day(full_day_events(skip=(0, 95)), {"MWH": METERS["MWH"]}, DAY).gaps
    assert [(g.interval_start, g.interval_end) for g in gaps] == [
        (slot(0), slot(1)),
        (slot(95), slot(0, DAY + dt.timedelta(days=1))),
    ]


def test_silent_meter_gets_one_full_day_gap():
    [g] = find_gaps([], {"MWH": METERS["MWH"]}, DAY)
    assert g.missing_intervals == SLOTS_PER_DAY and g.interval_start == slot(0)
    assert (g.feeder_id, g.zone_id) == ("F01", "Z01")


def test_quarantined_slot_counts_as_gap():
    events = full_day_events()
    events[10]["raw"]["energy"] = -3
    res = normalise_day(events, {"MWH": METERS["MWH"]}, DAY)
    assert [(g.interval_start, g.missing_intervals) for g in res.gaps] == [(slot(10), 1)]


def test_unknown_meter_produces_no_gap_rows():
    events = full_day_events()
    events.append({"bronze_event_id": 999, "source_file": "x", "source_date": DAY,
                   "schema_version": 1, "raw": ev("M99999")})
    res = normalise_day(events, {"MWH": METERS["MWH"]}, DAY)
    assert all(g.meter_id != "M99999" for g in res.gaps)


# --- day scoping ----------------------------------------------------------
def test_events_for_another_utc_day_are_excluded_from_this_day():
    events = full_day_events()
    events.append({"bronze_event_id": 999, "source_file": "x", "source_date": DAY,
                   "schema_version": 1, "raw": ev(ts="2025-09-02T00:00:00Z")})
    res = normalise_day(events, {"MWH": METERS["MWH"]}, DAY)
    assert all(r.reading_date == DAY for r in res.readings)
    assert len(res.readings) == SLOTS_PER_DAY and res.quarantine == []


def test_normalise_day_is_deterministic_regardless_of_input_order():
    events = full_day_events(skip=(7,)) + full_day_events("MKWH", start_eid=500)
    events.append({"bronze_event_id": 2000, "source_file": "x", "source_date": DAY,
                   "schema_version": 1, "raw": ev(ts=ts_str(1), register=1100)})
    shuffled = events[:]
    random.Random(7).shuffle(shuffled)
    a, b = normalise_day(events, METERS, DAY), normalise_day(shuffled, METERS, DAY)
    assert [(r.meter_id, r.reading_ts, r.bronze_event_id) for r in a.readings] == [
        (r.meter_id, r.reading_ts, r.bronze_event_id) for r in b.readings
    ]
    assert [(q.bronze_event_id, q.reason_code) for q in a.quarantine] == [
        (q.bronze_event_id, q.reason_code) for q in b.quarantine
    ]
    assert a.gaps == b.gaps
