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

## Layer 1 — Synthetic data (`tests/test_synthetic_data.py`, 23 cases, all green)
Generates into a temp dir and asserts against the emitted files + `_manifest.json`.
Feature code is not modified.

| ID | Rule | Test name | Expected |
|---|---|---|---|
| S1 | Same seed ⇒ identical bytes | `test_generation_is_deterministic_same_seed_same_bytes` | re-run digest matches |
| S2 | Seed controls output | `test_different_seed_produces_different_bytes` | different seed differs |
| S3 | v1 has no v2 fields | `test_v1_events_have_no_voltage_or_firmware` | no voltage/firmware |
| S4 | v2 adds voltage+firmware | `test_v2_events_have_voltage_and_firmware` | both present |
| S5 | Both units emitted | `test_both_wh_and_kwh_meters_are_present` | {Wh, kWh} |
| S6 | Unit scale distinct (no double-convert) | `test_wh_meter_energy_is_about_1000x_kwh_meter` | Wh≫kWh magnitude |
| S7 | Duplicates planted | `test_duplicate_reading_is_planted` | repeated (meter,ts) |
| S8 | Out-of-order planted | `test_out_of_order_file_is_not_sorted_by_ts` | file unsorted |
| S9 | Missing interval = gap, not filled | `test_missing_interval_is_recorded_as_gap_not_filled` | intervals absent |
| S10 | Rollover is flagged | `test_register_rollover_is_flagged` | `rollover=true` |
| S11 | Unflagged register decrease present | `test_register_decrease_without_rollover_is_present` | decrease w/o flag |
| S12 | Unknown meter absent from master | `test_unknown_meter_id_is_absent_from_master` | sentinel not in dim_meter |
| S13 | Negative energy planted | `test_negative_energy_is_planted` | energy<0 exists |
| S14 | Unparseable file is invalid JSON | `test_unparseable_file_is_invalid_json` | JSONDecodeError |
| S15 | Re-delivered file byte-identical | `test_redelivered_file_is_byte_identical` | bytes equal |
| S16 | Tamper = zero across window | `test_tamper_meter_is_zero_across_window` | all zero in window |
| S17 | Spike exceeds baseline | `test_spike_interval_exceeds_meter_baseline` | max>10×median |
| S18 | Outage window empty for feeder | `test_outage_feeder_window_has_no_readings` | no readings in window |
| S19 | Manifest lists defects+reasons | `test_manifest_lists_defects_with_expected_reason_codes` | all types + reason codes |
| S20 | Every real meter in master | `test_every_real_meter_is_in_master` | ids ⊆ dim_meter |
| S21 | UTC, 15-min aligned | `test_all_timestamps_are_utc_and_15min_aligned` | `…Z`, minute%15==0 |
| S22 | `make seed` default is small | `test_make_seed_default_is_small` | 60/4/2/3 |
| S23 | `--full` sets target scale | `test_full_flag_sets_target_scale` | 5000/20/6/90 |

## Deliberately failing test (CI proof)
Keep one test that fails on a known-broken input to prove CI turns red.
`tests/test_deliberately_failing.py` is `@pytest.mark.skip`; unskip ⇒ suite goes red.
