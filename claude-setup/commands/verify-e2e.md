Run the whole pipeline end to end and report: `make up` healthy, `make seed`, `make run`
for one day, dashboard shows gold/mart data + the DQ scorecard, and `make test` green.
Then re-run `make run` for the same day and confirm gold totals are IDENTICAL (idempotency).
Report any step that fails; do not fix silently.
