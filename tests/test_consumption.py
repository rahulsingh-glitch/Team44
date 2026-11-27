"""Consumption layer tests — gold.consumption_{hourly,daily}, gold.billing_monthly
and the feeder/zone roll-up views (CLAUDE.md §3, §4).

Two throwaway databases on the warehouse server (the team's `lakehouse` is
never touched); skipped if the warehouse is unreachable. Feature code is not
modified.

A. SEED (gridpulse_test_gold): generator -> real pipeline (`pipeline.run`) ->
   assert reconciliation and planted defects (gap, outage, duplicate,
   quarantined slot, unknown meter, Wh/kWh) as they land in gold.
B. CRAFTED (gridpulse_test_gold_crafted): rows written straight into
   ref.dim_meter + silver.meter_readings, then `build_gold_date` — for cases the
   3-day seed cannot produce (full month -> BILLABLE / LOW_COMPLETENESS, silent
   meter, not-yet-installed meter, the 90% boundary, UTC hour buckets,
   replace-not-append on re-run).
"""

import datetime as dt
from decimal import Decimal

import generate_synthetic_data as gen
import psycopg
import pytest
from psycopg import conninfo, sql

from src import pipeline
from src.common.db import warehouse_dsn
from src.gold.consumption import build_gold_date
from src.ref.dim_meter import create_ref_schema
from src.silver.schema import create_silver_schema
from src.storage.partitions import ensure_partition

UTC = dt.UTC
SEED_DB = "gridpulse_test_gold"
CRAFTED_DB = "gridpulse_test_gold_crafted"


# --------------------------------------------------------------- helpers
def _dsn(db: str) -> str:
    return conninfo.make_conninfo(warehouse_dsn(), dbname=db)


def _recreate(db: str) -> None:
    with psycopg.connect(_dsn("postgres"), autocommit=True, connect_timeout=3) as c:
        c.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(db)
            )
        )
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))


def _drop(db: str) -> None:
    with psycopg.connect(_dsn("postgres"), autocommit=True) as c:
        c.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(db)
            )
        )


def q(conn, query, *params):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def one(conn, query, *params):
    return q(conn, query, *params)[0]


def gold_fingerprint(conn) -> str:
    return one(
        conn,
        """SELECT md5(string_agg(t, E'\\n' ORDER BY t)) FROM (
             SELECT (meter_id,hour_ts,reading_date,feeder_id,zone_id,energy_kwh,
                     intervals_present)::text t FROM gold.consumption_hourly
             UNION ALL SELECT (meter_id,reading_date,feeder_id,zone_id,energy_kwh,
                     intervals_present,intervals_expected,completeness_pct,is_complete)::text
               FROM gold.consumption_daily
             UNION ALL SELECT (meter_id,billing_month,feeder_id,zone_id,energy_kwh,
                     days_with_data,days_processed,days_in_month,intervals_present,
                     intervals_expected,completeness_pct,billing_status)::text
               FROM gold.billing_monthly) x""",
    )[0]


