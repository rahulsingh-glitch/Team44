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

## Layer 3 — Silver normalisation (73 test functions / 86 cases incl. parametrised, all green)
- `tests/test_silver_normalise.py` (52 fns) — pure rule tests on crafted rows, no DB.
- `tests/test_silver_integration.py` (21 fns) — generator → bronze → silver through the real
  `src.pipeline` in a **throwaway DB `gridpulse_test_silver`** (team `lakehouse` untouched);
  expectations read from `_manifest.json`. Skips if the warehouse is unreachable.
Feature code is not modified.

### Unit rule / time rule (CLAUDE.md §4)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V1 | Wh ÷ 1000 | `test_wh_energy_is_converted_to_kwh_by_dividing_by_1000` | 1500 Wh → 1.5 kWh |
| V2 | kWh never double-converted | `test_kwh_meter_energy_is_not_double_converted` | 1.5 → 1.5 |
| V3 | Register uses same unit rule | `test_register_is_converted_with_the_same_unit_rule_as_energy` | Wh register ÷ 1000 |
| V4 | No `unit` → master unit | `test_missing_unit_field_falls_back_to_meter_master_unit` | converted per master |
| V5 | Event unit ≠ master = ambiguous | `test_unit_disagreeing_with_meter_master_is_quarantined_bad_schema` | BAD_SCHEMA |
| V6 | Unknown unit | `test_unknown_unit_is_quarantined_bad_schema` / `test_to_kwh_rejects_unknown_unit` | BAD_SCHEMA / ValueError |
| V7 | Exact decimal maths | `test_decimal_conversion_is_exact_no_float_drift` | 0.1 Wh → 0.0001 |
| V8 | Offset ts → UTC | `test_offset_timestamp_is_normalised_to_utc` | +05:30 → 00:00Z |
| V9 | reading_date = UTC date | `test_reading_date_is_the_utc_date_not_the_local_date` | local 09-02 → 09-01 |
| V10 | Naive ts = UTC | `test_naive_timestamp_is_treated_as_utc` | tz=UTC |
| V11 | 15-min boundary | `test_timestamp_not_on_15_min_boundary_is_quarantined_bad_schema` | BAD_SCHEMA |
| V12 | Bad ts | `test_unparseable_timestamp_is_quarantined_unparseable` | UNPARSEABLE |
| V13 | No ts → source_date | `test_quarantine_without_parsed_ts_uses_fallback_source_date` | fallback date |
| V14 | E2E unit rule | `test_wh_converted_to_kwh_and_kwh_meters_not_double_converted_end_to_end` | 0 mismatches Wh + kWh |
| V15 | source_unit = master | `test_source_unit_matches_meter_master_unit` | 0 mismatches |
| V16 | E2E UTC/aligned | `test_all_reading_ts_are_utc_15min_aligned_and_match_reading_date` | 0 violations |

### Shape / schema v1-v2 (ADR-0003)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V17 | Required field missing | `test_missing_required_field_is_quarantined_bad_schema` (×4) | BAD_SCHEMA |
| V18 | Required field null | `test_null_required_field_is_quarantined_bad_schema` (×4) | BAD_SCHEMA |
| V19 | Non-object event | `test_non_object_event_is_quarantined_bad_schema` | BAD_SCHEMA, raw kept |
| V20 | meter_id not string | `test_non_string_meter_id_is_quarantined_bad_schema` | BAD_SCHEMA |
| V21 | Non-numeric energy (abc/bool/NaN/Inf/list) | `test_non_numeric_energy_is_quarantined_unparseable` (×5) | UNPARSEABLE |
| V22 | Non-numeric voltage | `test_non_numeric_voltage_is_quarantined_unparseable` | UNPARSEABLE |
| V23 | Numeric string accepted | `test_numeric_string_energy_is_accepted` | "1500" → 1.5 |
| V24 | schema_version ∉ {1,2} | `test_schema_version_other_than_1_or_2_is_quarantined_bad_schema` (×4) | BAD_SCHEMA |
| V25 | Version inferred | `test_missing_schema_version_is_inferred_from_v2_fields` | 1 / 2 |
| V26 | Bronze version used | `test_bronze_recorded_schema_version_is_used_when_payload_lacks_it` | 2 |
| V27 | v1 nulls | `test_v1_event_has_null_voltage_and_firmware` | null/null |
| V28 | v2 keeps fields | `test_v2_event_keeps_voltage_and_firmware` | populated |
| V29 | Feeder/zone enrichment | `test_reading_is_enriched_with_feeder_and_zone_from_master` | F01/Z01 |
| V30 | E2E v1/v2 columns | `test_v1_rows_have_null_voltage_firmware_and_v2_rows_have_them` | v1 0/0, v2 full |

