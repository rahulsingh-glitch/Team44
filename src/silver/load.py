"""Silver builder: bronze.meter_events_raw -> silver.{meter_readings, quarantine, gaps}.

IDEMPOTENT per UTC date: build_silver_date(D) deletes D's rows from all three
silver tables and re-inserts them in ONE transaction. Same bronze in -> same
rows out (only run_id / quarantine_id differ).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import psycopg

from src.ref.dim_meter import fetch_meters
from src.silver.normalise import DayResult, normalise_day
from src.silver.schema import create_silver_schema

# Candidates for day D: anything landed D-1..D+1 (covers tz offsets around
# midnight) plus late files whose ts text starts with D. Final filter is the
# parsed UTC date, in normalise_day.
CANDIDATES_SQL = """
SELECT event_id, source_file, source_date, schema_version, raw
FROM bronze.meter_events_raw
WHERE source_date BETWEEN %(d)s::date - 1 AND %(d)s::date + 1
   OR left(raw->>'ts', 10) = %(ds)s
"""

BRONZE_TS_INDEX = """
CREATE INDEX IF NOT EXISTS ix_meter_events_raw_ts_date
    ON bronze.meter_events_raw ((left(raw->>'ts', 10)));
"""

# Unparseable FILES (logged by bronze) -> one UNPARSEABLE quarantine row each.
UNPARSEABLE_FILES_SQL = """
SELECT DISTINCT ON (source_file, file_checksum) source_file, file_checksum, reason
FROM bronze.load_log
WHERE status = 'unparseable' AND source_date = %(d)s
ORDER BY source_file, file_checksum, log_id
"""

# Last accepted register per meter before D (7-day look-back bounds the scan).
PREV_REGISTER_SQL = """
SELECT DISTINCT ON (meter_id) meter_id, register_kwh
FROM silver.meter_readings
WHERE reading_date BETWEEN %(d)s::date - 7 AND %(d)s::date - 1
ORDER BY meter_id, reading_ts DESC
"""


def _fetch_events(conn: psycopg.Connection, day: dt.date) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL, {"d": day, "ds": day.isoformat()})
        return [
            {
                "bronze_event_id": eid,
                "source_file": sf,
                "source_date": sd,
                "schema_version": sv,
                "raw": raw,
            }
            for eid, sf, sd, sv, raw in cur.fetchall()
        ]


def _prev_register(conn: psycopg.Connection, day: dt.date) -> dict[str, Decimal]:
    with conn.cursor() as cur:
        cur.execute(PREV_REGISTER_SQL, {"d": day})
        return dict(cur.fetchall())


def _unparseable_files(conn: psycopg.Connection, day: dt.date) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(UNPARSEABLE_FILES_SQL, {"d": day})
        return cur.fetchall()


def _write(
    conn: psycopg.Connection,
    day: dt.date,
    res: DayResult,
    bad_files: list[tuple],
    run_id: str,
) -> None:
    with conn.cursor() as cur:
        for t in ("meter_readings", "quarantine", "gaps"):
            cur.execute(f"DELETE FROM silver.{t} WHERE reading_date = %s", (day,))

        with cur.copy(
            "COPY silver.meter_readings (meter_id, reading_ts, reading_date, feeder_id,"
            " zone_id, energy_kwh, register_kwh, source_unit, status, voltage, firmware,"
            " schema_version, rollover, is_duplicate, bronze_event_id, run_id) FROM STDIN"
        ) as cp:
            for r in res.readings:
                cp.write_row(
                    (
                        r.meter_id,
                        r.reading_ts,
                        r.reading_date,
                        r.feeder_id,
                        r.zone_id,
                        r.energy_kwh,
                        r.register_kwh,
                        r.source_unit,
                        r.status,
                        r.voltage,
                        r.firmware,
                        r.schema_version,
                        r.rollover,
                        False,
                        r.bronze_event_id,
                        run_id,
                    )
                )

        with cur.copy(
            "COPY silver.quarantine (reading_date, meter_id, reading_ts, reason_code,"
            " detail, raw_row, bronze_event_id, source_file, run_id) FROM STDIN"
        ) as cp:
            for q in res.quarantine:
                cp.write_row(
                    (
                        q.reading_date,
                        q.meter_id,
                        q.reading_ts,
                        q.reason_code,
                        q.detail,
                        json.dumps(q.raw, sort_keys=True),
                        q.bronze_event_id,
                        q.source_file,
                        run_id,
                    )
                )
            for source_file, checksum, reason in bad_files:
                cp.write_row(
                    (
                        day,
                        None,
                        None,
                        "UNPARSEABLE",
                        (reason or "unparseable file")[:300],
                        json.dumps(
                            {"source_file": source_file, "file_checksum": checksum}
                        ),
                        None,
                        source_file,
                        run_id,
                    )
                )

        with cur.copy(
            "COPY silver.gaps (meter_id, interval_start, interval_end, missing_intervals,"
            " reading_date, feeder_id, zone_id, run_id) FROM STDIN"
        ) as cp:
            for g in res.gaps:
                cp.write_row(
                    (
                        g.meter_id,
                        g.interval_start,
                        g.interval_end,
                        g.missing_intervals,
                        g.reading_date,
                        g.feeder_id,
                        g.zone_id,
                        run_id,
                    )
                )


def build_silver_date(
    conn: psycopg.Connection, day: dt.date | str, run_id: str
) -> dict:
    """Rebuild silver for one UTC date. Returns a summary dict."""
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    create_silver_schema(conn)
    with conn.cursor() as cur:
        cur.execute(BRONZE_TS_INDEX)
    conn.commit()

    meters = fetch_meters(conn)
    events = _fetch_events(conn, day)
    res = normalise_day(events, meters, day, _prev_register(conn, day))
    bad_files = _unparseable_files(conn, day)
    try:
        _write(conn, day, res, bad_files, run_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    reasons: dict[str, int] = {}
    for q in res.quarantine:
        reasons[q.reason_code] = reasons.get(q.reason_code, 0) + 1
    if bad_files:
        reasons["UNPARSEABLE"] = reasons.get("UNPARSEABLE", 0) + len(bad_files)
    return {
        "run_id": run_id,
        "date": day.isoformat(),
        "readings": len(res.readings),
        "quarantined": sum(reasons.values()),
        "reasons": dict(sorted(reasons.items())),
        "gaps": len(res.gaps),
        "missing_intervals": sum(g.missing_intervals for g in res.gaps),
    }
