"""Compare the raw and rolled-up tables: rows, storage, accuracy, and query time.

Run after load.py. Query times are wall-clock from this script (including HTTP), with Druid's caches off,
after one warm-up run; the median of 10 runs is reported.
"""

import statistics
import time

from druid import sql

NO_CACHE = {"useCache": False, "populateCache": False, "useResultLevelCache": False, "populateResultLevelCache": False}
RUNS = 10

# The same three questions, asked of each table
QUERIES = {
    "views by page": (
        'SELECT page, COUNT(*) AS views FROM clicks_raw GROUP BY 1 ORDER BY 2 DESC',
        'SELECT page, SUM(views) AS views FROM clicks_hourly GROUP BY 1 ORDER BY 2 DESC',
    ),
    "views per day by device": (
        "SELECT TIME_FLOOR(__time, 'P1D') AS bucket, device, COUNT(*) AS views FROM clicks_raw GROUP BY 1, 2",
        "SELECT TIME_FLOOR(__time, 'P1D') AS bucket, device, SUM(views) AS views FROM clicks_hourly GROUP BY 1, 2",
    ),
    "unique users by country": (
        "SELECT country, APPROX_COUNT_DISTINCT_DS_HLL(user_id) AS users FROM clicks_raw GROUP BY 1",
        "SELECT country, APPROX_COUNT_DISTINCT_DS_HLL(users_sketch) AS users FROM clicks_hourly GROUP BY 1",
    ),
}


def timed(query):
    sql(query, NO_CACHE)  # warm-up
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        sql(query, NO_CACHE)
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times)


def main():
    raw_rows = sql("SELECT COUNT(*) AS n FROM clicks_raw")[0]["n"]
    hourly_rows = sql("SELECT COUNT(*) AS n FROM clicks_hourly")[0]["n"]
    views = sql("SELECT SUM(views) AS n FROM clicks_hourly")[0]["n"]
    sizes = {r["datasource"]: r["bytes"] for r in sql(
        "SELECT datasource, SUM(\"size\") AS bytes FROM sys.segments WHERE is_active = 1 GROUP BY 1")}
    segments = {r["datasource"]: r["n"] for r in sql(
        "SELECT datasource, COUNT(*) AS n FROM sys.segments WHERE is_active = 1 GROUP BY 1")}

    print("Storage")
    print(f"  {'table':<14} {'rows':>10} {'segments':>9} {'size':>9}")
    for table, rows in (("clicks_raw", raw_rows), ("clicks_hourly", hourly_rows)):
        print(f"  {table:<14} {rows:>10,} {segments[table]:>9} {sizes[table] / 1_000_000:>7.1f} MB")
    print(f"  rollup: {raw_rows / hourly_rows:.1f}x fewer rows, {sizes['clicks_raw'] / sizes['clicks_hourly']:.1f}x less storage")
    print(f"  SUM(views) in clicks_hourly = {views:,} (raw rows: {raw_rows:,}) -> {'no clicks lost' if views == raw_rows else 'MISMATCH'}")

    exact = sql("SELECT COUNT(DISTINCT user_id) AS n FROM clicks_raw", {"useApproximateCountDistinct": False})[0]["n"]
    from_raw = sql("SELECT APPROX_COUNT_DISTINCT_DS_HLL(user_id) AS n FROM clicks_raw")[0]["n"]
    from_sketch = sql("SELECT APPROX_COUNT_DISTINCT_DS_HLL(users_sketch) AS n FROM clicks_hourly")[0]["n"]
    print("\nUnique users in the month")
    print(f"  exact, from clicks_raw:          {exact:,}")
    print(f"  HLL estimate, from clicks_raw:    {round(from_raw):,} ({(from_raw - exact) / exact:+.2%})")
    print(f"  HLL estimate, from clicks_hourly: {round(from_sketch):,} ({(from_sketch - exact) / exact:+.2%})")

    print(f"\nQuery time, median of {RUNS} runs, caches off")
    print(f"  {'query':<26} {'raw':>8} {'hourly':>8}")
    for name, (raw_query, hourly_query) in QUERIES.items():
        print(f"  {name:<26} {timed(raw_query):>6.0f} ms {timed(hourly_query):>6.0f} ms")


if __name__ == "__main__":
    main()
