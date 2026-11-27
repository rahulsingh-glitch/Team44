"""obs.run_log writer.

`track(run_id, stage, date)` times a block and records running -> success |
failed. It writes through its OWN autocommit connection, so a failed stage is
recorded even when the stage's transaction rolls back; the error is re-raised.

    with track(run_id, "silver", d) as t:
        s = build_silver_date(conn, d, run_id)
        t["rows_out"] = s["readings"]; t["detail"] = s
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import time
from collections.abc import Iterator

from src.common.db import connect
from src.observability.schema import create_obs_schema


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


@contextlib.contextmanager
def track(
    run_id: str, stage: str, metric_date: dt.date | str | None = None
) -> Iterator[dict]:
    info: dict = {"rows_out": None, "detail": None}
    with connect(autocommit=True) as log:
        create_obs_schema(log)
        (log_id,) = log.execute(
            "INSERT INTO obs.run_log (run_id, stage, metric_date, status)"
            " VALUES (%s, %s, %s, 'running') RETURNING log_id",
            (run_id, stage, metric_date),
        ).fetchone()
        t0 = time.perf_counter()
        status, error = "success", None
        try:
            yield info
        except BaseException as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            log.execute(
                "UPDATE obs.run_log SET status=%s, ended_at=now(), duration_s=%s,"
                " rows_out=%s, detail=%s, error=%s WHERE log_id=%s",
                (
                    status,
                    round(time.perf_counter() - t0, 3),
                    info["rows_out"],
                    json.dumps(_jsonable(info["detail"])) if info["detail"] else None,
                    error,
                    log_id,
                ),
            )
            if status == "failed":
                print(f"[obs] stage={stage} date={metric_date} FAILED: {error}")


# --- whole-run row spanning several processes (Airflow tasks) ---------------
# track() can't span tasks, so the DAG opens the 'pipeline' row in its first
# task and closes it in the last task (success) or a DAG failure callback.


def start_run(run_id: str, detail: dict | None = None) -> None:
    """Open (or re-open, on a task retry) the 'pipeline' row for run_id."""
    with connect(autocommit=True) as log:
        create_obs_schema(log)
        log.execute(
            "DELETE FROM obs.run_log WHERE run_id = %s AND stage = 'pipeline'",
            (run_id,),
        )
        log.execute(
            "INSERT INTO obs.run_log (run_id, stage, status, detail)"
            " VALUES (%s, 'pipeline', 'running', %s)",
            (run_id, json.dumps(_jsonable(detail)) if detail else None),
        )


def finish_run(
    run_id: str, status: str, error: str | None = None, rows_out: int | None = None
) -> float | None:
    """Close the 'pipeline' row; returns its duration in seconds. If the row
    was never opened (failure before start_run), one is created so the
    failure is still visible to /health."""
    with connect(autocommit=True) as log:
        create_obs_schema(log)
        log.execute(
            """INSERT INTO obs.run_log (run_id, stage, status)
               SELECT %s, 'pipeline', 'running'
               WHERE NOT EXISTS (SELECT 1 FROM obs.run_log
                                 WHERE run_id = %s AND stage = 'pipeline')""",
            (run_id, run_id),
        )
        row = log.execute(
            """UPDATE obs.run_log SET status = %s, ended_at = now(),
                      duration_s = round(extract(epoch FROM now() - started_at)::numeric, 3),
                      error = %s, rows_out = coalesce(%s, rows_out)
               WHERE run_id = %s AND stage = 'pipeline'
               RETURNING duration_s""",
            (status, (error or "")[:2000] or None, rows_out, run_id),
        ).fetchone()
    return float(row[0]) if row else None
