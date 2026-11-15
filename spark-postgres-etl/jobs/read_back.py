"""Read the Parquet table back: how much does a one-day query read, and how long does it take?

The query averages temperature by status. It reads two columns: Parquet never reads the other eight.

    docker compose run --rm spark read_back.py
"""

import statistics

from common import TABLE_PATH, Timer, spark_session
from pyspark.sql import functions as F

RUNS = 5
DAY = "2026-10-15"


def scan_metrics(df):
    """Files and date partitions read by the Parquet scan(s) of the last execution, from Spark's own metrics."""
    found = {"files": 0, "partitions": 0, "bytes": 0}

    def walk(node):
        name = node.getClass().getSimpleName()
        if name == "AdaptiveSparkPlanExec":
            return walk(node.executedPlan())
        if name.endswith("QueryStageExec"):
            return walk(node.plan())
        if name == "FileSourceScanExec":
            metrics = node.metrics()
            for key, out in (("numFiles", "files"), ("numPartitions", "partitions"), ("filesSize", "bytes")):
                if metrics.contains(key):
                    found[out] += metrics.apply(key).value()
        children = node.children()
        for i in range(children.size()):
            walk(children.apply(i))

    walk(df._jdf.queryExecution().executedPlan())
    return found


def main():
    spark = spark_session("read-back")
    day_start = F.lit(f"{DAY} 00:00:00").cast("timestamp")
    day_end = day_start + F.expr("INTERVAL 1 DAY")
    filters = {
        "whole table": None,
        "event_date = day (partition column)": F.col("event_date") == DAY,
        "event_time within day (not partitioned)": (F.col("event_time") >= day_start) & (F.col("event_time") < day_end),
    }

    def build(condition):
        # A new DataFrame every time: re-collecting the same one reuses its shuffle output and skips the scan
        events = spark.read.parquet(str(TABLE_PATH))
        if condition is not None:
            events = events.where(condition)
        return events.groupBy("status").agg(F.count("*").alias("count"), F.avg("temperature_c").alias("avg_temperature"))

    print(f"\nEvents and average temperature by status; median of {RUNS} runs after a warm-up. Day: {DAY}")
    print("  files, dates, MB: what the scan selected after partition pruning")
    print(f"  {'filter':<42} {'rows':>10} {'files':>6} {'dates':>6} {'MB':>7} {'time':>8}")
    for label, condition in filters.items():
        build(condition).collect()  # warm-up
        times = []
        for _ in range(RUNS):
            query = build(condition)
            with Timer() as t:
                rows = query.collect()
            times.append(t.seconds * 1000)
        m = scan_metrics(query)
        total = sum(r["count"] for r in rows)
        print(f"  {label:<42} {total:>10,} {m['files']:>6} {m['partitions']:>6} {m['bytes'] / 1e6:>7.1f} {statistics.median(times):>6.0f} ms")
    spark.stop()


if __name__ == "__main__":
    main()
