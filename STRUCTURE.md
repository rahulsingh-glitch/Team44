# GridPulse — Full Target Repo Structure (checklist)

Tick each file as the agents build it. `(have)` = already exists from setup. `(build)` = an
agent creates it via `/build-layer`. Owner in brackets.

```
manthan-w2-b-team44/
├── CLAUDE.md                     (have) GridPulse rules + contract — read every session
├── README.md                     (have) what it is + how to run
├── START-HERE.md                 (have) team quick guide
├── MASTER-PROMPT.md              (have) lead's kickoff prompt
├── WORKFLOW.md                   (have) build→test→ship loop, git rules, role map
├── SUBMISSION.md                 (have) gates + 10 artifacts + demo checklist
├── STRUCTURE.md                  (this file) the build checklist
├── Makefile                      (have) make up/down/seed/run/test/backfill
├── requirements.txt              (have) pinned deps (incl dbt-postgres, faker, pandas)
├── .env.example                  (have) dummy config keys (commit this)
├── .env                          (have, gitignored) real local secrets
├── .gitignore                    (have)
│
├── .claude/
│   ├── agents/
│   │   ├── setup.md              (have) stack bring-up (Airflow+PG18 fixes)
│   │   ├── pipeline-builder.md   (have) GridPulse layers, files-only
│   │   ├── tester.md             (have) writes rule-stating tests
│   │   ├── reviewer.md           (have) pre-merge review
│   │   └── tracker.md            (have) status board
│   └── commands/
│       ├── setup-stack.md  build-layer.md  test-feature.md  grill.md
│       ├── ship.md  gates.md  rca.md  verify-e2e.md  logprompt.md  syncboard.md  (have)
│
├── deploy/
│   ├── docker-compose.yml        (have) Postgres18 + Airflow3.3 + Superset
│   ├── Makefile                  (have) included from root
│   ├── .env.example              (have)
│   ├── init-db/
│   │   └── 01_schemas.sql        (have) creates bronze/silver/gold/mart/obs  +ADD ref
│   ├── airflow/
│   │   ├── Dockerfile            (have) Airflow 3.3.1 + dbt-postgres
│   │   ├── requirements-airflow.txt  (have)
│   │   └── simple_auth_manager_passwords.json.generated  (have) admin/admin
│   └── scripts/
│       ├── gen_env.sh  wait_healthy.sh   (have)
│
├── dags/
│   └── gridpulse_dag.py          (build, Nabi) land→bronze→silver→dq→consumption→anomaly→publish; retries + backfill
│
├── scripts/
│   └── generate_synthetic_data.py (build, Jitesh) 5000 meters/20 feeders/6 zones, 15-min,
│                                   v1+v2 schema, Wh+kWh mix, defects; meter master CSV
│
├── src/
│   ├── common/
│   │   ├── db.py                 (build) Postgres connection helper
│   │   ├── checksum.py           (build) file checksum + ledger (re-delivery skip)
│   │   └── normalise.py          (build) Wh→kWh, UTC, unit detection
│   ├── bronze/
│   │   └── land.py               (build, Jitesh) land raw JSON + schema_version + load_log
│   ├── silver/
│   │   ├── normalise.py          (build, Jitesh) kWh, dedup, order, UTC
│   │   ├── gaps.py               (build, Jitesh) record missing 15-min intervals (NOT filled)
│   │   └── quarantine.py         (build, Jitesh) bad rows + reason_code
│   ├── gold/
│   │   ├── consumption.py        (build, Adarsh) hourly/daily per meter/feeder/zone
│   │   ├── billing.py            (build, Adarsh) monthly billing-ready per meter
│   │   └── anomaly.py            (build, Chetan) SPIKE / TAMPER / OUTAGE
│   ├── dq/
│   │   └── checks.py             (build, Chetan) meter exists, non-neg, register monotonic,
│   │                              completeness>90% → quality flag; dq_pass_rate→obs.metrics
│   ├── storage/
│   │   └── partitions.py         (build, Adarsh) range partition by date, zone index,
│   │                              compaction + retention (raw 30d / hourly 13mo)
│   ├── observability/
│   │   ├── run_log.py            (build, Nabi) obs.run_log helper
│   │   ├── metrics.py            (build, Nabi) ingest_lag, completeness, dup_rate, duration
│   │   ├── health.py             (build, Nabi) /health endpoint
│   │   └── alert.py              (build, Nabi) alert on completeness drop
│   └── pipeline.py               (build, Nabi) entrypoint: run <date> / backfill <range>
│
├── dbt/ (if using dbt for transforms)
│   ├── dbt_project.yml  profiles.example.yml   (build)
│   ├── models/
│   │   ├── staging/   stg_meter_events.sql + schema.yml (DQ tests)   (build)
│   │   └── marts/     consumption_hourly.sql  consumption_daily.sql  billing_monthly.sql (build)
│   └── (no snapshots — GridPulse has no SCD2)
│
├── dashboard/
│   └── superset_assets/          (build, Chetan) 4 tabs: feeder consumption, anomaly list,
│                                   completeness % per zone, pipeline-health
│
├── tests/
│   ├── test_units.py             (build) Wh→kWh, no double-convert
│   ├── test_dedup_order.py       (build) duplicates, out-of-order
│   ├── test_gaps.py              (build) missing interval = gap, not filled
│   ├── test_register.py          (build) decrease w/o rollover → quarantine
│   ├── test_idempotency.py       (build) re-run = identical consumption
│   ├── test_anomaly.py           (build) spike/tamper/outage fire; normal does NOT
│   ├── test_completeness.py      (build) <90% sets quality flag
│   └── test_deliberately_failing.py  (have) skipped; unskip proves CI red
│
├── .github/workflows/ci.yml      (have) ruff + black + pytest on push
│
└── docs/
    ├── gridpulse-plan.md         (have) roles, build order, demo
    ├── lld.md                    (fill) components, data model, interfaces
    ├── ideation.md               (fill) problem, options, trade-offs
    ├── runbook.md                (fill) operate/monitor/recover + RCA
    ├── test-plan.md              (fill) scope, matrix, results
    ├── claude-log.md             (fill live) prompts + corrections (15 pts)
    ├── clock.md                  (have) the 5-hour clock
    ├── status.csv                (have) task board
    └── adr/
        ├── ADR-0001-late-data.md            (fill, Rahul)
        ├── ADR-0002-partitioning-retention.md (fill, Rahul)
        └── ADR-0003-schema-evolution.md       (fill, Rahul)
```

## The 10 build steps (tick as you go)
- [ ] 1 synthetic data   [ ] 2 bronze        [ ] 3 silver normalisation   [ ] 4 consumption
- [ ] 5 anomalies        [ ] 6 data quality  [ ] 7 storage layout         [ ] 8 observability+alert
- [ ] 9 airflow dag      [ ] 10 dashboard

## Done =
make seed → make run → make test green → make run again = identical consumption (idempotent)
→ Superset shows 4 tabs → /gates ALL PASS → 10 artifacts in the shared folder.
EOF
echo "STRUCTURE.md written"