### Quarantine / DQ (CLAUDE.md §5)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V31 | Unknown meter | `test_unknown_meter_is_quarantined_unknown_meter` | UNKNOWN_METER |
| V32 | Negative energy | `test_negative_energy_is_quarantined_negative_energy` | NEGATIVE_ENERGY |
| V33 | Zero is valid | `test_zero_energy_is_accepted_not_quarantined` | accepted |
| V34 | Lineage kept | `test_quarantine_preserves_raw_row_and_bronze_lineage` | raw + event id + file |
| V35 | Manifest defects → codes | `test_every_planted_quarantine_defect_lands_with_expected_reason_code` | expected ⊆ got ⊆ expected+DUPLICATE |
| V36 | E2E unknown meter | `test_unknown_meter_rows_are_quarantined_and_absent_from_silver` | 5 quarantined, 0 in silver |
| V37 | E2E negative | `test_negative_energy_is_quarantined_and_no_negative_kwh_in_silver` | 1 row; 0 negatives |
| V38 | E2E unparseable file | `test_unparseable_file_is_quarantined_unparseable` | `_corrupt.json` row |
| V39 | Closed reason list enforced | `test_quarantine_rejects_reason_code_outside_closed_list` | CheckViolation |

### Dedupe / order / register (CLAUDE.md §7)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V40 | Dedupe first copy | `test_duplicate_reading_is_deduped_first_copy_kept` | lowest event id kept, other DUPLICATE |
| V41 | Triplicate | `test_triplicate_reading_yields_one_row_and_two_duplicate_quarantines` | 1 + 2 |
| V42 | Key includes meter | `test_same_ts_different_meters_are_not_duplicates` | both kept |
| V43 | Bad copy doesn't block good | `test_invalid_first_copy_does_not_block_valid_second_copy` | valid kept, NEGATIVE_ENERGY only |
| V44 | E2E dedupe | `test_duplicate_reading_is_deduped_and_quarantined_duplicate` | 3 DUPLICATE, 96 rows |
| V45 | E2E PK unique | `test_silver_has_one_row_per_meter_and_reading_ts` | 0 dupes, is_duplicate never true |
| V46 | Order | `test_out_of_order_events_are_ordered_by_meter_and_reading_ts` | sorted, complete |
| V47 | Arrival order ≠ decrease | `test_out_of_order_arrival_does_not_cause_false_register_decrease` | 0 quarantined |
| V48 | E2E out-of-order file | `test_out_of_order_file_yields_complete_ordered_readings` | 96 − quarantined per meter |
| V49 | Re-delivery not double counted | `test_redelivered_file_is_not_double_counted_in_silver` | meters×96 − quarantined |
| V50 | Decrease w/o flag | `test_register_decrease_without_rollover_is_quarantined` | REGISTER_DECREASE_NO_ROLLOVER |
| V51 | Rollover kept | `test_register_decrease_with_rollover_flag_is_kept` | kept, rollover=true |
| V52 | Equal register OK | `test_equal_register_is_not_a_decrease` | kept |
| V53 | Compare to last accepted | `test_register_after_quarantined_decrease_is_compared_to_last_accepted` | both decreases quarantined |
| V54 | Cross-day continuity | `test_register_decrease_across_days_uses_previous_day_register` | quarantined |
| V55 | Per-meter check | `test_register_check_is_per_meter_not_global` | no false positive |
| V56 | E2E decrease | `test_register_decrease_without_rollover_is_quarantined_at_planted_interval` | M00005 @ planted ts |
| V57 | E2E rollover | `test_flagged_rollover_is_kept_in_silver_with_rollover_true` | M00004 kept |

### Gaps — recorded, never filled (CLAUDE.md §4)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V58 | Gap recorded, not filled | `test_missing_interval_recorded_as_gap_not_filled` | 1 gap ×16, no synthetic rows |
| V59 | Complete day | `test_complete_day_has_no_gaps` | none |
| V60 | Separate runs | `test_separate_missing_runs_become_separate_gaps` | 2 gaps |
| V61 | Day edges | `test_leading_and_trailing_gaps_are_recorded` | 00:00 and 23:45 gaps |
| V62 | Silent meter | `test_silent_meter_gets_one_full_day_gap` | 1 gap ×96 |
| V63 | Quarantined slot = gap | `test_quarantined_slot_counts_as_gap` | 1 gap |
| V64 | Unknown meter no gaps | `test_unknown_meter_produces_no_gap_rows` | none |
| V65 | E2E planted gap | `test_missing_interval_recorded_as_gap_not_filled_end_to_end` | M00003 16 slots, 0 rows in window |
| V66 | E2E outage | `test_feeder_outage_window_is_recorded_as_gaps_for_every_meter_on_feeder` | every meter, 9 slots |
| V67 | Accounting | `test_readings_plus_missing_slots_equal_96_per_meter_per_day` | all = 96 |

### Day scoping / idempotency (CLAUDE.md §4 IDEMPOTENT)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| V68 | Other UTC day excluded | `test_events_for_another_utc_day_are_excluded_from_this_day` | not in this day |
| V69 | Deterministic | `test_normalise_day_is_deterministic_regardless_of_input_order` | identical output |
| V70 | Re-run | `test_rerun_is_idempotent` | silver fingerprint unchanged |
| V71 | Backfill range | `test_backfill_of_date_range_is_idempotent` | fingerprint unchanged |
| V72 | Late re-delivered copy | `test_rerun_after_redelivered_copy_adds_no_silver_rows` | fingerprint unchanged |

