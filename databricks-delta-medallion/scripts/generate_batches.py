"""Generate three batches of raw shipment-tracking events as newline-delimited JSON, with a fixed seed.

data/raw/batch=1/events.json   50,000 clean events (October 1-10, 2026)
data/raw/batch=2/events.json   50,000 new events, plus 2,000 redelivered copies of batch-1 events,
                               1,000 late corrections of batch-1 events (same event_id, newer updated_at),
                               and 200 malformed records
data/raw/batch=3/events.json   50,000 new events with a new field, carrier (schema evolution)
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 7
ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
STATUSES = ["in_transit"] * 7 + ["delivered", "delivered", "delayed", "exception"]
COMPANIES = [f"company_{n:02d}" for n in range(1, 13)]
CARRIERS = ["road", "rail", "air"]
iso = lambda t: t.isoformat(timespec="seconds").replace("+00:00", "Z")  # noqa: E731


def event(rng, event_id, day_offset):
    t = START + timedelta(days=day_offset, seconds=rng.randrange(86400))
    return {"event_id": event_id, "package_id": f"pkg_{rng.randrange(1, 8001):05d}",
            "company": rng.choice(COMPANIES), "status": rng.choice(STATUSES),
            "event_time": iso(t), "updated_at": iso(t),
            "temperature_c": round(rng.uniform(-5, 40), 1), "weight_kg": round(rng.uniform(0.5, 40), 2)}


def write(batch, records):
    path = ROOT / f"batch={batch}" / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    return path


def main():
    rng = random.Random(SEED)
    batch1 = [event(rng, f"evt_{i:07d}", rng.randrange(0, 10)) for i in range(50_000)]
    write(1, batch1)

    batch2 = [event(rng, f"evt_{i:07d}", rng.randrange(10, 20)) for i in range(50_000, 100_000)]
    duplicates = rng.sample(batch1, 2_000)  # redelivered, unchanged
    corrections = []
    for original in rng.sample(batch1, 1_000):  # same event, corrected later
        fixed = dict(original, status="delivered",
                     updated_at=iso(datetime.fromisoformat(original["updated_at"].replace("Z", "+00:00")) + timedelta(hours=6)))
        corrections.append(fixed)
    malformed = []
    for n in range(200):
        bad = event(rng, f"bad_{n:04d}", 12)
        kind = n % 4
        if kind == 0:
            bad["event_time"] = "not-a-date"
        elif kind == 1:
            del bad["event_id"]
        elif kind == 2:
            bad["weight_kg"] = -1.0
        else:
            bad = '{"event_id": "bad_' + f"{n:04d}" + '", "status": "in_transit"'  # truncated JSON line
        malformed.append(bad)
    mixed = batch2 + duplicates + corrections + malformed
    rng.shuffle(mixed)
    write(2, mixed)

    batch3 = [dict(event(rng, f"evt_{i:07d}", rng.randrange(20, 30)), carrier=rng.choice(CARRIERS)) for i in range(100_000, 150_000)]
    write(3, batch3)
    for b in (1, 2, 3):
        p = ROOT / f"batch={b}" / "events.json"
        print(f"batch {b}: {sum(1 for _ in p.open()):,} lines, {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
