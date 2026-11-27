"""Deterministic synthetic smart-meter telemetry for GridPulse (Team 44, Track B).

Pure stdlib (no Faker) so re-runs are byte-identical: a fixed --seed plus
sort_keys JSON output means the same flags always produce the same files.

Emits, under --out (default data/landing/):
  <YYYY-MM-DD>/<feeder>.json   per-day, per-feeder JSON array of reading events
  _master/dim_meter.csv        meter master for ref.dim_meter
  _manifest.json               generation params + the exact location of every
                               planted defect, so the tester can assert precisely

Reading event fields (see CLAUDE.md §3/§4/§7):
  v1: meter_id, ts, energy, status, register, unit, schema_version
  v2: + voltage, firmware
`energy` is the interval (15-min) consumption and `register` is the cumulative
meter reading, both in the meter's NATIVE unit (Wh or kWh per `unit`). Silver
converts to kWh using `unit` and must never double-convert.

Planted defects (all recorded in _manifest.json):
  duplicate reading, out-of-order file, missing intervals (gap), register
  rollover (flagged), register decrease (unflagged -> quarantine), unknown
  meter_id, negative energy, unparseable file, re-delivered (byte-identical)
  file, plus tamper/spike/outage seeds for the anomaly layer.

Usage:
  python scripts/generate_synthetic_data.py            # small dry-run set
  python scripts/generate_synthetic_data.py --full     # 5000 meters x 90 days
  python scripts/generate_synthetic_data.py --meters 200 --days 7 --seed 44
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# --- fixed vocab ----------------------------------------------------------
FIRMWARES = ["fw-2.1.0", "fw-2.3.1", "fw-3.0.0"]
MODELS = ["GP-100", "GP-200", "GP-200X"]
REGISTER_MAX = {"Wh": 1_000_000.0, "kWh": 100_000.0}  # dial wraps here -> rollover
UNKNOWN_METER_ID = "M99999"  # sentinel: deliberately absent from dim_meter


@dataclass(frozen=True)
class Meter:
    meter_id: str
    feeder_id: str
    zone_id: str
    unit: str  # "Wh" | "kWh"
    schema_version: int  # 1 | 2
    base_load_kwh: float  # typical 15-min consumption, kWh
    firmware: str  # "" for v1
    model: str
    install_date: str
    register0_kwh: float  # starting cumulative register, in kWh


# --- topology -------------------------------------------------------------
def build_topology(
    n_meters: int, n_feeders: int, n_zones: int, seed: int
) -> list[Meter]:
    """Deterministically assign meters -> feeders -> zones with stable attrs."""
    meters: list[Meter] = []
    for i in range(1, n_meters + 1):
        feeder_idx = ((i - 1) % n_feeders) + 1
        zone_idx = ((feeder_idx - 1) % n_zones) + 1
        rnd = random.Random(f"{seed}:meter:{i}")
        schema_version = 2 if rnd.random() < 0.60 else 1
        unit = "kWh" if rnd.random() < 0.15 else "Wh"
        base_load = round(rnd.uniform(0.05, 0.50), 4)  # kWh / 15 min
        firmware = rnd.choice(FIRMWARES) if schema_version == 2 else ""
        model = rnd.choice(MODELS)
        install_days = rnd.randint(200, 1500)
        install_date = (
            date(2024, 1, 1) - timedelta(days=0) + timedelta(days=-install_days)
        ).isoformat()
        register0 = round(rnd.uniform(1_000.0, 50_000.0), 4)  # kWh
        meters.append(
            Meter(
                meter_id=f"M{i:05d}",
                feeder_id=f"F{feeder_idx:02d}",
                zone_id=f"Z{zone_idx:02d}",
                unit=unit,
                schema_version=schema_version,
                base_load_kwh=base_load,
                firmware=firmware,
                model=model,
                install_date=install_date,
                register0_kwh=register0,
            )
        )
    return meters


def diurnal_factor(hour: int) -> float:
    """Smooth daily load curve: low overnight, morning + evening peaks."""
    # two gaussian-ish humps at ~08:00 and ~19:00 on a base.
    morning = math.exp(-((hour - 8) ** 2) / 8.0)
    evening = math.exp(-((hour - 19) ** 2) / 6.0)
    return 0.4 + 0.8 * morning + 1.1 * evening


# --- defect plan ----------------------------------------------------------
def plan_defects(meters: list[Meter], dates: list[date], feeders: list[str]) -> dict:
    """Pick concrete, always-present targets and describe them for the manifest.

    Targets use the first few meters (always exist, even in --small) and clamp
    day indices to what was generated.
    """

    def day(i: int) -> date:
        return dates[min(i, len(dates) - 1)]

    by_id = {m.meter_id: m for m in meters}

    # tamper needs ~48h; use two consecutive days when available.
    if len(dates) >= 3:
        tamper_days = [dates[1], dates[2]]
    elif len(dates) == 2:
        tamper_days = [dates[0], dates[1]]
    else:
        tamper_days = [dates[0]]

    outage_feeder = feeders[-1]  # last feeder, whole-feeder window drop

    plan = {
        "duplicate": {"meter_id": "M00001", "date": day(0), "intervals": [40, 41, 42]},
        "out_of_order": {"feeder_id": feeders[0], "date": day(0)},
        "gap": {"meter_id": "M00003", "date": day(1), "drop_from": 30, "drop_to": 45},
        "rollover": {"meter_id": "M00004", "date": day(1), "interval": 50},
        "register_decrease": {"meter_id": "M00005", "date": day(1), "interval": 55},
        "unknown_meter": {"feeder_id": feeders[0], "date": day(0), "count": 5},
        "negative_energy": {"meter_id": "M00006", "date": day(0), "interval": 60},
        "tamper": {"meter_id": "M00007", "dates": list(tamper_days)},
        "spike": {"meter_id": "M00008", "date": day(2), "interval": 70, "factor": 25.0},
        "outage": {"feeder_id": outage_feeder, "date": day(2), "from": 32, "to": 40},
        "redelivered": {"feeder_id": feeders[min(1, len(feeders) - 1)], "date": day(0)},
        "unparseable": {"date": day(0)},
    }
    # keep only defects whose meter actually exists in this run
    for key in (
        "duplicate",
        "gap",
        "rollover",
        "register_decrease",
        "negative_energy",
        "tamper",
        "spike",
    ):
        mid = plan[key].get("meter_id")
        if mid and mid not in by_id:
            plan[key] = None
    return plan


# --- generation -----------------------------------------------------------
def _emit_unit(
    interval_kwh: float, register_kwh: float, unit: str
) -> tuple[float, float]:
    if unit == "Wh":
        return round(interval_kwh * 1000.0, 1), round(register_kwh * 1000.0, 1)
    return round(interval_kwh, 4), round(register_kwh, 4)


def _event(
    meter: Meter,
    ts: datetime,
    energy: float,
    register: float,
    status: str,
    rng: random.Random,
    rollover: bool = False,
) -> dict:
    ev = {
        "meter_id": meter.meter_id,
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "energy": energy,
        "status": status,
        "register": register,
        "unit": meter.unit,
        "schema_version": meter.schema_version,
    }
    if rollover:
        ev["rollover"] = True
    if meter.schema_version == 2:
        ev["voltage"] = round(230.0 + rng.uniform(-6.0, 6.0), 1)
        ev["firmware"] = meter.firmware
    return ev


def generate(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    dates = [start + timedelta(days=d) for d in range(args.days)]
    intervals_per_day = (24 * 60) // args.interval_min

    meters = build_topology(args.meters, args.feeders, args.zones, args.seed)
    feeders = sorted({m.feeder_id for m in meters})
    meters_by_feeder: dict[str, list[Meter]] = {f: [] for f in feeders}
    for m in meters:
        meters_by_feeder[m.feeder_id].append(m)

    plan = plan_defects(meters, dates, feeders)

    # fresh output tree (idempotent: identical bytes each run)
    if out.exists():
        for child in out.iterdir():
            if child.name == ".gitkeep":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)

    # per-meter running register (kWh) + per-meter rng for noise
    register_kwh = {m.meter_id: m.register0_kwh for m in meters}
    meter_rng = {
        m.meter_id: random.Random(f"{args.seed}:noise:{m.meter_id}") for m in meters
    }

    counts = {"events": 0, "files": 0}

    for d in dates:
        day_dir = out / d.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)

        for feeder in feeders:
            events: list[dict] = []
            outage = plan.get("outage") or {}
            outage_here = outage.get("feeder_id") == feeder and outage.get("date") == d

            for meter in meters_by_feeder[feeder]:
                rng = meter_rng[meter.meter_id]
                for idx in range(intervals_per_day):
                    minutes = idx * args.interval_min
                    ts = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(
                        minutes=minutes
                    )

                    # --- whole-feeder OUTAGE window: drop every meter's reading
                    if outage_here and outage["from"] <= idx <= outage["to"]:
                        continue

                    # --- individual MISSING intervals -> gap
                    g = plan.get("gap")
                    if (
                        g
                        and meter.meter_id == g["meter_id"]
                        and d == g["date"]
                        and g["drop_from"] <= idx <= g["drop_to"]
                    ):
                        continue

                    hour = ts.hour
                    noise = 1.0 + rng.uniform(-0.15, 0.15)
                    interval_kwh = max(
                        0.0, meter.base_load_kwh * diurnal_factor(hour) * noise
                    )
                    status = "OK"
                    rollover = False

                    # --- TAMPER seed: flat zero across the tamper window
                    t = plan.get("tamper")
                    if t and meter.meter_id == t["meter_id"] and d in t["dates"]:
                        interval_kwh = 0.0

                    # --- SPIKE seed: one huge interval
                    s = plan.get("spike")
                    if (
                        s
                        and meter.meter_id == s["meter_id"]
                        and d == s["date"]
                        and idx == s["interval"]
                    ):
                        interval_kwh *= s["factor"]

                    register_kwh[meter.meter_id] += interval_kwh

                    # --- REGISTER ROLLOVER (flagged): wrap the dial past its max
                    r = plan.get("rollover")
                    if (
                        r
                        and meter.meter_id == r["meter_id"]
                        and d == r["date"]
                        and idx == r["interval"]
                    ):
                        cap_kwh = REGISTER_MAX[meter.unit] / (
                            1000.0 if meter.unit == "Wh" else 1.0
                        )
                        register_kwh[meter.meter_id] = register_kwh[meter.meter_id] % (
                            cap_kwh * 0.001 + 1.0
                        )
                        rollover = True

                    energy, register = _emit_unit(
                        interval_kwh, register_kwh[meter.meter_id], meter.unit
                    )

                    # --- REGISTER DECREASE without rollover flag -> quarantine
                    rd = plan.get("register_decrease")
                    if (
                        rd
                        and meter.meter_id == rd["meter_id"]
                        and d == rd["date"]
                        and idx == rd["interval"]
                    ):
                        register = round(
                            register * 0.5, 4 if meter.unit == "kWh" else 1
                        )

                    # --- NEGATIVE energy -> quarantine
                    ne = plan.get("negative_energy")
                    if (
                        ne
                        and meter.meter_id == ne["meter_id"]
                        and d == ne["date"]
                        and idx == ne["interval"]
                    ):
                        energy = -abs(energy) if energy else -1.0

                    events.append(
                        _event(meter, ts, energy, register, status, rng, rollover)
                    )

            # --- DUPLICATE readings in this file
            dup = plan.get("duplicate")
            if dup and dup["date"] == d:
                dups = [
                    e
                    for e in events
                    if e["meter_id"] == dup["meter_id"]
                    and _interval_index(e["ts"], d, args.interval_min)
                    in dup["intervals"]
                ]
                events.extend(json.loads(json.dumps(e)) for e in dups)

            # --- UNKNOWN meter_id events injected into this file
            um = plan.get("unknown_meter")
            if um and um["feeder_id"] == feeder and um["date"] == d:
                urng = random.Random(f"{args.seed}:unknown")
                for k in range(um["count"]):
                    ts = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(
                        minutes=k * args.interval_min
                    )
                    events.append(
                        {
                            "meter_id": UNKNOWN_METER_ID,
                            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "energy": round(urng.uniform(0.1, 0.4) * 1000.0, 1),
                            "status": "OK",
                            "register": round(urng.uniform(1000, 5000), 1),
                            "unit": "Wh",
                            "schema_version": 1,
                        }
                    )

            # order events (ts, meter_id) EXCEPT the designated out-of-order file
            ooo = plan.get("out_of_order")
            if ooo and ooo["feeder_id"] == feeder and ooo["date"] == d:
                random.Random(f"{args.seed}:ooo").shuffle(events)
            else:
                events.sort(key=lambda e: (e["ts"], e["meter_id"]))

            path = day_dir / f"{feeder}.json"
            _write_json(path, events)
            counts["events"] += len(events)
            counts["files"] += 1

            # --- RE-DELIVERED: byte-identical copy of this file
            rdl = plan.get("redelivered")
            if rdl and rdl["feeder_id"] == feeder and rdl["date"] == d:
                shutil.copyfile(path, day_dir / f"{feeder}.redelivered.json")
                counts["files"] += 1

    # --- UNPARSEABLE file (invalid JSON on purpose)
    up = plan.get("unparseable")
    if up:
        bad = out / up["date"].isoformat() / "_corrupt.json"
        bad.write_text(
            '{"meter_id": "M00001", "ts": "2025-09-01T00:00:00Z", "energy": 12.3,',
            encoding="utf-8",
        )
        counts["files"] += 1

    _write_master(out, meters)
    manifest = _build_manifest(args, meters, dates, feeders, plan, counts)
    _write_json(out / "_manifest.json", manifest)
    return manifest


def _interval_index(ts: str, d: date, interval_min: int) -> int:
    t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    return (t.hour * 60 + t.minute) // interval_min


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def _write_master(out: Path, meters: list[Meter]) -> None:
    master_dir = out / "_master"
    master_dir.mkdir(parents=True, exist_ok=True)
    with (master_dir / "dim_meter.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "meter_id",
                "feeder_id",
                "zone_id",
                "unit",
                "schema_version",
                "model",
                "firmware",
                "install_date",
            ]
        )
        for m in meters:
            w.writerow(
                [
                    m.meter_id,
                    m.feeder_id,
                    m.zone_id,
                    m.unit,
                    m.schema_version,
                    m.model,
                    m.firmware,
                    m.install_date,
                ]
            )


def _build_manifest(args, meters, dates, feeders, plan, counts) -> dict:
    def jsonable(v):
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, list):
            return [jsonable(x) for x in v]
        return v

    defects = []
    reason_for = {
        "register_decrease": "REGISTER_DECREASE_NO_ROLLOVER",
        "unknown_meter": "UNKNOWN_METER",
        "negative_energy": "NEGATIVE_ENERGY",
        "unparseable": "UNPARSEABLE",
    }
    for name, spec in plan.items():
        if not spec:
            continue
        entry = {"type": name, **{k: jsonable(v) for k, v in spec.items()}}
        if name in reason_for:
            entry["expected_reason_code"] = reason_for[name]
        defects.append(entry)

    units = {"Wh": 0, "kWh": 0}
    schemas = {1: 0, 2: 0}
    for m in meters:
        units[m.unit] += 1
        schemas[m.schema_version] += 1

    return {
        "generator": "gridpulse-synthetic/1.0",
        "params": {
            "meters": args.meters,
            "feeders": args.feeders,
            "zones": args.zones,
            "days": args.days,
            "start_date": args.start_date,
            "interval_min": args.interval_min,
            "seed": args.seed,
        },
        "dates": [d.isoformat() for d in dates],
        "feeders": feeders,
        "counts": {
            **counts,
            "meters": len(meters),
            "units": units,
            "schema_versions": {str(k): v for k, v in schemas.items()},
        },
        "defects": defects,
        "unknown_meter_sentinel": UNKNOWN_METER_ID,
    }


# --- cli ------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generate deterministic GridPulse smart-meter telemetry."
    )
    ap.add_argument("--meters", type=int, default=60)
    ap.add_argument("--feeders", type=int, default=4)
    ap.add_argument("--zones", type=int, default=2)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--start-date", default="2025-09-01")
    ap.add_argument("--interval-min", type=int, default=15)
    ap.add_argument("--seed", type=int, default=44)
    ap.add_argument("--out", default="data/landing")
    ap.add_argument(
        "--full",
        action="store_true",
        help="target scale: 5000 meters, 20 feeders, 6 zones, 90 days",
    )
    return ap


def main() -> None:
    args = build_parser().parse_args()
    if args.full:
        args.meters, args.feeders, args.zones, args.days = 5000, 20, 6, 90
    manifest = generate(args)
    c = manifest["counts"]
    print(f"[gridpulse] wrote {c['events']} events in {c['files']} files -> {args.out}")
    print(
        f"[gridpulse] meters={c['meters']} units={c['units']} schema={c['schema_versions']}"
    )
    print(
        f"[gridpulse] planted {len(manifest['defects'])} defect types; see {args.out}/_manifest.json"
    )


if __name__ == "__main__":
    main()
