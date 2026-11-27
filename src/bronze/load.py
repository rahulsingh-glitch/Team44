"""Bronze loader: land raw landing JSON into bronze.meter_events_raw.

Rules (CLAUDE.md §3, builder spec step 2):
  * Land every event payload UNTOUCHED (JSONB), recording schema_version per event.
  * Write bronze.load_log for every file (loaded / skipped_duplicate / unparseable).
  * Skip re-delivered files by CHECKSUM (not filename) -> idempotent re-runs.
  * No business validation here (unknown meters, negatives, dupes all land as-is);
    that is silver/dq's job.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from src.bronze.schema import create_bronze_schema
from src.common.checksum import file_checksum
from src.storage.partitions import ensure_partition

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_run_id(prefix: str = "bronze") -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def infer_schema_version(event: dict) -> int:
    """Per-event schema version: payload field if valid, else infer from v2 fields."""
    sv = event.get("schema_version")
    if sv in (1, 2):
        return int(sv)
    return 2 if ("voltage" in event or "firmware" in event) else 1


def _source_date(path: Path) -> dt.date | None:
    name = path.parent.name
    if DATE_RE.match(name):
        return dt.date.fromisoformat(name)
    return None


def iter_landing_files(landing: Path, date: str) -> list[Path]:
    """All *.json files for one landing date, sorted (re-deliveries after originals)."""
    day_dir = landing / date
    if not day_dir.is_dir():
        return []
    return sorted(day_dir.glob("*.json"))


def discover_dates(landing: Path) -> list[str]:
    return sorted(
        p.name for p in landing.iterdir() if p.is_dir() and DATE_RE.match(p.name)
    )


def preload_loaded_checksums(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT file_checksum FROM bronze.load_log WHERE status = 'loaded'"
        )
        return {r[0] for r in cur.fetchall()}


def load_file(
    conn: psycopg.Connection,
    path: Path,
    run_id: str,
    landing: Path,
    seen: set[str],
) -> dict:
    """Load one landing file in a single transaction. Returns a summary dict."""
    source_file = path.relative_to(landing).as_posix()
    checksum = file_checksum(path)
    source_date = _source_date(path)

    # --- re-delivery: identical bytes already loaded -> skip (log it)
    if checksum in seen:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bronze.load_log "
                "(run_id, source_file, file_checksum, source_date, row_count, status, reason) "
                "VALUES (%s, %s, %s, %s, 0, 'skipped_duplicate', %s)",
                (
                    run_id,
                    source_file,
                    checksum,
                    source_date,
                    "re-delivered (checksum seen)",
                ),
            )
        conn.commit()
        return {"file": source_file, "status": "skipped_duplicate", "rows": 0}

    # --- parse
    try:
        events = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(events, list):
            raise TypeError("landing file is not a JSON array of events")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bronze.load_log "
                "(run_id, source_file, file_checksum, source_date, row_count, status, reason) "
                "VALUES (%s, %s, %s, %s, 0, 'unparseable', %s)",
                (
                    run_id,
                    source_file,
                    checksum,
                    source_date,
                    f"UNPARSEABLE: {exc}"[:300],
                ),
            )
        conn.commit()
        return {"file": source_file, "status": "unparseable", "rows": 0}

    # --- land every event untouched
    rows = [
        (
            run_id,
            source_file,
            checksum,
            source_date,
            infer_schema_version(ev),
            Jsonb(ev),
        )
        for ev in events
    ]
    if source_date is not None:
        ensure_partition(conn, "bronze.meter_events_raw", source_date)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bronze.meter_events_raw "
            "(run_id, source_file, file_checksum, source_date, schema_version, raw) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute(
            "INSERT INTO bronze.load_log "
            "(run_id, source_file, file_checksum, source_date, row_count, status) "
            "VALUES (%s, %s, %s, %s, %s, 'loaded')",
            (run_id, source_file, checksum, source_date, len(rows)),
        )
    conn.commit()
    seen.add(checksum)
    return {"file": source_file, "status": "loaded", "rows": len(rows)}


def _summarise(results: list[dict], run_id: str) -> dict:
    summary = {
        "run_id": run_id,
        "loaded": 0,
        "skipped_duplicate": 0,
        "unparseable": 0,
        "rows": 0,
    }
    for r in results:
        summary[r["status"]] += 1
        summary["rows"] += r["rows"]
    return summary


def load_date(
    conn: psycopg.Connection, landing: Path, date: str, run_id: str | None = None
) -> dict:
    """Land all files for one date. Idempotent via checksum skip."""
    run_id = run_id or new_run_id()
    create_bronze_schema(conn)
    seen = preload_loaded_checksums(conn)
    results = [
        load_file(conn, p, run_id, landing, seen)
        for p in iter_landing_files(landing, date)
    ]
    return _summarise(results, run_id)


def load_all(
    conn: psycopg.Connection, landing: Path, run_id: str | None = None
) -> dict:
    """Land every discovered date under the landing dir."""
    run_id = run_id or new_run_id()
    create_bronze_schema(conn)
    seen = preload_loaded_checksums(conn)
    results: list[dict] = []
    for date in discover_dates(landing):
        results += [
            load_file(conn, p, run_id, landing, seen)
            for p in iter_landing_files(landing, date)
        ]
    return _summarise(results, run_id)
