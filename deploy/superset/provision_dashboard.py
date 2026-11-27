"""Provision the GridPulse Superset dashboard via the REST API (stdlib only).

Idempotent upsert by name: database connection -> one dataset per mart.* view
-> charts -> dashboard "GridPulse" (slug gridpulse) with 4 tabs and a zone
filter. Re-running updates in place; nothing is duplicated.

    python deploy/superset/provision_dashboard.py            # provision
    python deploy/superset/provision_dashboard.py --verify   # + run every chart query

Env: SUPERSET_URL (http://localhost:8088), SUPERSET_ADMIN_USER/PASSWORD
(admin/admin), SUPERSET_WAREHOUSE_URI (the warehouse as seen FROM the Superset
container: postgresql+psycopg2://postgres:postgres@warehouse:5432/lakehouse).
Run `python -m src.marts.views` first (`make dashboard` does both).
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088").rstrip("/")
USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")
DB_NAME = "GridPulse warehouse"
DB_URI = os.environ.get(
    "SUPERSET_WAREHOUSE_URI",
    "postgresql+psycopg2://postgres:postgres@warehouse:5432/lakehouse",
)
SCHEMA = "mart"
DASH_TITLE, DASH_SLUG = "GridPulse", "gridpulse"


# ----------------------------------------------------------------- client
class Superset:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.headers = {"Content-Type": "application/json"}
        tok = self.call(
            "POST",
            "/api/v1/security/login",
            {
                "username": USER,
                "password": PASSWORD,
                "provider": "db",
                "refresh": False,
            },
        )["access_token"]
        self.headers["Authorization"] = f"Bearer {tok}"
        self.headers["Referer"] = BASE
        self.headers["X-CSRFToken"] = self.call("GET", "/api/v1/security/csrf_token/")[
            "result"
        ]

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            BASE + path, data=data, method=method, headers=self.headers
        )
        try:
            with self.http.open(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"{method} {path} -> {e.code}: {e.read()[:600]!r}"
            ) from None
        return json.loads(raw) if raw else {}

    def list_all(self, resource: str) -> list[dict]:
        q = urllib.parse.quote("(page:0,page_size:100)")
        return self.call("GET", f"/api/v1/{resource}/?q={q}")["result"]


# ------------------------------------------------------------- chart specs
def sql_metric(expr: str, label: str) -> dict:
    return {"expressionType": "SQL", "sqlExpression": expr, "label": label}


def ts(x: str, grain: str, metrics: list, groupby=(), **extra) -> dict:
    return {
        "x_axis": x,
        "time_grain_sqla": grain,
        "metrics": metrics,
        "groupby": list(groupby),
        "row_limit": 10000,
        "adhoc_filters": [],
        "show_legend": True,
        "rich_tooltip": True,
        **extra,
    }


def raw_table(
    cols: list[str], order: str, desc: bool = True, limit: int = 200, filters=()
) -> dict:
    return {
        "query_mode": "raw",
        "all_columns": cols,
        "order_by_cols": [json.dumps([order, not desc])],
        "row_limit": limit,
        "adhoc_filters": list(filters),
        "server_pagination": False,
        "table_timestamp_format": "%Y-%m-%d %H:%M",
    }


def agg_table(groupby: list[str], metrics: list, order_desc: bool = True) -> dict:
    return {
        "query_mode": "aggregate",
        "groupby": groupby,
        "metrics": metrics,
        "row_limit": 1000,
        "order_desc": order_desc,
        "adhoc_filters": [],
    }


KWH = sql_metric("SUM(energy_kwh)", "kWh")


# (tab, slice_name, dataset view, viz_type, params, width)
def where(sql: str) -> dict:
    return {"expressionType": "SQL", "clause": "WHERE", "sqlExpression": sql}


def pie(groupby: str, metric: dict, filters=()) -> dict:
    return {
        "groupby": [groupby],
        "metric": metric,
        "adhoc_filters": list(filters),
        "row_limit": 100,
        "show_labels": True,
        "label_type": "key_value_percent",
        "show_legend": True,
        "donut": True,
    }


COUNT = sql_metric("COUNT(*)", "count")

# (tab, slice_name, dataset view, viz_type, params, width)
# Order = layout: charts fill rows left->right, a new row starts when the next
# chart would pass 12 columns. Each table sits next to its visual companion.
CHARTS: list[tuple] = [
    # ---------------------------------------------------- Feeder consumption
    (
        "Feeder consumption",
        "Daily kWh per feeder",
        "feeder_consumption_daily",
        "echarts_timeseries_line",
        ts("reading_date", "P1D", [KWH], ["feeder_id"], markerEnabled=True),
        6,
    ),
    (
        "Feeder consumption",
        "Hourly kWh per feeder",
        "feeder_consumption_hourly",
        "echarts_timeseries_bar",
        ts("hour_ts", "PT1H", [KWH], ["feeder_id"], stack="Stack"),
        6,
    ),
    (
        "Feeder consumption",
        "Meters by billing status",
        "billing_status",
        "pie",
        pie("billing_status", sql_metric("SUM(meters)", "meters")),
        4,
    ),
    (
        "Feeder consumption",
        "Billing status by month",
        "billing_status",
        "table",
        agg_table(
            ["billing_month", "billing_status"],
            [
                sql_metric("SUM(meters)", "meters"),
                KWH,
                sql_metric("ROUND(AVG(avg_completeness_pct), 2)", "avg completeness %"),
            ],
        ),
        8,
    ),
    # ------------------------------------------------------------- Anomalies
    (
        "Anomalies",
        "Anomalies by type",
        "anomaly_list",
        "echarts_timeseries_bar",
        ts("anomaly_type", None, [COUNT], []),
        6,
    ),
    (
        "Anomalies",
        "Anomalies per feeder",
        "anomaly_list",
        "echarts_timeseries_bar",
        ts("feeder_id", None, [COUNT], ["anomaly_type"], stack="Stack"),
        6,
    ),
    (
        "Anomalies",
        "Anomaly list",
        "anomaly_list",
        "table",
        raw_table(
            [
                "detected_date",
                "anomaly_type",
                "meter_id",
                "feeder_id",
                "zone_id",
                "window_start",
                "window_hours",
                "score",
                "summary",
            ],
            "detected_date",
        ),
        12,
    ),
    # ----------------------------------------------------- Data completeness
    (
        "Data completeness",
        "Completeness % per zone",
        "zone_completeness",
        "echarts_timeseries_line",
        ts(
            "reading_date",
            "P1D",
            [sql_metric("MAX(completeness_pct)", "completeness %")],
            ["zone_id"],
            markerEnabled=True,
            y_axis_format=".2f",
        ),
        6,
    ),
    (
        "Data completeness",
        "Meter-days flagged per zone",
        "zone_completeness",
        "echarts_timeseries_bar",
        ts(
            "reading_date",
            "P1D",
            [sql_metric("SUM(meter_days_flagged)", "meter-days flagged")],
            ["zone_id"],
            adhoc_filters=[where("zone_id <> 'ALL'")],
        ),
        6,
    ),
    (
        "Data completeness",
        "Completeness by zone and day",
        "zone_completeness",
        "table",
        raw_table(
            ["reading_date", "zone_id", "completeness_pct", "meter_days_flagged"],
            "reading_date",
        ),
        5,
    ),
    (
        "Data completeness",
        "Rows caught per DQ check",
        "dq_scorecard",
        "echarts_timeseries_bar",
        ts(
            "check_date",
            "P1D",
            [sql_metric("SUM(rows_caught)", "rows caught")],
            ["check_name"],
            stack="Stack",
            adhoc_filters=[where("check_name <> 'COMPLETENESS'")],
        ),
        7,
    ),
    (
        "Data completeness",
        "DQ scorecard",
        "dq_scorecard",
        "table",
        raw_table(
            [
                "check_date",
                "check_name",
                "status",
                "pass_rate",
                "threshold",
                "rows_checked",
                "rows_caught",
                "invariant_ok",
            ],
            "check_date",
        ),
        12,
    ),
    # ------------------------------------------------------- Pipeline health
    (
        "Pipeline health",
        "DQ pass rate (latest)",
        "pipeline_metrics",
        "big_number",
        {
            "x_axis": "metric_date",
            "time_grain_sqla": "P1D",
            "metric": sql_metric("MAX(dq_pass_rate)", "dq_pass_rate"),
            "y_axis_format": ".4f",
            "show_trend_line": True,
            "start_y_axis_at_zero": False,
            "adhoc_filters": [],
        },
        3,
    ),
    (
        "Pipeline health",
        "Run duration and ingest lag (s)",
        "pipeline_metrics",
        "echarts_timeseries_line",
        ts(
            "metric_date",
            "P1D",
            [
                sql_metric("MAX(run_duration_s)", "run duration s"),
                sql_metric("MAX(ingest_lag_s)", "ingest lag s"),
            ],
            markerEnabled=True,
        ),
        9,
    ),
    (
        "Pipeline health",
        "Pipeline runs by status",
        "pipeline_runs",
        "pie",
        pie("status", COUNT, [where("stage = 'pipeline'")]),
        3,
    ),
    (
        "Pipeline health",
        "Average stage duration (s)",
        "pipeline_runs",
        "echarts_timeseries_bar",
        ts(
            "stage",
            None,
            [sql_metric("ROUND(AVG(duration_s), 3)", "avg duration s")],
            [],
            adhoc_filters=[where("stage <> 'pipeline'")],
        ),
        5,
    ),
    (
        "Pipeline health",
        "Alerts per zone",
        "alerts",
        "echarts_timeseries_bar",
        ts("zone_id", None, [COUNT], []),
        4,
    ),
    (
        "Pipeline health",
        "Recent pipeline runs",
        "pipeline_runs",
        "table",
        raw_table(
            ["started_at", "run_id", "status", "duration_s", "rows_out", "error"],
            "started_at",
            limit=50,
            filters=[where("stage = 'pipeline'")],
        ),
        7,
    ),
    (
        "Pipeline health",
        "Fired alerts",
        "alerts",
        "table",
        raw_table(
            [
                "metric_date",
                "zone_id",
                "completeness_pct",
                "baseline_pct",
                "worst_feeder",
                "message",
            ],
            "metric_date",
        ),
        5,
    ),
]
TABS = ["Feeder consumption", "Anomalies", "Data completeness", "Pipeline health"]
ZONE_DATASETS = {
    "feeder_consumption_daily",
    "feeder_consumption_hourly",
    "billing_status",
    "anomaly_list",
    "zone_completeness",
    "alerts",
}


# --------------------------------------------------------------- upserts
def upsert_database(ss: Superset) -> int:
    body = {
        "database_name": DB_NAME,
        "sqlalchemy_uri": DB_URI,
        "expose_in_sqllab": True,
    }
    for d in ss.list_all("database"):
        if d["database_name"] == DB_NAME:
            ss.call("PUT", f"/api/v1/database/{d['id']}", body)
            return d["id"]
    return ss.call("POST", "/api/v1/database/", body)["id"]


def upsert_dataset(ss: Superset, db_id: int, view: str, existing: list[dict]) -> int:
    for d in existing:
        if d["table_name"] == view and d.get("schema") == SCHEMA:
            ss.call(
                "PUT", f"/api/v1/dataset/{d['id']}/refresh"
            )  # pick up column changes
            return d["id"]
    return ss.call(
        "POST",
        "/api/v1/dataset/",
        {"database": db_id, "schema": SCHEMA, "table_name": view},
    )["id"]


def upsert_chart(
    ss: Superset, name: str, viz: str, ds_id: int, params: dict, existing
) -> dict:
    p = {**params, "viz_type": viz, "datasource": f"{ds_id}__table"}
    body = {
        "slice_name": name,
        "viz_type": viz,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(p),
    }
    for c in existing:
        if c["slice_name"] == name:
            ss.call("PUT", f"/api/v1/chart/{c['id']}", body)
            return ss.call("GET", f"/api/v1/chart/{c['id']}")["result"] | {
                "id": c["id"]
            }
    cid = ss.call("POST", "/api/v1/chart/", body)["id"]
    return ss.call("GET", f"/api/v1/chart/{cid}")["result"] | {"id": cid}


def layout(charts: list[dict]) -> dict:
    """position_json: header + one TABS with a TAB per group, rows of <= 12 cols."""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["TABS-main"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "id": "HEADER_ID",
            "type": "HEADER",
            "meta": {"text": DASH_TITLE},
        },
        "TABS-main": {
            "type": "TABS",
            "id": "TABS-main",
            "children": [],
            "parents": ["ROOT_ID"],
            "meta": {},
        },
    }
    for ti, tab in enumerate(TABS):
        tab_id = f"TAB-{ti}"
        pos["TABS-main"]["children"].append(tab_id)
        pos[tab_id] = {
            "type": "TAB",
            "id": tab_id,
            "children": [],
            "parents": ["ROOT_ID", "TABS-main"],
            "meta": {"text": tab, "defaultText": "Tab title"},
        }
        row, used, ri = None, 12, 0
        for c in (c for c in charts if c["tab"] == tab):
            if used + c["width"] > 12:
                row, used, ri = f"ROW-{ti}-{ri}", 0, ri + 1
                pos[tab_id]["children"].append(row)
                pos[row] = {
                    "type": "ROW",
                    "id": row,
                    "children": [],
                    "parents": ["ROOT_ID", "TABS-main", tab_id],
                    "meta": {"background": "BACKGROUND_TRANSPARENT"},
                }
            cid = f"CHART-{c['id']}"
            pos[row]["children"].append(cid)
            pos[cid] = {
                "type": "CHART",
                "id": cid,
                "children": [],
                "parents": ["ROOT_ID", "TABS-main", tab_id, row],
                "meta": {
                    "chartId": c["id"],
                    "width": c["width"],
                    "height": 50,
                    "sliceName": c["name"],
                    "uuid": c.get("uuid"),
                },
            }
            used += c["width"]
    return pos


def metadata(charts: list[dict], zone_ds: int) -> dict:
    in_scope = [c["id"] for c in charts if c["view"] in ZONE_DATASETS]
    excluded = [c["id"] for c in charts if c["view"] not in ZONE_DATASETS]
    return {
        "color_scheme": "supersetColors",
        "refresh_frequency": 0,
        "cross_filters_enabled": False,
        "native_filter_configuration": [
            {
                "id": "NATIVE_FILTER-zone",
                "name": "Zone",
                "filterType": "filter_select",
                "type": "NATIVE_FILTER",
                "targets": [{"datasetId": zone_ds, "column": {"name": "zone_id"}}],
                "controlValues": {
                    "multiSelect": True,
                    "enableEmptyFilter": False,
                    "defaultToFirstItem": False,
                    "inverseSelection": False,
                    "searchAllOptions": False,
                },
                "defaultDataMask": {
                    "extraFormData": {},
                    "filterState": {},
                    "ownState": {},
                },
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
                "chartsInScope": in_scope,
                "tabsInScope": [],
                "description": "Filter zone-level charts",
            }
        ],
    }


def upsert_dashboard(ss: Superset, charts: list[dict], zone_ds: int) -> int:
    body = {
        "dashboard_title": DASH_TITLE,
        "slug": DASH_SLUG,
        "published": True,
        "position_json": json.dumps(layout(charts)),
        "json_metadata": json.dumps(metadata(charts, zone_ds)),
    }
    for d in ss.list_all("dashboard"):
        if d.get("slug") == DASH_SLUG:
            ss.call("PUT", f"/api/v1/dashboard/{d['id']}", body)
            return d["id"]
    return ss.call("POST", "/api/v1/dashboard/", body)["id"]


# ----------------------------------------------------------------- verify
def verify_query(c: dict) -> dict:
    """Minimal query equivalent to the chart, run through Superset itself."""
    p = c["params"]
    if c["viz"] == "table" and p.get("query_mode") == "raw":
        q = {
            "columns": p["all_columns"],
            "metrics": [],
            "filters": [],
            "extras": {
                "where": " AND ".join(f["sqlExpression"] for f in p["adhoc_filters"])
            },
            "row_limit": p["row_limit"],
        }
    elif c["viz"] == "table":
        q = {
            "columns": p["groupby"],
            "metrics": p["metrics"],
            "row_limit": p["row_limit"],
        }
    else:  # timeseries / categorical bar / pie / big number
        metrics = p.get("metrics") or [p["metric"]]
        cols = ([p["x_axis"]] if p.get("x_axis") else []) + list(p.get("groupby", []))
        q = {
            "columns": cols,
            "metrics": metrics,
            "extras": {
                "where": " AND ".join(f["sqlExpression"] for f in p["adhoc_filters"])
            },
            "row_limit": 10000,
        }
    return {
        "datasource": {"id": c["ds_id"], "type": "table"},
        "queries": [q],
        "result_format": "json",
        "result_type": "full",
        "force": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="run every chart's query")
    a = ap.parse_args()

    ss = Superset()
    db_id = upsert_database(ss)
    existing_ds = ss.list_all("dataset")
    ds = {v: upsert_dataset(ss, db_id, v, existing_ds) for v in {c[2] for c in CHARTS}}
    existing_ch = ss.list_all("chart")
    charts = []
    for tab, name, view, viz, params, width in CHARTS:
        r = upsert_chart(ss, name, viz, ds[view], params, existing_ch)
        charts.append(
            {
                "tab": tab,
                "name": name,
                "view": view,
                "viz": viz,
                "params": params,
                "width": width,
                "id": r["id"],
                "uuid": r.get("uuid"),
                "ds_id": ds[view],
            }
        )
    dash_id = upsert_dashboard(ss, charts, ds["zone_completeness"])
    for c in charts:  # link chart <-> dashboard (position_json alone does not)
        ss.call("PUT", f"/api/v1/chart/{c['id']}", {"dashboards": [dash_id]})
    print(
        f"[superset] database={db_id} datasets={len(ds)} charts={len(charts)} "
        f"dashboard={dash_id} -> {BASE}/superset/dashboard/{DASH_SLUG}/"
    )

    if not a.verify:
        return 0
    bad = 0
    for c in charts:
        try:
            res = ss.call("POST", "/api/v1/chart/data", verify_query(c))["result"][0]
            n, err = res.get("rowcount"), res.get("error")
        except RuntimeError as exc:
            n, err = None, str(exc)
        ok = err is None and n
        bad += not ok
        print(
            f"[verify] {'OK ' if ok else 'BAD'} {c['tab']:<18} | {c['name']:<32} rows={n}"
            + (f" error={err}" if err else "")
        )
    print(f"[verify] {len(charts) - bad}/{len(charts)} charts returned data")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
