"""GridPulse storage maintenance DAG (ADR-0002) — kept off the main pipeline.

    retention -> compact_reindex

- retention       : DROP partitions past their window (raw 30d, silver/hourly
                    13mo). as_of = param, else the DATA clock (max silver date).
- compact_reindex : VACUUM (ANALYZE) + REINDEX CONCURRENTLY the last 3 days'
                    partitions (lock_timeout -> busy partitions skipped, reported).
"""

from __future__ import annotations

import datetime as dt

from airflow.sdk import Param, dag, get_current_context, task


@dag(
    dag_id="gridpulse_maintenance",
    description="Partition retention + compaction (VACUUM/REINDEX)",
    schedule="@daily",
    start_date=dt.datetime(2025, 9, 1, tzinfo=dt.UTC),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "team44",
        "retries": 1,
        "retry_delay": dt.timedelta(minutes=5),
    },
    params={
        "as_of": Param(
            None,
            type=["null", "string"],
            format="date",
            description="retention reference date; default = data clock",
        ),
        "dry_run": Param(False, type="boolean"),
    },
    tags=["gridpulse", "storage"],
)
def gridpulse_maintenance():
    @task
    def retention() -> list[str]:
        from src.storage.maintenance import retention as run_retention

        p = get_current_context()["params"]
        res = run_retention(p.get("as_of"), bool(p.get("dry_run")))
        verb = "would drop" if res["dry_run"] else "dropped"
        for part, lo, hi, table in res["dropped"]:
            print(f"[retention] {verb} {part} [{lo}, {hi}) of {table}")
        print(f"[retention] as_of={res['as_of']} {verb}={len(res['dropped'])}")
        return [d[0] for d in res["dropped"]]

    @task
    def compact_reindex() -> dict:
        from src.common.db import connect
        from src.storage.maintenance import compact, data_clock

        with connect() as conn:
            clock = data_clock(conn)
        if clock is None:
            return {"done": [], "skipped": []}
        res = compact([clock - dt.timedelta(days=i) for i in range(3)], reindex=True)
        print(f"[compact] done={len(res['done'])} skipped={res['skipped']}")
        return {"done": res["done"], "skipped": [list(s) for s in res["skipped"]]}

    retention() >> compact_reindex()


gridpulse_maintenance()
