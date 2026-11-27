"""GridPulse pipeline DAG (Airflow 3.3) — file-based landing ONLY, no Kafka.

    land -> bronze -> silver -> dq -> consumption -> anomaly -> publish

Each task calls the SAME stage function the CLI uses (src/pipeline.py), so
`make run` and this DAG produce identical output.

Dates: the run's logical date by default; trigger with params
{"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"} to process a range in one
run (= `make backfill`). Or `airflow backfill create` one run per date
(max_active_runs=1 keeps dates in order: silver reads D±1, TAMPER reads D-1).

- land   : fails if a date has no landing files (late file -> retried)
- dq     : DQ gate failure -> AirflowFailException (deterministic, NO retry)
- obs    : run_id "af-<airflow run_id>"; each stage timed into obs.run_log;
           the whole-run 'pipeline' row is opened in land, closed in publish,
           and marked failed by the task failure callback (-> /health 503).
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from airflow.sdk import Param, dag, get_current_context, task

try:  # Airflow 3 SDK location, with fallback
    from airflow.sdk.exceptions import AirflowFailException
except ImportError:  # pragma: no cover
    from airflow.exceptions import AirflowFailException

LANDING = Path(
    os.environ.get("GRIDPULSE_LANDING", "/opt/airflow/gridpulse/data/landing")
)


def _run_id(context) -> str:
    return f"af-{context['run_id']}"


def _dates(context) -> list[str]:
    from src.pipeline import date_range

    params = context.get("params") or {}
    if params.get("date_from"):
        return date_range(
            params["date_from"], params.get("date_to") or params["date_from"]
        )
    logical = context.get("logical_date") or context["dag_run"].run_after
    return [logical.date().isoformat()]


def _mark_failed(context) -> None:
    """Task failure callback (after the last retry): close the whole-run row."""
    from src.observability.run_log import finish_run

    ti = context.get("task_instance")
    exc = context.get("exception")
    task_id = getattr(ti, "task_id", "?")
    finish_run(_run_id(context), "failed", error=f"task {task_id}: {exc}")


DEFAULT_ARGS = {
    "owner": "team44",
    "retries": 2,
    "retry_delay": dt.timedelta(minutes=2),
    "execution_timeout": dt.timedelta(minutes=30),
    "on_failure_callback": _mark_failed,
}


@dag(
    dag_id="gridpulse_pipeline",
    description="GridPulse smart-meter pipeline: landing -> bronze -> silver -> dq -> gold -> anomaly -> obs",
    schedule="@daily",
    start_date=dt.datetime(2025, 9, 1, tzinfo=dt.UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={
        "date_from": Param(
            None,
            type=["null", "string"],
            format="date",
            description="optional range start (YYYY-MM-DD)",
        ),
        "date_to": Param(
            None,
            type=["null", "string"],
            format="date",
            description="optional range end (YYYY-MM-DD)",
        ),
    },
    tags=["gridpulse", "telemetry"],
)
def gridpulse_pipeline():
    @task
    def land() -> list[str]:
        from src.observability.run_log import start_run

        ctx = get_current_context()
        dates = _dates(ctx)
        # open the whole-run row FIRST, so a missing-file failure is visible
        start_run(_run_id(ctx), {"dag_run": ctx["run_id"], "dates": dates})
        missing = [
            d
            for d in dates
            if not (LANDING / d).is_dir() or not any((LANDING / d).glob("*.json"))
        ]
        if missing:
            raise FileNotFoundError(
                f"no landing files for {missing} under {LANDING} (late or missing source)"
            )
        print(f"[land] dates={dates} landing={LANDING}")
        return dates

    @task
    def bronze(dates: list[str]) -> dict:
        from src.pipeline import stage_bronze

        return stage_bronze(dates, _run_id(get_current_context()), LANDING)

    @task
    def silver(dates: list[str]) -> dict:
        from src.pipeline import stage_silver

        out = stage_silver(dates, _run_id(get_current_context()))
        return {
            s["date"]: {"readings": s["readings"], "quarantined": s["quarantined"]}
            for s in out
        }

    @task
    def dq(dates: list[str]) -> dict:
        from src.dq.checks import DQGateError
        from src.pipeline import stage_dq

        try:
            out = stage_dq(dates, _run_id(get_current_context()))
        except DQGateError as exc:  # bad data does not fix itself: no retry
            raise AirflowFailException(str(exc)) from exc
        return {s["date"]: s["dq_pass_rate"] for s in out}

    @task
    def consumption(dates: list[str]) -> dict:
        from src.pipeline import stage_gold

        out = stage_gold(dates, _run_id(get_current_context()))
        return {s["date"]: float(s["kwh"]) for s in out}

    @task
    def anomaly(dates: list[str]) -> dict:
        from src.pipeline import stage_anomaly

        out = stage_anomaly(dates, _run_id(get_current_context()))
        return {
            s["date"]: {k: s[k] for k in ("SPIKE", "TAMPER", "OUTAGE")} for s in out
        }

    @task
    def publish(dates: list[str]) -> dict:
        from src.common.db import connect
        from src.observability.metrics import record_run_duration
        from src.observability.run_log import finish_run
        from src.pipeline import stage_publish

        run_id = _run_id(get_current_context())
        res = stage_publish(dates, run_id, LANDING)
        duration = finish_run(run_id, "success")
        if duration is not None:
            with connect() as conn:
                record_run_duration(conn, dates[-1], run_id, duration)
        return {"alerts": [list(a) for a in res["alerts"]], "duration_s": duration}

    dates = land()
    b, s, q, g, a, p = (
        bronze(dates),
        silver(dates),
        dq(dates),
        consumption(dates),
        anomaly(dates),
        publish(dates),
    )
    b >> s >> q >> g >> a >> p


gridpulse_pipeline()
