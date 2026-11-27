# Claude Usage Log — Team 44

> Scored under **Claude usage (15)**. Judges want prompt quality, plan-first,
> CLAUDE.md, and **corrections made** — not volume. Log the notable moments, not
> every keystroke. A correction you caught scores higher than flawless output.

| Time | Phase | Prompt intent (short) | What Claude produced | Our correction / decision |
|---|---|---|---|---|
| 09:30 | setup | stand up full stack (PG18 + Airflow 3.3 + Superset), prove fresh-clone start | docker-compose, Makefile, schema init, CI, pinned admin/admin | Caught 2 defects live: stale `superset-home` volume poisoned by an old SECRET_KEY → wiped + pinned project name `gridpulse`; scheduler healthcheck probed disabled :8974 server → switched to `airflow jobs check` |
| 10:05 | synthetic data | deterministic generator: meters/feeders/zones, v1/v2, Wh+kWh, planted defects + manifest | `scripts/generate_synthetic_data.py` (stdlib-only, seeded); dim_meter.csv + _manifest.json; 11/11 defect checks pass | Added cumulative `register` to every event (needed for rollover/decrease rules, beyond §7's v1 list); chose stdlib over Faker for byte-identical re-runs; `make seed` defaults small, `--full`=5000×90d |
| | architecture | asked for locking/idempotency options | <<...>> | chose <<...>> because <<...>> |
| | silver | plan for dedup + quarantine | <<...>> | fixed <<edge case>> |
| | gold | SCD2 snapshot | <<...>> | corrected <<valid_to logic>> |
| | sre drill | hypotheses from trimmed logs | <<...>> | tested <<which>>, added regression test |

## Prompts we reused (keep the good ones)
- "Plan first, don't write code yet: ..."
- "Write a failing test for <rule>, then implement until it passes."
- "Here are the 6 relevant log lines and the metric. Give 3 ranked hypotheses."
