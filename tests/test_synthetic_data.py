"""Tests for the synthetic-data layer (scripts/generate_synthetic_data.py).

Test names state the rule and the result. These tests do NOT change the feature;
they generate into a temp dir and assert against the emitted files + manifest.
Rules come from CLAUDE.md §3/§4/§7 and the pipeline-builder layer spec.
"""

import hashlib
import itertools
import json
from pathlib import Path

import generate_synthetic_data as gen
import pytest

SEED = 44


def _args(out: Path, **over):
    argv = ["--out", str(out)]
    for k, v in over.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return gen.build_parser().parse_args(argv)


def _gen(out: Path, **over):
    over.setdefault("seed", SEED)
    manifest = gen.generate(_args(out, **over))
    return manifest, out


def _all_events(root: Path):
    for p in sorted(root.glob("*/*.json")):
        if p.name == "_corrupt.json":
            continue
        for e in json.loads(p.read_text()):
            yield p, e


def _dir_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing")
    manifest, root = _gen(out, meters=60, feeders=4, zones=2, days=3)
    master = {}
    for row in (root / "_master" / "dim_meter.csv").read_text().splitlines()[1:]:
        cols = row.split(",")
        master[cols[0]] = {
            "meter_id": cols[0],
            "feeder_id": cols[1],
            "zone_id": cols[2],
            "unit": cols[3],
        }
    return {"manifest": manifest, "root": root, "master": master}


# --- determinism ----------------------------------------------------------
def test_generation_is_deterministic_same_seed_same_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _gen(a, meters=40, feeders=4, zones=2, days=2, seed=7)
    _gen(b, meters=40, feeders=4, zones=2, days=2, seed=7)
    assert _dir_digest(a) == _dir_digest(b)


def test_different_seed_produces_different_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _gen(a, meters=40, feeders=4, zones=2, days=2, seed=7)
    _gen(b, meters=40, feeders=4, zones=2, days=2, seed=8)
    assert _dir_digest(a) != _dir_digest(b)


# --- schema v1 / v2 -------------------------------------------------------
def test_v1_events_have_no_voltage_or_firmware(dataset):
    v1 = [e for _, e in _all_events(dataset["root"]) if e.get("schema_version") == 1]
    assert v1, "expected some v1 events"
    assert all("voltage" not in e and "firmware" not in e for e in v1)


def test_v2_events_have_voltage_and_firmware(dataset):
    v2 = [
        e
        for _, e in _all_events(dataset["root"])
        if e.get("schema_version") == 2 and e["meter_id"] != gen.UNKNOWN_METER_ID
    ]
    assert v2, "expected some v2 events"
    assert all("voltage" in e and "firmware" in e for e in v2)


# --- units (CLAUDE.md §4: Wh vs kWh, never double-convert) ----------------
def test_both_wh_and_kwh_meters_are_present(dataset):
    units = {m["unit"] for m in dataset["master"].values()}
    assert units == {"Wh", "kWh"}


def test_wh_meter_energy_is_about_1000x_kwh_meter(dataset):
    master = dataset["master"]
    by_meter = {}
    for _, e in _all_events(dataset["root"]):
        if e["energy"] > 0:
            by_meter.setdefault(e["meter_id"], e["energy"])
    wh = next(
        by_meter[m] for m, r in master.items() if r["unit"] == "Wh" and m in by_meter
    )
    kwh = next(
        by_meter[m] for m, r in master.items() if r["unit"] == "kWh" and m in by_meter
    )
    assert wh > 10 and kwh < 5, (wh, kwh)  # Wh scale vs kWh scale, clearly distinct


# --- planted defects ------------------------------------------------------
def test_duplicate_reading_is_planted(dataset):
    counts = {}
    for p, e in _all_events(dataset["root"]):
        if e["meter_id"] == "M00001" and "2025-09-01" in p.parent.name:
            counts[e["ts"]] = counts.get(e["ts"], 0) + 1
    assert max(counts.values()) > 1


def test_out_of_order_file_is_not_sorted_by_ts(dataset):
    spec = next(
        d for d in dataset["manifest"]["defects"] if d["type"] == "out_of_order"
    )
    events = json.loads(
        (dataset["root"] / spec["date"] / f"{spec['feeder_id']}.json").read_text()
    )
    ts = [e["ts"] for e in events]
    assert ts != sorted(ts)


def test_missing_interval_is_recorded_as_gap_not_filled(dataset):
    spec = next(d for d in dataset["manifest"]["defects"] if d["type"] == "gap")
    events = [
        e
        for e in json.loads((dataset["root"] / spec["date"] / "F03.json").read_text())
        if e["meter_id"] == spec["meter_id"]
    ]
    mins = {int(e["ts"][11:13]) * 60 + int(e["ts"][14:16]) for e in events}
    dropped = [
        i for i in range(spec["drop_from"], spec["drop_to"] + 1) if i * 15 not in mins
    ]
    assert len(dropped) == (spec["drop_to"] - spec["drop_from"] + 1)


def test_register_rollover_is_flagged(dataset):
    flagged = [e for _, e in _all_events(dataset["root"]) if e.get("rollover")]
    assert flagged and all(e["meter_id"] == "M00004" for e in flagged)