# =================================================== A. seed, end to end
@pytest.fixture(scope="module")
def seed_landing(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing")
    gen.generate(gen.build_parser().parse_args(["--out", str(out), "--seed", "44"]))
    return out


@pytest.fixture(scope="module")
def seed_built(seed_landing):
    try:
        _recreate(SEED_DB)
    except psycopg.OperationalError as exc:
        pytest.skip(f"warehouse unreachable: {exc}")
    mp = pytest.MonkeyPatch()
    mp.setenv("WAREHOUSE_URL", _dsn(SEED_DB))
    pipeline.run("all", landing=seed_landing)
    yield seed_landing
    mp.undo()
    _drop(SEED_DB)


@pytest.fixture()
def sdb(seed_built):
    with psycopg.connect(_dsn(SEED_DB)) as c:
        yield c


# --- reconciliation: every level carries exactly the silver kWh --------------
def test_hourly_kwh_equals_silver_kwh_per_meter_per_day(sdb):
    bad = q(
        sdb,
        """
        WITH s AS (SELECT meter_id, reading_date, sum(energy_kwh) k, count(*) n
                   FROM silver.meter_readings GROUP BY 1, 2),
             h AS (SELECT meter_id, reading_date, sum(energy_kwh) k, sum(intervals_present) n
                   FROM gold.consumption_hourly GROUP BY 1, 2)
        SELECT * FROM s FULL JOIN h USING (meter_id, reading_date)
        WHERE s.k IS DISTINCT FROM h.k OR s.n IS DISTINCT FROM h.n""",
    )
    assert bad == []


def test_daily_kwh_equals_sum_of_hourly_per_meter(sdb):
    bad = q(
        sdb,
        """
        WITH h AS (SELECT meter_id, reading_date, sum(energy_kwh) k, sum(intervals_present) n
                   FROM gold.consumption_hourly GROUP BY 1, 2)
        SELECT d.meter_id, d.reading_date FROM gold.consumption_daily d
        LEFT JOIN h USING (meter_id, reading_date)
        WHERE d.energy_kwh IS DISTINCT FROM h.k OR d.intervals_present <> coalesce(h.n, 0)""",
    )
    assert bad == []


def test_monthly_billing_kwh_equals_sum_of_daily_per_meter(sdb):
    bad = q(
        sdb,
        """
        WITH d AS (SELECT meter_id, date_trunc('month', reading_date)::date m,
                          coalesce(sum(energy_kwh), 0) k, sum(intervals_present) n
                   FROM gold.consumption_daily GROUP BY 1, 2)
        SELECT b.meter_id FROM gold.billing_monthly b
        JOIN d ON d.meter_id = b.meter_id AND d.m = b.billing_month
        WHERE b.energy_kwh <> d.k OR b.intervals_present <> d.n""",
    )
    assert bad == []
    assert one(sdb, "SELECT count(*) FROM gold.billing_monthly")[0] == 60


def test_feeder_and_zone_views_equal_meter_level_totals(sdb):
    for view, key in (
        ("gold.consumption_daily_feeder", "feeder_id"),
        ("gold.consumption_daily_zone", "zone_id"),
    ):
        bad = q(
            sdb,
            f"""
            WITH m AS (SELECT reading_date, {key}, sum(energy_kwh) k
                       FROM gold.consumption_daily GROUP BY 1, 2)
            SELECT * FROM {view} v FULL JOIN m USING (reading_date, {key})
            WHERE v.energy_kwh IS DISTINCT FROM m.k""",
        )
        assert bad == [], view
    for view, key in (
        ("gold.consumption_hourly_feeder", "feeder_id"),
        ("gold.consumption_hourly_zone", "zone_id"),
    ):
        bad = q(
            sdb,
            f"""
            WITH m AS (SELECT hour_ts, {key}, sum(energy_kwh) k
                       FROM gold.consumption_hourly GROUP BY 1, 2)
            SELECT * FROM {view} v FULL JOIN m USING (hour_ts, {key})
            WHERE v.energy_kwh IS DISTINCT FROM m.k""",
        )
        assert bad == [], view


def test_every_installed_meter_has_one_daily_row_per_processed_day(sdb):
    assert q(
        sdb,
        "SELECT reading_date, count(*) FROM gold.consumption_daily GROUP BY 1 ORDER BY 1",
    ) == [
        (dt.date(2025, 9, 1), 60),
        (dt.date(2025, 9, 2), 60),
        (dt.date(2025, 9, 3), 60),
    ]


# --- planted defects as they land in gold ------------------------------------
def test_gap_day_is_marked_incomplete_and_missing_intervals_are_not_filled(sdb):
    row = one(
        sdb,
        """SELECT intervals_present, completeness_pct, is_complete, energy_kwh
                      FROM gold.consumption_daily
                      WHERE meter_id = 'M00003' AND reading_date = '2025-09-02'""",
    )
    silver_k = one(
        sdb,
        """SELECT sum(energy_kwh) FROM silver.meter_readings
                           WHERE meter_id = 'M00003' AND reading_date = '2025-09-02'""",
    )[0]
    assert row[:3] == (80, Decimal("83.33"), False)
    assert row[3] == silver_k  # only measured kWh, nothing interpolated


def test_gap_hours_have_no_hourly_rows_and_edge_hours_keep_partial_counts(sdb):
    # M00003 2025-09-02 slots 30..45 missing = 07:30 .. 11:15 inclusive
    hours = dict(
        q(
            sdb,
            """SELECT extract(hour FROM hour_ts AT TIME ZONE 'UTC')::int,
                                  intervals_present
                           FROM gold.consumption_hourly
                           WHERE meter_id = 'M00003' AND reading_date = '2025-09-02'""",
        )
    )
    assert not {8, 9, 10} & hours.keys()
    assert hours[7] == 2 and hours[11] == 2
    assert len(hours) == 21


def test_feeder_outage_hours_have_no_hourly_rows_for_any_meter_on_feeder(sdb):
    # F04 outage 2025-09-03 slots 32..40 = 08:00 .. 10:00 inclusive
    rows = q(
        sdb,
        """SELECT extract(hour FROM hour_ts AT TIME ZONE 'UTC')::int,
                            count(*), min(intervals_present), max(intervals_present)
                     FROM gold.consumption_hourly
                     WHERE feeder_id = 'F04' AND reading_date = '2025-09-03'
                       AND extract(hour FROM hour_ts AT TIME ZONE 'UTC') BETWEEN 7 AND 11
                     GROUP BY 1 ORDER BY 1""",
    )
    assert [r[0] for r in rows] == [7, 10, 11]
    assert rows[1][1:] == (15, 3, 3)  # 10:00 missing, 10:15-10:45 present


def test_duplicate_readings_are_not_double_counted_in_gold(sdb):
    # M00001 2025-09-01 has duplicated intervals 40..42
    assert (
        one(
            sdb,
            """SELECT intervals_present, completeness_pct FROM gold.consumption_daily
                       WHERE meter_id = 'M00001' AND reading_date = '2025-09-01'""",
        )
        == (96, Decimal("100.00"))
    )
    assert (
        one(sdb, "SELECT max(intervals_present) FROM gold.consumption_hourly")[0] <= 4
    )


def test_quarantined_reading_carries_no_billable_kwh(sdb):
    # M00006 negative energy (2025-09-01 #60) and M00005 register decrease (2025-09-02 #55)
    got = q(
        sdb,
        """SELECT meter_id, intervals_present FROM gold.consumption_daily
                    WHERE (meter_id, reading_date) IN (('M00006', '2025-09-01'), ('M00005', '2025-09-02'))
                    ORDER BY 1""",
    )
    assert got == [("M00005", 95), ("M00006", 95)]
    assert (
        one(sdb, "SELECT count(*) FROM gold.consumption_hourly WHERE energy_kwh < 0")[0]
        == 0
    )


def test_unknown_meter_is_absent_from_every_gold_table(sdb, seed_built):
    import json

    sentinel = json.loads((seed_built / "_manifest.json").read_text())[
        "unknown_meter_sentinel"
    ]
    for t in (
        "gold.consumption_hourly",
        "gold.consumption_daily",
        "gold.billing_monthly",
    ):
        assert (
            one(sdb, f"SELECT count(*) FROM {t} WHERE meter_id = %s", sentinel)[0] == 0
        ), t


def test_kwh_reporting_meters_are_not_double_converted_in_gold(sdb):
    avg = dict(
        q(
            sdb,
            """SELECT m.unit, avg(d.energy_kwh) FROM gold.consumption_daily d
                         JOIN ref.dim_meter m USING (meter_id) GROUP BY 1""",
        )
    )
    ratio = avg["Wh"] / avg["kWh"]
    assert Decimal("0.1") < ratio < Decimal(10), ratio  # 1000x off => double-converted


def test_hour_buckets_are_utc_hour_aligned_and_on_their_reading_date(sdb):
    assert (
        one(
            sdb,
            """SELECT count(*) FROM gold.consumption_hourly
                       WHERE hour_ts <> date_trunc('hour', hour_ts, 'UTC')
                          OR (hour_ts AT TIME ZONE 'UTC')::date <> reading_date""",
        )[0]
        == 0
    )


def test_partial_month_is_open_month_with_expected_based_on_processed_days(sdb):
    assert (
        q(
            sdb,
            """SELECT billing_status, days_processed, days_in_month, count(*),
                            min(intervals_expected), max(intervals_expected)
                     FROM gold.billing_monthly GROUP BY 1, 2, 3""",
        )
        == [("OPEN_MONTH", 3, 30, 60, 288, 288)]
    )


# --- idempotency (the most-tested Track B failure) ---------------------------
def test_rerun_of_one_date_is_idempotent_for_gold(sdb, seed_landing):
    before = gold_fingerprint(sdb)
    pipeline.run("2025-09-02", landing=seed_landing)
    sdb.rollback()
    assert gold_fingerprint(sdb) == before


def test_backfill_of_date_range_is_idempotent_for_gold(sdb, seed_landing):
    before = gold_fingerprint(sdb)
    counts = one(
        sdb,
        """SELECT (SELECT count(*) FROM gold.consumption_hourly),
                                (SELECT count(*) FROM gold.consumption_daily),
                                (SELECT count(*) FROM gold.billing_monthly)""",
    )
    pipeline.backfill("2025-09-01", "2025-09-03", landing=seed_landing)
    sdb.rollback()
    assert gold_fingerprint(sdb) == before
    assert (
        one(
            sdb,
            """SELECT (SELECT count(*) FROM gold.consumption_hourly),
                              (SELECT count(*) FROM gold.consumption_daily),
                              (SELECT count(*) FROM gold.billing_monthly)""",
        )
        == counts
    )


# ================================================ B. crafted silver rows
SEPT = [dt.date(2030, 9, 1) + dt.timedelta(days=i) for i in range(30)]
EDGE_DAY = dt.date(2031, 1, 10)
METERS = [  # meter_id, feeder, zone, install_date
    ("B_FULL", "FB", "ZB", dt.date(2030, 1, 1)),
    ("B_LOW", "FB", "ZB", dt.date(2030, 1, 1)),
    ("E_SILENT", "FE", "ZE", dt.date(2031, 1, 1)),
    ("E_LATE", "FE", "ZE", dt.date(2031, 2, 1)),  # installed after EDGE_DAY
    ("E_86", "FE", "ZE", dt.date(2031, 1, 1)),
    ("E_87", "FE", "ZE", dt.date(2031, 1, 1)),
    ("E_UTC", "FE", "ZE", dt.date(2031, 1, 1)),
]
FEEDER = {m: (f, z) for m, f, z, _ in METERS}


def _slot(day: dt.date, i: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), UTC) + dt.timedelta(minutes=15 * i)


