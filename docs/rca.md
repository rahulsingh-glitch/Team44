# RCA — `gridpulse_pipeline` failed with `FileNotFoundError` (missing landing files)

| | |
|---|---|
| **Date** | 2026-11-27 (UTC) |
| **System** | Airflow 3.3 DAG `gridpulse_pipeline`, task `land`; observability (`obs.run_log`, `/health`) |
| **Trigger** | Deliberate negative test: `airflow dags test gridpulse_pipeline 2025-09-10` |
| **Severity** | Test environment only, no data affected. The **detection gap** it exposed would be high in production |
| **Status** | Resolved: gap fixed and re-verified. Follow-ups open (see §7) |

## 1. What happened
We ran the pipeline DAG for a date with no landing files, to prove that a late or missing
source fails loudly. The seed data only covers 2025-09-01 to 2025-09-03.

The DAG itself behaved as designed:
- The `land` task raised `FileNotFoundError: no landing files for ['2025-09-10'] under /opt/airflow/gridpulse/data/landing (late or missing source)`.
- Airflow retried it twice (2 × 2 min), then marked the task and the DAG run `failed`.
- No downstream task ran, so no data was written.

**The incident is what observability did on the first attempt.** With the original `land` code:
- The failure left **no row at all** in `obs.run_log`.
- `/health` therefore kept reporting the **previous successful run** and returned `200`.

A whole day's data could go missing while the health page said everything was fine.

## 2. Impact
- **Actual:** none. It was a test run on a date with no data, and nothing was written to bronze, silver or gold.
- **Potential (production):** a silent failure. For a day whose files are late or missing:
  - Airflow shows the task as red, but our own signals don't.
  - `/health` stays `200 ok/degraded`.
  - The run log has no failed run.
  - The `COMPLETENESS_DROP` alert **cannot fire** either. It is computed in the `publish` task, which never runs when `land` fails, so no metrics exist for that date (see §7).
  - Gold, billing and the dashboard simply have no rows for that day.

## 3. Root cause
**Ordering bug in the `land` task** (`dags/gridpulse_pipeline.py`):

```python
dates = _dates(ctx)
missing = [...]                       # 1. check landing files
if missing:
    raise FileNotFoundError(...)      # 2. fails HERE ...
start_run(_run_id(ctx), {...})        # 3. ... so the whole-run row is never opened
```

The DAG's whole-run tracking has three parts:
- `start_run()` opens the run's `pipeline` row in `obs.run_log`, in the first task.
- `finish_run()` closes it, in `publish` or in the task failure callback `_mark_failed`.
- `/health` reads the **latest `pipeline` row**.

Because the file check came **before** `start_run()`:
1. The failure happened before any `pipeline` row existed for the run.
2. The failure callback called `finish_run(..., "failed")`. That was an `UPDATE … WHERE run_id = …`, which matched **0 rows** and did nothing, with no error.
3. `/health` still saw the last successful run.

**Why it wasn't caught earlier:** the CLI path (`make run`) wraps the whole run in `track()`, which inserts the row *before* any work starts, so it never had this gap. The gap only exists in the multi-task DAG path, where the open and the close happen in different tasks. Our earlier observability tests only went through the CLI path.

## 4. Evidence
**Airflow task log** (rerun after the fix, run `manual__2026-11-27T11:33:53.426146+00:00`):

| Time (UTC) | Event |
|---|---|
| 11:34:02.40 | `land` attempt 1: `FileNotFoundError` → `up_for_retry` |
| 11:36:02.67 | `land` attempt 2: `FileNotFoundError` → `up_for_retry` |
| 11:38:02.81 | `land` attempt 3: `FileNotFoundError` → `failed` |
| 11:38:02.84 | `Marking run … failed` / `DagRun Finished` |

**Run log** (`obs.run_log`):
- First test run under the old `land` code (`af-manual__2026-11-27T11:30:29…`): **0 rows**. This is the gap.
- Rerun after the fix (`af-manual__2026-11-27T11:33:53…`): one row with `stage=pipeline`, `status=failed`, and error `task land: no landing files for ['2025-09-10'] under /opt/airflow/gridpulse/data/landing (late or missing source)`.

**`/health` after the fix:** `503`, `"status": "down"`, with `last_run.error` set to the message above.

## 5. Fix
Two changes, both applied and re-verified:
1. **`dags/gridpulse_pipeline.py`:** `land` now calls `start_run()` **first**, before checking the files. Any failure in `land` then has a row to mark `failed`.
2. **`src/observability/run_log.py`:** `finish_run()` now **inserts the `pipeline` row if it doesn't exist**, before updating it. Any failure before `start_run()` (an import error, a bad parameter, a context problem) is now recorded too, instead of the update silently matching nothing.

**Verification:** after the fix, the run log shows `failed` with the error, `/health` returns 503, and Airflow's own result is unchanged: the task fails after 2 retries.

## 6. Timeline (UTC, 2026-11-27)
| Time | Event |
|---|---|
| 11:30:29 | First negative test started (old `land` code); `land` fails and goes to retry |
| ~11:31 | **Detected** by reviewing the test output against the code: no `pipeline` row for the run, so `/health` would stay green |
| ~11:32 | **Fixed**: `start_run()` moved first, and `finish_run()` creates the row if it's missing |
| ~11:33 | Old test run stopped (it was still testing the pre-fix code); leftover process killed in the scheduler container |
| 11:33:53 | Negative test rerun on the fixed code |
| 11:38:02 | Run marked `failed` after 3 attempts; run log `failed`; `/health` 503 → **verified** |

## 7. Prevention and follow-ups
| # | Action | Status |
|---|---|---|
| P1 | Regression test: `test_dag_land_failure_marks_run_failed_and_health_503`. It calls `land` with no landing files and asserts a `failed` `pipeline` row in the run log and a 503 from `/health`. | **Open**, for the tester |
| P2 | Regression test: `test_finish_run_creates_row_when_never_started`. `finish_run()` with no prior `start_run()` should insert a `failed` row. | **Open**, for the tester |
| P3 | **Freshness alert** for an expected date with no landing files: today only `/health` catches this, because `COMPLETENESS_DROP` needs metrics that never get computed. This is T5 in `docs/test-plan.md`: `test_late_file_raises_freshness_failure`. | **Open** |
| P4 | On a retry, `start_run()` deletes and re-inserts the `pipeline` row, so `started_at` and `duration_s` cover only the **last attempt**: the rerun shows 0.014 s instead of about 4 min. It should keep the first attempt's `started_at` and count attempts. | **Open** (found during this RCA) |
| P5 | Runbook §4 row for "DAG `land` retries then fails" | **Done** |

## 8. Lessons
- **A failure that observability doesn't record is worse than the failure itself.** Every whole-run tracker has to be opened before the first thing that can fail, and closing it must work even if it was never opened.
- **Test the negative path through every entry point.** The CLI and the DAG share the stage code but not the run-tracking code, so the CLI's green results didn't prove anything about the DAG.
- **A silent no-op is a bug.** An `UPDATE` that matches 0 rows during failure handling should be treated as a problem, never ignored.