def test_register_decrease_without_rollover_is_present(dataset):
    spec = next(
        d for d in dataset["manifest"]["defects"] if d["type"] == "register_decrease"
    )
    events = sorted(
        (
            e
            for e in json.loads(
                (dataset["root"] / spec["date"] / "F01.json").read_text()
            )
            if e["meter_id"] == spec["meter_id"]
        ),
        key=lambda e: e["ts"],
    )
    decreases = [
        (a["register"], b["register"])
        for a, b in itertools.pairwise(events)
        if b["register"] < a["register"] and not b.get("rollover")
    ]
    assert (
        decreases
    ), "expected an unflagged register decrease (silver should quarantine it)"
    assert spec["expected_reason_code"] == "REGISTER_DECREASE_NO_ROLLOVER"


def test_unknown_meter_id_is_absent_from_master(dataset):
    master = dataset["master"]
    unknown = [
        e for _, e in _all_events(dataset["root"]) if e["meter_id"] not in master
    ]
    assert unknown and all(e["meter_id"] == gen.UNKNOWN_METER_ID for e in unknown)


def test_negative_energy_is_planted(dataset):
    neg = [e for _, e in _all_events(dataset["root"]) if e["energy"] < 0]
    assert neg


def test_unparseable_file_is_invalid_json(dataset):
    bad = dataset["root"] / "2025-09-01" / "_corrupt.json"
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_text())


def test_redelivered_file_is_byte_identical(dataset):
    d = dataset["root"] / "2025-09-01"
    assert (d / "F02.json").read_bytes() == (d / "F02.redelivered.json").read_bytes()


def test_tamper_meter_is_zero_across_window(dataset):
    spec = next(d for d in dataset["manifest"]["defects"] if d["type"] == "tamper")
    window_dates = set(spec["dates"])
    vals = [
        e["energy"]
        for p, e in _all_events(dataset["root"])
        if e["meter_id"] == spec["meter_id"] and p.parent.name in window_dates
    ]
    assert vals and all(v == 0 for v in vals)


def test_spike_interval_exceeds_meter_baseline(dataset):
    spec = next(d for d in dataset["manifest"]["defects"] if d["type"] == "spike")
    vals = sorted(
        e["energy"]
        for _, e in _all_events(dataset["root"])
        if e["meter_id"] == spec["meter_id"] and e["energy"] > 0
    )
    median = vals[len(vals) // 2]
    assert max(vals) > 10 * median


def test_outage_feeder_window_has_no_readings(dataset):
    spec = next(d for d in dataset["manifest"]["defects"] if d["type"] == "outage")
    events = json.loads(
        (dataset["root"] / spec["date"] / f"{spec['feeder_id']}.json").read_text()
    )
    window = {i * 15 for i in range(spec["from"], spec["to"] + 1)}
    present = {int(e["ts"][11:13]) * 60 + int(e["ts"][14:16]) for e in events}
    assert not (
        window & present
    ), "outage window should have zero readings for the feeder"


# --- manifest + master contracts -----------------------------------------
def test_manifest_lists_defects_with_expected_reason_codes(dataset):
    defects = {d["type"]: d for d in dataset["manifest"]["defects"]}
    for t in (
        "duplicate",
        "out_of_order",
        "gap",
        "rollover",
        "register_decrease",
        "unknown_meter",
        "negative_energy",
        "tamper",
        "spike",
        "outage",
        "redelivered",
        "unparseable",
    ):
        assert t in defects, f"missing defect in manifest: {t}"
    assert (
        defects["register_decrease"]["expected_reason_code"]
        == "REGISTER_DECREASE_NO_ROLLOVER"
    )
    assert defects["unknown_meter"]["expected_reason_code"] == "UNKNOWN_METER"
    assert defects["negative_energy"]["expected_reason_code"] == "NEGATIVE_ENERGY"


def test_every_real_meter_is_in_master(dataset):
    master = set(dataset["master"])
    seen = {e["meter_id"] for _, e in _all_events(dataset["root"])}
    seen.discard(gen.UNKNOWN_METER_ID)
    assert seen <= master


def test_all_timestamps_are_utc_and_15min_aligned(dataset):
    for _, e in _all_events(dataset["root"]):
        assert e["ts"].endswith("Z")
        minute = int(e["ts"][14:16])
        assert minute % 15 == 0


# --- CLI scale controls ---------------------------------------------------
def test_make_seed_default_is_small():
    args = gen.build_parser().parse_args([])
    assert (
        args.meters == 60 and args.feeders == 4 and args.zones == 2 and args.days == 3
    )


def test_full_flag_sets_target_scale(monkeypatch):
    captured = {}

    def fake_generate(args):
        captured["args"] = args
        return {
            "defects": [],
            "counts": {
                "events": 0,
                "files": 0,
                "meters": 0,
                "units": {},
                "schema_versions": {},
            },
        }

    monkeypatch.setattr(gen, "generate", fake_generate)
    monkeypatch.setattr("sys.argv", ["prog", "--full"])
    gen.main()
    a = captured["args"]
    assert (a.meters, a.feeders, a.zones, a.days) == (5000, 20, 6, 90)