def _insert(conn, meter: str, day: dt.date, slots, kwh: str = "0.25") -> None:
    ensure_partition(conn, "silver.meter_readings", day)
    f, z = FEEDER[meter]
    with conn.cursor() as cur, cur.copy(
        "COPY silver.meter_readings (meter_id, reading_ts, reading_date, feeder_id,"
        " zone_id, energy_kwh, register_kwh, source_unit, status, schema_version,"
        " rollover, is_duplicate, bronze_event_id, run_id) FROM STDIN"
    ) as cp:
        for n, i in enumerate(slots):
            cp.write_row(
                (
                    meter,
                    _slot(day, i),
                    day,
                    f,
                    z,
                    Decimal(kwh),
                    Decimal(n),
                    "kWh",
                    "OK",
                    1,
                    False,
                    False,
                    0,
                    "test",
                )
            )


@pytest.fixture(scope="module")
def crafted():
    try:
        _recreate(CRAFTED_DB)
    except psycopg.OperationalError as exc:
        pytest.skip(f"warehouse unreachable: {exc}")
    snap = {}
    with psycopg.connect(_dsn(CRAFTED_DB)) as c:
        create_ref_schema(c)
        create_silver_schema(c)
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO ref.dim_meter (meter_id, feeder_id, zone_id, unit,"
                " schema_version, install_date) VALUES (%s, %s, %s, 'kWh', 1, %s)",
                METERS,
            )
        # full month: B_FULL 96/day, B_LOW 80/day (slots 0..79)
        for d in SEPT:
            _insert(c, "B_FULL", d, range(96))
            _insert(c, "B_LOW", d, range(80))
        # edge day
        _insert(c, "E_86", EDGE_DAY, range(86))
        _insert(c, "E_87", EDGE_DAY, range(87))
        _insert(c, "E_UTC", EDGE_DAY, [95])  # 23:45 UTC
        c.commit()
        for d in SEPT[:-1]:
            build_gold_date(c, d, "test")
        snap["before_last_day"] = q(
            c,
            """SELECT meter_id, billing_status FROM gold.billing_monthly
                                          ORDER BY 1""",
        )
        build_gold_date(c, SEPT[-1], "test")
        build_gold_date(c, EDGE_DAY, "test")
    yield snap
    _drop(CRAFTED_DB)


