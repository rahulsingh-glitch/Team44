# Test Plan — Team 44 · Track B

> Scored under **Engineering & data quality (15)**. Every must-have has a test;
> one command runs them all (`make test`).

## Scope
In: <<the must-have slice>>. Out: <<stretch>>.

## Entry criteria
Stack up, synthetic data seeded, schemas created.

## Exit criteria
All must-have tests green; the deliberately-failing test proves the suite catches failure.

## Risks
Concurrency/idempotency; SCD2 correctness; freshness edge cases; tz/currency parsing.

## Test cases (one row per must-have — names state rule and result)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| T1 | Re-delivered file skipped | `test_redelivered_file_is_skipped` | row counts unchanged on re-run |
| T2 | No double-count on re-run | `test_rerun_is_idempotent` | identical gold totals |
| T3 | SCD2 keeps history | `test_product_rename_keeps_history` | 2 rows, one `is_current` |
| T4 | Bad FK quarantined | `test_unknown_product_is_quarantined` | row in quarantine w/ reason |
| T5 | Freshness breach alerts | `test_late_file_raises_freshness_failure` | alert fired |
| T6 | Negative qty unless return | `test_negative_qty_quarantined_unless_return` | quarantined/flagged |

## Deliberately failing test (CI proof)
Keep one test that fails on a known-broken input to prove CI turns red.
