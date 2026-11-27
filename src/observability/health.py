"""GET /health on :8000 (HEALTH_PORT) — stdlib only, no web framework.

status:
  ok        DB reachable, last pipeline run succeeded, no alerts firing  -> 200
  degraded  as ok, but COMPLETENESS_DROP alerts fire on the latest date  -> 200
  down      DB unreachable, or the last pipeline run failed / no run yet -> 503

Run:  python -m src.observability.health   (or `make health`)
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg

from src.common.db import connect
from src.observability.schema import create_obs_schema

KEY_METRICS = (
    "completeness_pct",
    "dq_pass_rate",
    "dq_meter_days_flagged",
    "duplicate_rate",
    "ingest_lag_s",
    "quarantine_count",
    "readings",
    "run_duration_s",
)


def health_report() -> tuple[int, dict]:
    """(http_status, body). Never raises."""
    try:
        with connect(connect_timeout=3) as conn:
            create_obs_schema(conn)
            last = conn.execute(
                """SELECT run_id, status, started_at, ended_at, duration_s, error
                   FROM obs.run_log WHERE stage = 'pipeline'
                   ORDER BY started_at DESC LIMIT 1"""
            ).fetchone()
            (latest,) = conn.execute(
                "SELECT max(metric_date) FROM obs.metrics"
                " WHERE metric_name = 'completeness_pct'"
            ).fetchone()
            metrics: dict = {}
            alerts: list = []
            if latest:
                for name, scope, value in conn.execute(
                    """SELECT metric_name, scope, value FROM obs.metrics
                       WHERE metric_date = %s AND metric_name = ANY(%s)
                       ORDER BY 1, 2""",
                    (latest, list(KEY_METRICS)),
                ):
                    metrics.setdefault(name, {})[scope] = (
                        float(value) if value is not None else None
                    )
                alerts = [
                    {"alert": a, "scope": s, "value": float(v), "message": m}
                    for a, s, v, m in conn.execute(
                        """SELECT alert_name, scope, value, message FROM obs.alert
                           WHERE metric_date = %s ORDER BY scope""",
                        (latest,),
                    )
                ]
    except psycopg.Error as exc:
        return 503, {"status": "down", "db": "unreachable", "error": str(exc)[:300]}

    run = None
    if last:
        run = dict(
            zip(
                ("run_id", "status", "started_at", "ended_at", "duration_s", "error"),
                last,
            )
        )
    if run is None or run["status"] == "failed":
        status, code = "down", 503
    else:  # success, or a run in progress
        status, code = ("degraded" if alerts else "ok"), 200
    body = {
        "status": status,
        "db": "ok",
        "last_run": run,
        "latest_metric_date": latest,
        "metrics": metrics,
        "alerts_firing": alerts,
    }
    return code, json.loads(json.dumps(body, default=str))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") != "/health":
            self.send_error(404, "try /health")
            return
        code, body = health_report()
        data = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # quieter console
        print(f"[health] {self.address_string()} {fmt % args}")


def serve(port: int | None = None) -> None:
    port = port or int(os.environ.get("HEALTH_PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    print(f"[health] serving http://localhost:{port}/health")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    serve()