@pytest.fixture()
def cdb(crafted):
    with psycopg.connect(_dsn(CRAFTED_DB)) as c:
        yield c


def test_full_month_above_90_pct_is_billable_with_exact_kwh(cdb):
    assert (
        one(
            cdb,
            """SELECT billing_status, energy_kwh, completeness_pct, days_processed,
                              days_in_month, days_with_data, intervals_expected
                       FROM gold.billing_monthly WHERE meter_id = 'B_FULL'""",
        )
        == ("BILLABLE", Decimal("720.000000"), Decimal("100.00"), 30, 30, 30, 2880)
    )


def test_full_month_at_or_below_90_pct_is_low_completeness_not_estimated(cdb):
    # 80/96 per day -> 83.33 %, kWh is measured only (80 * 0.25 * 30), never filled up
    assert (
        one(
            cdb,
            """SELECT billing_status, energy_kwh, completeness_pct
                       FROM gold.billing_monthly WHERE meter_id = 'B_LOW'""",
        )
        == ("LOW_COMPLETENESS", Decimal("600.000000"), Decimal("83.33"))
    )


def test_month_is_open_until_every_day_is_processed(crafted):
    assert crafted["before_last_day"] == [
        ("B_FULL", "OPEN_MONTH"),
        ("B_LOW", "OPEN_MONTH"),
    ]


