# Claude Usage Log — Team 44

> Scored under **Claude usage (15)**. Judges want prompt quality, plan-first,
> CLAUDE.md, and **corrections made** — not volume. Log the notable moments, not
> every keystroke. A correction you caught scores higher than flawless output.

| Time | Phase | Prompt intent (short) | What Claude produced | Our correction / decision |
|---|---|---|---|---|
| 09:30 | setup | stand up full stack (PG18 + Airflow 3.3 + Superset), prove fresh-clone start | docker-compose, Makefile, schema init, CI, pinned admin/admin | Caught 2 defects live: stale `superset-home` volume poisoned by an old SECRET_KEY → wiped + pinned project name `gridpulse`; scheduler healthcheck probed disabled :8974 server → switched to `airflow jobs check` |
| 10:05 | synthetic data | deterministic generator: meters/feeders/zones, v1/v2, Wh+kWh, planted defects + manifest | `scripts/generate_synthetic_data.py` (stdlib-only, seeded); dim_meter.csv + _manifest.json; 11/11 defect checks pass | Added cumulative `register` to every event (needed for rollover/decrease rules, beyond §7's v1 list); chose stdlib over Faker for byte-identical re-runs; `make seed` defaults small, `--full`=5000×90d |
| 10:20 | bronze | land raw JSON untouched, per-event schema_version, load_log, checksum skip | `src/bronze/{schema,load}.py`, `src/common/db.py`, wired `pipeline.run`; 17137 rows, 1 skip, 1 unparseable | Decisions: unparseable logged in load_log (quarantine deferred to silver); checksum-skip append-only idempotency (re-run = 0 new rows, verified) |
| | architecture | asked for locking/idempotency options | <<...>> | chose <<...>> because <<...>> |
| 10:36 | silver | plan-first silver normalisation: UNIT RULE, UTC, dedupe, order, register check, gaps, quarantine | `src/silver/{schema,normalise,load}.py`, `src/ref/dim_meter.py`, pipeline wired bronze→silver; seed: 17127 readings, 11 quarantined (3 DUPLICATE, 5 UNKNOWN_METER, 1 NEGATIVE_ENERGY, 1 REGISTER_DECREASE_NO_ROLLOVER, 1 UNPARSEABLE file), 18 gap runs / 153 missing slots — all match `_manifest.json`; 0 Wh/kWh mismatches; re-run + backfill fingerprint identical | Approved: duplicates → quarantine DUPLICATE (auditable), removed retail template stubs (`validate_sale`, `parse_amount`). Caught: our own fingerprint check falsely passed (shell `$$`→PID, empty hashes) → rewrote as script; `parse_event` called directly with no schema_version wrongly → BAD_SCHEMA → now infers like bronze. Decision: a quarantined slot counts as a gap (no billable reading) |
| | gold | SCD2 snapshot | <<...>> | corrected <<valid_to logic>> |
| | sre drill | hypotheses from trimmed logs | <<...>> | tested <<which>>, added regression test |

## Prompts we reused (keep the good ones)
- "Plan first, don't write code yet: ..."
- "Write a failing test for <rule>, then implement until it passes."
- "Here are the 6 relevant log lines and the metric. Give 3 ranked hypotheses."
