"""End-to-end check (used by CI): batches 1, 2, 2 again, and 3, then the Delta features, in a scratch database.

    docker compose run --rm spark pipeline/verify.py

Every expected number follows from scripts/generate_batches.py (seed 7). Exits non-zero on the first mismatch.
"""

from pipeline.medallion import Config, run
from pipeline.run_local import spark_session

DB = "medallion_verify"


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {actual}" + ("" if ok else f" (expected {expected})"), flush=True)
    if not ok:
        raise SystemExit(1)


def main():
    spark = spark_session()
    spark.sparkContext.setLogLevel("OFF")  # the schema-enforcement step fails on purpose; keep the output readable
    spark.sql(f"DROP DATABASE IF EXISTS {DB} CASCADE")
    spark.sql(f"CREATE DATABASE {DB}")
    cfg = Config(prefix=DB, raw_root="/data/raw")

    b1 = run(spark, cfg, 1, False)
    check("batch 1: rows into silver", b1["silver"]["inserted"], 50_000)

    b2 = run(spark, cfg, 2, False)
    check("batch 2: raw lines into bronze", b2["bronze"]["rows_written"], 53_200)
    check("batch 2: rejects by reason", b2["silver"]["rejected"],
          {"unparseable JSON": 50, "missing event_id": 50, "invalid event_time": 50, "non-positive weight_kg": 50})
    check("batch 2: new events inserted", b2["silver"]["inserted"], 50_000)
    check("batch 2: late corrections applied", b2["silver"]["updated"], 1_000)
    check("batch 2: silver rows", b2["silver"]["silver_rows"], 100_000)

    again = run(spark, cfg, 2, False)
    check("batch 2 again: bronze skipped", again["bronze"]["skipped"], True)
    check("batch 2 again: inserted, updated", (again["silver"]["inserted"], again["silver"]["updated"]), (0, 0))
    check("batch 2 again: rejects not duplicated", spark.table(cfg.table("silver_rejects")).count(), 200)

    b3 = run(spark, cfg, 3, False)
    check("batch 3: silver rows", b3["silver"]["silver_rows"], 150_000)
    check("batch 3: carrier column added", "carrier" in spark.table(cfg.table("silver_events")).columns, True)
    check("gold: events add up to silver", b3["gold"]["events"], 150_000)

    delta = run(spark, cfg, None, True)["delta"]
    check("time travel: rows changed since version 0", delta["rows_changed_since_first_version"], 1_000)
    enforcement = delta["schema_enforcement"]
    check("enforcement: unknown column", enforcement["unknown column (discount_code)"].startswith("rejected"), True)
    check("enforcement: 'heavy' into a double", enforcement["weight_kg as the string 'heavy'"].startswith("rejected"), True)
    check("enforcement: '12.5' into a double", enforcement["weight_kg as the string '12.5'"], "accepted")
    check("OPTIMIZE: one file afterwards", delta["optimize_files"][1], 1)

    spark.sql(f"DROP DATABASE {DB} CASCADE")
    print("all checks passed")


if __name__ == "__main__":
    main()