def test_meter_with_no_readings_has_daily_row_with_null_energy_not_zero(cdb):
    assert (
        one(
            cdb,
            """SELECT energy_kwh, intervals_present, completeness_pct, is_complete
                       FROM gold.consumption_daily
                       WHERE meter_id = 'E_SILENT' AND reading_date = %s""",
            EDGE_DAY,
        )
        == (None, 0, Decimal("0.00"), False)
    )
    assert (
        one(
            cdb,
            "SELECT count(*) FROM gold.consumption_hourly WHERE meter_id = 'E_SILENT'",
        )[0]
        == 0
    )


def test_meter_installed_after_date_gets_no_daily_row(cdb):
    assert (
        one(
            cdb,
            """SELECT count(*) FROM gold.consumption_daily
                       WHERE meter_id = 'E_LATE'""",
        )[0]
        == 0
    )


def test_completeness_flag_requires_strictly_more_than_90_pct(cdb):
    got = {
        m: (p, c)
        for m, p, c in q(
            cdb,
            """
        SELECT meter_id, completeness_pct, is_complete FROM gold.consumption_daily
        WHERE meter_id IN ('E_86', 'E_87') AND reading_date = %s""",
            EDGE_DAY,
        )
    }
    assert got == {"E_86": (Decimal("89.58"), False), "E_87": (Decimal("90.63"), True)}


def test_reading_at_2345_utc_lands_in_hour_23_of_the_same_utc_date(cdb):
    assert (
        q(
            cdb,
            """SELECT hour_ts, reading_date, intervals_present FROM gold.consumption_hourly
                     WHERE meter_id = 'E_UTC'""",
        )
        == [(dt.datetime(2031, 1, 10, 23, 0, tzinfo=UTC), EDGE_DAY, 1)]
    )


def test_rerun_after_silver_change_replaces_rows_instead_of_appending(cdb):
    counts = one(
        cdb,
        """SELECT (SELECT count(*) FROM gold.consumption_hourly WHERE reading_date = %s),
                                (SELECT count(*) FROM gold.consumption_daily WHERE reading_date = %s)""",
        EDGE_DAY,
        EDGE_DAY,
    )
    cdb.execute(
        "UPDATE silver.meter_readings SET energy_kwh = 1 WHERE meter_id = 'E_87'"
    )
    cdb.commit()
    build_gold_date(cdb, EDGE_DAY, "test-rerun")
    assert (
        one(
            cdb,
            """SELECT energy_kwh FROM gold.consumption_daily
                       WHERE meter_id = 'E_87' AND reading_date = %s""",
            EDGE_DAY,
        )[0]
        == Decimal(87)
    )
    assert (
        one(
            cdb,
            """SELECT (SELECT count(*) FROM gold.consumption_hourly WHERE reading_date = %s),
                              (SELECT count(*) FROM gold.consumption_daily WHERE reading_date = %s)""",
            EDGE_DAY,
            EDGE_DAY,
        )
        == counts
    )


def test_rebuilding_a_day_twice_gives_identical_gold(cdb):
    build_gold_date(cdb, SEPT[14], "test")
    before = gold_fingerprint(cdb)
    build_gold_date(cdb, SEPT[14], "test-again")
    assert gold_fingerprint(cdb) == before
