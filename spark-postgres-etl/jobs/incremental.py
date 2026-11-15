"""Incremental load: only rows added since the last run (id above the saved watermark).

    docker compose run --rm spark incremental.py
"""

from common import SOURCE, TABLE_PATH, Timer, id_range, jdbc, lake_stats, read_state, spark_session, write_state
from pyspark.sql import functions as F


def main():
    state = read_state()
    if state is None:
        raise SystemExit("No watermark yet. Run the full load first: docker compose run --rm spark extract.py")
    watermark = state["watermark_id"]

    spark = spark_session("incremental")
    lo, hi, new_rows = id_range(spark, f"id > {watermark}")
    if new_rows == 0:
        print(f"\nIncremental load: no rows above watermark id {watermark:,}. Nothing to do.")
        spark.stop()
        return

    before_files, _, before_dates = lake_stats(TABLE_PATH)
    with Timer() as t:
        # Bounded on both sides: rows inserted during this run wait for the next one
        df = jdbc(spark, f"SELECT * FROM {SOURCE} WHERE id BETWEEN {lo} AND {hi}",
                  partitionColumn="id", lowerBound=lo, upperBound=hi + 1, numPartitions=4)
        (df.withColumn("event_date", F.to_date("event_time"))
           .write.mode("append").partitionBy("event_date").parquet(str(TABLE_PATH)))
    write_state(hi, new_rows)

    total = spark.read.parquet(str(TABLE_PATH)).count()
    pg_total = id_range(spark)[2]
    files, _, dates = lake_stats(TABLE_PATH)
    print(f"\nIncremental load from watermark id {watermark:,}")
    print(f"  read: {new_rows:,} new rows (ids {lo:,}-{hi:,}) in {t.seconds:.1f} s")
    print(f"  Parquet: {files - before_files} new files, {dates - before_dates} new date partition(s)")
    print(f"  totals: {total:,} rows in Parquet, {pg_total:,} in PostgreSQL ({'match' if total == pg_total else 'MISMATCH'})")
    print(f"  watermark: id {watermark:,} -> {hi:,}")
    spark.stop()


if __name__ == "__main__":
    main()
