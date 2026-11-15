"""Full load: PostgreSQL -> Parquet, partitioned by date.

    docker compose run --rm spark extract.py --partitions 1    # Spark's default JDBC read: one connection
    docker compose run --rm spark extract.py --partitions 8    # eight connections, each reading an id range
"""

import argparse

from common import SOURCE, TABLE_PATH, Timer, id_range, jdbc, lake_stats, spark_session, write_state
from pyspark.sql import functions as F


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--partitions", type=int, default=8)
    args = parser.parse_args()

    spark = spark_session(f"extract-{args.partitions}")
    lo, hi, source_rows = id_range(spark)
    # Freeze the range now, so rows inserted while the job runs are left for the next incremental load
    query = f"SELECT * FROM {SOURCE} WHERE id BETWEEN {lo} AND {hi}"

    with Timer() as t:
        if args.partitions == 1:
            df = jdbc(spark, query)  # no partitioning options: one task, one connection
        else:
            # Spark splits [lowerBound, upperBound) into equal id ranges, one query and one task each
            df = jdbc(spark, query, partitionColumn="id", lowerBound=lo, upperBound=hi + 1, numPartitions=args.partitions)
        (df.withColumn("event_date", F.to_date("event_time"))
           .write.mode("overwrite").partitionBy("event_date").parquet(str(TABLE_PATH)))

    written = spark.read.parquet(str(TABLE_PATH)).count()
    files, size, dates = lake_stats(TABLE_PATH)
    pg_bytes = jdbc(spark, f"SELECT pg_total_relation_size('{SOURCE}') AS b").first().b
    write_state(hi, written)

    print(f"\nFull load with {args.partitions} JDBC partition(s) ({df.rdd.getNumPartitions()} read tasks)")
    print(f"  rows: {source_rows:,} in PostgreSQL -> {written:,} in Parquet ({'match' if written == source_rows else 'MISMATCH'})")
    print(f"  time: {t.seconds:.1f} s for read + transform + write")
    print(f"  Parquet: {files} files in {dates} date partitions, {size / 1e6:.1f} MB "
          f"(PostgreSQL table with index: {pg_bytes / 1e6:.1f} MB)")
    print(f"  watermark: id {hi:,}")
    spark.stop()


if __name__ == "__main__":
    main()
