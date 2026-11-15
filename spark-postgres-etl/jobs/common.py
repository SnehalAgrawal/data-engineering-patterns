"""Shared helpers for the Spark jobs: session, JDBC reads, lake paths, timing, and the load watermark."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

LAKE = Path(os.environ.get("LAKE", "/lake"))
TABLE_PATH = LAKE / "tracking_events"
STATE_PATH = LAKE / "_state" / "tracking_events.json"
SOURCE = "tracking_events"


def spark_session(name: str) -> SparkSession:
    spark = (
        SparkSession.builder.appName(name)
        .config("spark.sql.session.timeZone", "UTC")  # event_date is the UTC date
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def jdbc(spark: SparkSession, query: str, **options) -> DataFrame:
    """Read the result of a SQL query from PostgreSQL.

    fetchsize: the PostgreSQL driver's default (0) buffers the whole result in memory;
    10,000 rows per round trip keeps memory flat however large the read is.
    """
    reader = (
        spark.read.format("jdbc")
        .option("url", os.environ["PG_URL"])
        .option("user", os.environ["PG_USER"])
        .option("password", os.environ["PG_PASSWORD"])
        .option("driver", "org.postgresql.Driver")
        .option("dbtable", f"({query}) AS src")
        .option("fetchsize", 10_000)
    )
    for key, value in options.items():
        reader = reader.option(key, value)
    return reader.load()


def id_range(spark: SparkSession, where: str = "TRUE"):
    """min(id), max(id), and row count for the rows matching `where` (one small query)."""
    row = jdbc(spark, f"SELECT min(id) AS lo, max(id) AS hi, count(*) AS n FROM {SOURCE} WHERE {where}").first()
    return row.lo, row.hi, row.n


def lake_stats(path: Path):
    files = list(path.rglob("*.parquet"))
    dates = {f.parent.name for f in files}
    return len(files), sum(f.stat().st_size for f in files), len(dates)


def read_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None


def write_state(watermark_id: int, rows: int):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "watermark_id": watermark_id,
        "rows_loaded_last_run": rows,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))


class Timer:
    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.started
