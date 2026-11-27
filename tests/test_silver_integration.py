"""Integration tests: generator -> bronze -> silver against a real Postgres.

Runs the real pipeline (`src.pipeline.run/backfill`) on freshly generated
synthetic data inside a THROWAWAY database (gridpulse_test_silver) on the
warehouse server, so the team's `lakehouse` data is never touched. Skipped if
the warehouse is unreachable. Expected values come from `_manifest.json`.
Feature code is not modified.
"""

import datetime as dt
import json
import shutil

import generate_synthetic_data as gen
import psycopg
import pytest
from psycopg import conninfo, sql

from src import pipeline
from src.common.db import warehouse_dsn

TEST_DB = "gridpulse_test_silver"


def _admin_dsn() -> str:
    return conninfo.make_conninfo(warehouse_dsn(), dbname="postgres")


def _test_dsn() -> str:
    return conninfo.make_conninfo(warehouse_dsn(), dbname=TEST_DB)


def _recreate_db():
    with psycopg.connect(_admin_dsn(), autocommit=True, connect_timeout=3) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB)))
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))


@pytest.fixture(scope="module")
def landing(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing")
    gen.generate(gen.build_parser().parse_args(["--out", str(out), "--seed", "44"]))
    return out


@pytest.fixture(scope="module")
def manifest(landing):
    return json.loads((landing / "_manifest.json").read_text())


@pytest.fixture(scope="module")
def built(landing):
    """Fresh DB + one full pipeline run over every landing date."""
    try:
        _recreate_db()
    except psycopg.OperationalError as exc:
        pytest.skip(f"warehouse unreachable: {exc}")
    mp = pytest.MonkeyPatch()
    mp.setenv("WAREHOUSE_URL", _test_dsn())
    summary = pipeline.run("all", landing=landing)
    yield summary
    mp.undo()


@pytest.fixture()
def db(built):
    with psycopg.connect(_test_dsn()) as c:
        yield c


def q(conn, query, *params):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def defect(manifest, kind):
    return next(d for d in manifest["defects"] if d["type"] == kind)


def fingerprint(conn) -> str:
    return q(
        conn,
        """SELECT md5(string_agg(t, E'\\n' ORDER BY t)) FROM (
          SELECT (meter_id,reading_ts,reading_date,feeder_id,zone_id,energy_kwh,register_kwh,
                  source_unit,status,voltage,firmware,schema_version,rollover,bronze_event_id)::text t
          FROM silver.meter_readings
          UNION ALL SELECT (reading_date,meter_id,reading_ts,reason_code,detail,raw_row,
                            bronze_event_id,source_file)::text FROM silver.quarantine
          UNION ALL SELECT (meter_id,interval_start,interval_end,missing_intervals,reading_date)::text
          FROM silver.gaps) x""",
    )[0][0]


# --- every planted quarantine defect lands with its manifest reason code --
def test_every_planted_quarantine_defect_lands_with_expected_reason_code(db, manifest):
    got = {r for (r,) in q(db, "SELECT DISTINCT reason_code FROM silver.quarantine")}
    expected = {d["expected_reason_code"] for d in manifest["defects"] if "expected_reason_code" in d}
    assert expected <= got
    assert got <= expected | {"DUPLICATE"}  # nothing unexpected quarantined


def test_unknown_meter_rows_are_quarantined_and_absent_from_silver(db, manifest):
    um = defect(manifest, "unknown_meter")
    sentinel = manifest["unknown_meter_sentinel"]
    [(n,)] = q(db, "SELECT count(*) FROM silver.quarantine WHERE reason_code='UNKNOWN_METER' AND meter_id=%s", sentinel)
    assert n == um["count"]
    assert q(db, "SELECT count(*) FROM silver.meter_readings WHERE meter_id=%s", sentinel) == [(0,)]


def test_negative_energy_is_quarantined_and_no_negative_kwh_in_silver(db, manifest):
    ne = defect(manifest, "negative_energy")
    rows = q(db, "SELECT meter_id FROM silver.quarantine WHERE reason_code='NEGATIVE_ENERGY'")
    assert rows == [(ne["meter_id"],)]
    assert q(db, "SELECT count(*) FROM silver.meter_readings WHERE energy_kwh < 0") == [(0,)]


def test_register_decrease_without_rollover_is_quarantined_at_planted_interval(db, manifest):
    rd = defect(manifest, "register_decrease")
    ts = dt.datetime.fromisoformat(rd["date"]).replace(tzinfo=dt.UTC) + dt.timedelta(minutes=15 * rd["interval"])
    rows = q(db, "SELECT meter_id, reading_ts FROM silver.quarantine WHERE reason_code='REGISTER_DECREASE_NO_ROLLOVER'")
    assert rows == [(rd["meter_id"], ts)]


def test_flagged_rollover_is_kept_in_silver_with_rollover_true(db, manifest):
    r = defect(manifest, "rollover")
    rows = q(db, "SELECT meter_id FROM silver.meter_readings WHERE rollover")
    assert rows == [(r["meter_id"],)]
    assert q(db, "SELECT count(*) FROM silver.quarantine WHERE meter_id=%s", r["meter_id"]) == [(0,)]


def test_unparseable_file_is_quarantined_unparseable(db):
    rows = q(db, "SELECT source_file FROM silver.quarantine WHERE reason_code='UNPARSEABLE'")
    assert len(rows) == 1 and rows[0][0].endswith("_corrupt.json")


# --- dedupe / order -------------------------------------------------------
def test_duplicate_reading_is_deduped_and_quarantined_duplicate(db, manifest):
    dup = defect(manifest, "duplicate")
    rows = q(db, "SELECT meter_id, count(*) FROM silver.quarantine WHERE reason_code='DUPLICATE' GROUP BY 1")
    assert rows == [(dup["meter_id"], len(dup["intervals"]))]
    [(n,)] = q(
        db,
        "SELECT count(*) FROM silver.meter_readings WHERE meter_id=%s AND reading_date=%s",
        dup["meter_id"], dup["date"],
    )
    assert n == 96


def test_silver_has_one_row_per_meter_and_reading_ts(db):
    assert q(db, "SELECT count(*) - count(DISTINCT (meter_id, reading_ts)) FROM silver.meter_readings") == [(0,)]
    assert q(db, "SELECT count(*) FROM silver.meter_readings WHERE is_duplicate") == [(0,)]


def test_out_of_order_file_yields_complete_ordered_readings(db, manifest):
    ooo = defect(manifest, "out_of_order")
    rows = q(
        db,
        "SELECT meter_id, count(*), bool_and(reading_ts = date_trunc('minute', reading_ts)) "
        "FROM silver.meter_readings WHERE feeder_id=%s AND reading_date=%s GROUP BY 1",
        ooo["feeder_id"], ooo["date"],
    )
    lost = dict(q(db, "SELECT meter_id, count(*) FROM silver.quarantine WHERE reading_date=%s "
                      "AND reason_code <> 'DUPLICATE' AND meter_id IS NOT NULL GROUP BY 1", ooo["date"]))
    assert rows and all(n == 96 - lost.get(m, 0) for m, n, _ in rows)


def test_redelivered_file_is_not_double_counted_in_silver(db, manifest):
    rd = defect(manifest, "redelivered")
    [(n,)] = q(
        db,
        "SELECT count(*) FROM silver.meter_readings WHERE feeder_id=%s AND reading_date=%s",
        rd["feeder_id"], rd["date"],
    )
    [(meters,)] = q(db, "SELECT count(*) FROM ref.dim_meter WHERE feeder_id=%s", rd["feeder_id"])
    [(lost,)] = q(  # slots quarantined for a real reason (e.g. negative energy) on that feeder/day
        db,
        "SELECT count(*) FROM silver.quarantine qq JOIN ref.dim_meter m USING (meter_id) "
        "WHERE m.feeder_id=%s AND qq.reading_date=%s AND qq.reason_code <> 'DUPLICATE'",
        rd["feeder_id"], rd["date"],
    )
    assert n == meters * 96 - lost


# --- units ----------------------------------------------------------------
def test_wh_converted_to_kwh_and_kwh_meters_not_double_converted_end_to_end(db):
    rows = q(
        db,
        """SELECT r.source_unit, count(*) FILTER (WHERE r.energy_kwh <>
                 CASE WHEN r.source_unit='Wh' THEN (b.raw->>'energy')::numeric/1000
                      ELSE (b.raw->>'energy')::numeric END)
           FROM silver.meter_readings r JOIN bronze.meter_events_raw b ON b.event_id=r.bronze_event_id
           GROUP BY 1""",
    )
    assert dict(rows) == {"Wh": 0, "kWh": 0}


def test_source_unit_matches_meter_master_unit(db):
    assert q(
        db,
        "SELECT count(*) FROM silver.meter_readings r JOIN ref.dim_meter m USING (meter_id) "
        "WHERE r.source_unit <> m.unit",
    ) == [(0,)]


# --- gaps -----------------------------------------------------------------
def test_missing_interval_recorded_as_gap_not_filled_end_to_end(db, manifest):
    g = defect(manifest, "gap")
    start = dt.datetime.fromisoformat(g["date"]).replace(tzinfo=dt.UTC) + dt.timedelta(minutes=15 * g["drop_from"])
    n = g["drop_to"] - g["drop_from"] + 1
    rows = q(db, "SELECT interval_start, interval_end, missing_intervals FROM silver.gaps WHERE meter_id=%s", g["meter_id"])
    assert rows == [(start, start + dt.timedelta(minutes=15 * n), n)]
    assert q(
        db,
        "SELECT count(*) FROM silver.meter_readings WHERE meter_id=%s AND reading_ts >= %s AND reading_ts < %s",
        g["meter_id"], start, start + dt.timedelta(minutes=15 * n),
    ) == [(0,)]


def test_feeder_outage_window_is_recorded_as_gaps_for_every_meter_on_feeder(db, manifest):
    o = defect(manifest, "outage")
    [(meters,)] = q(db, "SELECT count(*) FROM ref.dim_meter WHERE feeder_id=%s", o["feeder_id"])
    n = o["to"] - o["from"] + 1
    rows = q(
        db,
        "SELECT count(DISTINCT meter_id), min(missing_intervals), max(missing_intervals) "
        "FROM silver.gaps WHERE feeder_id=%s AND reading_date=%s",
        o["feeder_id"], o["date"],
    )
    assert rows == [(meters, n, n)]


def test_readings_plus_missing_slots_equal_96_per_meter_per_day(db):
    rows = q(
        db,
        """SELECT m.meter_id, d.reading_date,
                  (SELECT count(*) FROM silver.meter_readings r WHERE r.meter_id=m.meter_id AND r.reading_date=d.reading_date)
                + (SELECT coalesce(sum(missing_intervals),0) FROM silver.gaps g WHERE g.meter_id=m.meter_id AND g.reading_date=d.reading_date)
           FROM ref.dim_meter m CROSS JOIN (SELECT DISTINCT reading_date FROM silver.meter_readings) d""",
    )
    assert rows and {n for *_, n in rows} == {96}


# --- contract -------------------------------------------------------------
def test_all_reading_ts_are_utc_15min_aligned_and_match_reading_date(db):
    assert q(
        db,
        "SELECT count(*) FROM silver.meter_readings WHERE extract(minute FROM reading_ts)::int %% 15 <> 0 "
        "OR extract(second FROM reading_ts) <> 0 OR (reading_ts AT TIME ZONE 'UTC')::date <> reading_date",
    ) == [(0,)]


def test_v1_rows_have_null_voltage_firmware_and_v2_rows_have_them(db):
    rows = {
        sv: (n, v, f)
        for sv, n, v, f in q(
            db,
            "SELECT schema_version, count(*), count(voltage), count(firmware) FROM silver.meter_readings GROUP BY 1",
        )
    }
    assert rows[1][1:] == (0, 0)
    assert rows[2][0] == rows[2][1] == rows[2][2]


def test_quarantine_rejects_reason_code_outside_closed_list(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO silver.quarantine (reading_date, reason_code, raw_row, run_id) "
            "VALUES ('2025-09-01', 'MADE_UP', '{}', 't')"
        )
    db.rollback()


# --- idempotency (must run last: they re-run the pipeline) ----------------
def test_rerun_is_idempotent(db, landing):
    before = fingerprint(db)
    pipeline.run("all", landing=landing)
    db.rollback()
    assert fingerprint(db) == before


def test_backfill_of_date_range_is_idempotent(db, landing, manifest):
    before = fingerprint(db)
    pipeline.backfill(manifest["dates"][0], manifest["dates"][-1], landing=landing)
    db.rollback()
    assert fingerprint(db) == before


def test_rerun_after_redelivered_copy_adds_no_silver_rows(db, landing, manifest):
    before = fingerprint(db)
    d = manifest["dates"][0]
    src = min((landing / d).glob("F*.json"))
    shutil.copyfile(src, landing / d / "zz_late_redelivery.json")
    try:
        pipeline.run(d, landing=landing)
    finally:
        (landing / d / "zz_late_redelivery.json").unlink()
    db.rollback()
    assert fingerprint(db) == before
