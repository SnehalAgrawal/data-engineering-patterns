"""Generate a month of synthetic clickstream events as newline-delimited JSON.

Seeded and with a fixed date range, so every run writes the same file:
data/generated/clicks.json (about 550,000 events, October 1-30, 2026).
Prints the exact totals, which compare.py later checks Druid against.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = 30
EVENTS_PER_WEEKDAY = 20_000  # weekends get 70% of this
USERS = 40_000

# (value, weight): uneven on purpose, like real traffic
PAGES = [("/home", 30), ("/pricing", 18), ("/products", 15), ("/docs", 14), ("/blog", 10), ("/about", 6), ("/careers", 4), ("/contact", 3)]
COUNTRIES = [("IN", 28), ("US", 24), ("GB", 9), ("DE", 8), ("CA", 6), ("SG", 6), ("AU", 5), ("FR", 5), ("BR", 5), ("JP", 4)]
DEVICES = [("desktop", 55), ("mobile", 40), ("tablet", 5)]
REFERRERS = [("google", 36), ("direct", 32), ("linkedin", 11), ("newsletter", 10), ("github", 6), ("x", 5)]
# Share of a day's traffic per UTC hour: quiet at night, busiest mid-afternoon
HOURLY = [2, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 6, 6, 6, 7, 7, 6, 5, 5, 4, 4, 4, 3, 3]


def weighted(pairs):
    values = [value for value, _ in pairs]
    cumulative, total = [], 0
    for _, weight in pairs:
        total += weight
        cumulative.append(total)
    return values, cumulative


def main():
    rng = random.Random(SEED)
    pages, countries, devices, referrers = (weighted(p) for p in (PAGES, COUNTRIES, DEVICES, REFERRERS))
    # A few users are very active and most are occasional (weight ~ 1 / rank)
    user_ids = [f"u{n:05d}" for n in range(USERS)]
    user_cumulative, total = [], 0.0
    for rank in range(1, USERS + 1):
        total += 1 / rank
        user_cumulative.append(total)

    out = Path(__file__).resolve().parent.parent / "data" / "generated" / "clicks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    events, seen_users = 0, set()
    with out.open("w") as f:
        for day in range(DAYS):
            date = START + timedelta(days=day)
            per_day = EVENTS_PER_WEEKDAY * (0.7 if date.weekday() >= 5 else 1.0)
            for hour, share in enumerate(HOURLY):
                count = int(per_day * share / sum(HOURLY) * rng.uniform(0.9, 1.1))
                for _ in range(count):
                    ts = date + timedelta(hours=hour, seconds=rng.uniform(0, 3600))
                    user = rng.choices(user_ids, cum_weights=user_cumulative)[0]
                    seen_users.add(user)
                    f.write(json.dumps({
                        "timestamp": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        "user_id": user,
                        "page": rng.choices(pages[0], cum_weights=pages[1])[0],
                        "country": rng.choices(countries[0], cum_weights=countries[1])[0],
                        "device": rng.choices(devices[0], cum_weights=devices[1])[0],
                        "referrer": rng.choices(referrers[0], cum_weights=referrers[1])[0],
                    }) + "\n")
                    events += 1
    size_mb = out.stat().st_size / 1_000_000
    print(f"Wrote {events:,} events from {len(seen_users):,} distinct users to {out.relative_to(out.parents[2])} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