## Layer 4 — Consumption (`tests/test_consumption.py`, 25 cases, all green)
Two throwaway DBs (`lakehouse` untouched; skipped if the warehouse is down). Feature code not modified.
- **A. Seed** — generator → real `pipeline.run` → gold; asserts reconciliation + planted defects.
- **B. Crafted** — rows written straight into `ref.dim_meter` + `silver.meter_readings`, then
  `build_gold_date`; covers what the 3-day seed cannot (full month, silent / not-yet-installed
  meter, 90 % boundary, UTC hour bucket, replace-not-append).

### Reconciliation (kWh carried exactly, no double count)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| G1 | Hourly = silver | `test_hourly_kwh_equals_silver_kwh_per_meter_per_day` | kWh + interval count match per meter-day |
| G2 | Daily = Σ hourly | `test_daily_kwh_equals_sum_of_hourly_per_meter` | no mismatch |
| G3 | Monthly = Σ daily | `test_monthly_billing_kwh_equals_sum_of_daily_per_meter` | no mismatch; 60 billing rows |
| G4 | Roll-ups = meter level | `test_feeder_and_zone_views_equal_meter_level_totals` | 4 views equal meter-grain sums |
| G5 | One row per meter-day | `test_every_installed_meter_has_one_daily_row_per_processed_day` | 60 × 3 days |

### Defects in gold (gaps marked, never filled — CLAUDE.md §4)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| G6 | Gap day incomplete, not filled | `test_gap_day_is_marked_incomplete_and_missing_intervals_are_not_filled` | M00003 80/96, 83.33 %, is_complete=false, kWh = silver |
| G7 | Gap hours absent | `test_gap_hours_have_no_hourly_rows_and_edge_hours_keep_partial_counts` | no 08–10 rows; 07 & 11 = 2 intervals |
| G8 | Outage hours absent | `test_feeder_outage_hours_have_no_hourly_rows_for_any_meter_on_feeder` | F04 no 08/09 rows; 10:00 hour = 3 intervals × 15 meters |
| G9 | Duplicates not double counted | `test_duplicate_readings_are_not_double_counted_in_gold` | M00001 96/96; max 4 intervals/hour |
| G10 | Quarantined slot not billed | `test_quarantined_reading_carries_no_billable_kwh` | M00005, M00006 = 95; no negative kWh |
| G11 | Unknown meter excluded | `test_unknown_meter_is_absent_from_every_gold_table` | 0 rows in 3 tables |
| G12 | No double unit conversion | `test_kwh_reporting_meters_are_not_double_converted_in_gold` | Wh/kWh meter mean ratio within 0.1–10 (1000× ⇒ fail) |
| G13 | UTC hour buckets | `test_hour_buckets_are_utc_hour_aligned_and_on_their_reading_date` | 0 misaligned |
| G14 | Partial month | `test_partial_month_is_open_month_with_expected_based_on_processed_days` | all OPEN_MONTH, 3/30 days, expected 288 |

### Billing status (crafted full month, Sept 2030)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| G15 | > 90 % full month ⇒ BILLABLE | `test_full_month_above_90_pct_is_billable_with_exact_kwh` | 720.000000 kWh, 100 %, 30/30 days |
| G16 | ≤ 90 % ⇒ LOW_COMPLETENESS, no estimate | `test_full_month_at_or_below_90_pct_is_low_completeness_not_estimated` | 600.000000 kWh (measured only), 83.33 % |
| G17 | Open until all days processed | `test_month_is_open_until_every_day_is_processed` | after 29/30 days both OPEN_MONTH |

### Edge cases (crafted)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| G18 | Outage ≠ 0 kWh | `test_meter_with_no_readings_has_daily_row_with_null_energy_not_zero` | energy NULL, 0 %, no hourly rows |
| G19 | Not yet installed | `test_meter_installed_after_date_gets_no_daily_row` | 0 rows |
| G20 | Complete is strictly > 90 % | `test_completeness_flag_requires_strictly_more_than_90_pct` | 86 = 89.58 % false; 87 = 90.63 % true |
| G21 | 23:45 UTC bucket | `test_reading_at_2345_utc_lands_in_hour_23_of_the_same_utc_date` | hour 23:00Z, same date |

### Idempotency (T2 — the most-tested Track B failure)
| ID | Rule | Test name | Expected |
|---|---|---|---|
| G22 | Re-run one date | `test_rerun_of_one_date_is_idempotent_for_gold` | gold md5 unchanged |
| G23 | Backfill range | `test_backfill_of_date_range_is_idempotent_for_gold` | md5 + row counts unchanged |
| G24 | Re-run replaces, not appends | `test_rerun_after_silver_change_replaces_rows_instead_of_appending` | new kWh (87), same row counts |
| G25 | Rebuild twice | `test_rebuilding_a_day_twice_gives_identical_gold` | md5 unchanged |

## Deliberately failing test (CI proof)
Keep one test that fails on a known-broken input to prove CI turns red.
`tests/test_deliberately_failing.py` is `@pytest.mark.skip`; unskip ⇒ suite goes red.
