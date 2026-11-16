# Databricks notebook source
"""Bronze -> silver -> gold with Delta Lake. Runs unchanged on local Spark and on Databricks serverless.

Only Spark SQL, DataFrame, and Delta APIs that Databricks serverless supports are used: no RDDs, no
cluster-level Spark settings. Tables are named <prefix>.<table>, where prefix is a database locally and
<catalog>.<schema> on Databricks.

The first line marks this file as a notebook for Databricks, which then loads it with %run (see run_databricks.py).
To Python it is a comment, so run_local.py and verify.py import it as an ordinary module.
"""

import json
import re
import time
from dataclasses import dataclass

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

STATUSES = ["in_transit", "delivered", "delayed", "exception"]


@dataclass
class Config:
    prefix: str  # "medallion" locally, "<catalog>.<schema>" on Databricks
    raw_root: str  # folder holding batch=<n>/ subfolders of newline-delimited JSON

    def table(self, name: str) -> str:
        return f"{self.prefix}.{name}"


def table_exists(spark: SparkSession, name: str) -> bool:
    return spark.catalog.tableExists(name)


def last_operation_metrics(spark: SparkSession, name: str) -> dict:
    row = spark.sql(f"DESCRIBE HISTORY {name} LIMIT 1").collect()[0]
    return {"version": row["version"], "operation": row["operation"], **(row["operationMetrics"] or {})}


# ---------------------------------------------------------------- bronze: raw, as received, append-only


def ingest_bronze(spark: SparkSession, cfg: Config, batch: int) -> dict:
    """Append one batch of raw JSON to bronze, unless its file was already ingested (idempotent ingestion)."""
    bronze = cfg.table("bronze_events")
    path = f"{cfg.raw_root}/batch={batch}"
    if table_exists(spark, bronze):
        seen = spark.sql(f"SELECT count(*) AS n FROM {bronze} WHERE _batch = {batch}").collect()[0]["n"]
        if seen:
            return {"batch": batch, "skipped": True, "rows_already_in_bronze": seen}

    # Schema inferred from the data: unparseable lines land in _corrupt_record, new fields add columns
    raw = (spark.read.option("mode", "PERMISSIVE").option("columnNameOfCorruptRecord", "_corrupt_record").json(path)
           .withColumn("_source_file", F.col("_metadata.file_path"))
           .withColumn("_batch", F.lit(batch))
           .withColumn("_ingested_at", F.current_timestamp()))
    (raw.write.format("delta").mode("append")
        .option("mergeSchema", "true")  # bronze accepts new columns as they arrive
        .saveAsTable(bronze))
    metrics = last_operation_metrics(spark, bronze)
    return {"batch": batch, "skipped": False, "rows_written": int(metrics.get("numOutputRows", 0)),
            "bronze_version": metrics["version"], "columns": len(spark.table(bronze).columns)}


# ---------------------------------------------------------------- silver: validated, typed, deduplicated


def validate(bronze_batch: DataFrame) -> DataFrame:
    """Add a reject_reason column (null when the row is valid) and typed timestamps."""
    cols = set(bronze_batch.columns)
    corrupt = F.col("_corrupt_record").isNotNull() if "_corrupt_record" in cols else F.lit(False)
    event_time = F.try_to_timestamp(F.col("event_time"))
    updated_at = F.try_to_timestamp(F.col("updated_at"))
    reason = (F.when(corrupt, "unparseable JSON")
              .when(F.col("event_id").isNull(), "missing event_id")
              .when(event_time.isNull(), "invalid event_time")
              .when(F.col("weight_kg") <= 0, "non-positive weight_kg")
              .when(~F.col("status").isin(STATUSES), "unknown status"))
    return (bronze_batch.withColumn("reject_reason", reason)
            .withColumn("event_time", event_time).withColumn("updated_at", updated_at))


def build_silver(spark: SparkSession, cfg: Config, batch: int) -> dict:
    """Validate one bronze batch, quarantine bad rows, and MERGE the rest into silver (upsert by event_id)."""
    bronze, silver, rejects = cfg.table("bronze_events"), cfg.table("silver_events"), cfg.table("silver_rejects")
    checked = validate(spark.table(bronze).where(F.col("_batch") == batch))

    bad = checked.where(F.col("reject_reason").isNotNull())
    # Keep the record as received: the raw line if it did not parse, otherwise its fields as JSON
    fields = F.to_json(F.struct(*[c for c in bad.columns if not c.startswith("_") and c != "reject_reason"]))
    raw_line = F.col("_corrupt_record") if "_corrupt_record" in bad.columns else F.lit(None).cast("string")
    bad_rows = (bad.select(F.col("_batch").alias("batch"), "reject_reason", F.coalesce(raw_line, fields).alias("record"))
                .withColumn("rejected_at", F.current_timestamp()))
    # Rejects are replaced per batch, so re-running a batch does not duplicate them
    if table_exists(spark, rejects):
        spark.sql(f"DELETE FROM {rejects} WHERE batch = {batch}")
    bad_rows.write.format("delta").mode("append").saveAsTable(rejects)
    reject_counts = {r["reject_reason"]: r["n"] for r in bad_rows.groupBy("reject_reason").agg(F.count("*").alias("n")).collect()}

    # Business columns only (no bronze metadata); carrier appears from batch 3 on
    business = ["event_id", "package_id", "company", "status", "event_time", "updated_at", "temperature_c", "weight_kg"]
    if "carrier" in checked.columns:
        business.append("carrier")
    good = checked.where(F.col("reject_reason").isNull()).select(*business)
    # Within a batch, keep the latest version of each event (redeliveries and corrections share an event_id)
    latest = Window.partitionBy("event_id").orderBy(F.col("updated_at").desc())
    deduped = good.withColumn("_rank", F.row_number().over(latest)).where("_rank = 1").drop("_rank")
    valid_rows, unique_rows = good.count(), deduped.count()

    if not table_exists(spark, silver):
        deduped.write.format("delta").saveAsTable(silver)
        merge = {"numTargetRowsInserted": unique_rows, "numTargetRowsUpdated": 0}
    else:
        (DeltaTable.forName(spark, silver).alias("t")
            .merge(deduped.alias("s"), "t.event_id = s.event_id")
            .withSchemaEvolution()  # adds carrier to silver when it first appears
            .whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")  # only newer versions win
            .whenNotMatchedInsertAll()
            .execute())
        merge = last_operation_metrics(spark, silver)
    inserted, updated = int(merge.get("numTargetRowsInserted", 0)), int(merge.get("numTargetRowsUpdated", 0))
    return {"batch": batch, "rejected": reject_counts, "valid_rows": valid_rows,
            "duplicates_in_batch": valid_rows - unique_rows, "merged_rows": unique_rows,
            "inserted": inserted, "updated": updated,
            "matched_not_newer": unique_rows - inserted - updated,  # redeliveries, or a rerun of the same batch
            "silver_rows": spark.table(silver).count(), "silver_columns": len(spark.table(silver).columns)}


# ---------------------------------------------------------------- gold: what the business reads


def build_gold(spark: SparkSession, cfg: Config) -> dict:
    """Daily metrics per company, rebuilt from silver (small enough here to recompute in full each run)."""
    silver, gold = cfg.table("silver_events"), cfg.table("gold_daily_company")
    query = f"""
        SELECT CAST(event_time AS DATE) AS day, company,
               count(*) AS events,
               count_if(status = 'delivered') AS delivered,
               count_if(status IN ('delayed', 'exception')) AS problems,
               round(avg(temperature_c), 1) AS avg_temperature_c
        FROM {silver}
        GROUP BY 1, 2"""
    # Overwrite in one Delta transaction (readers see the old or the new table, never half of it)
    if table_exists(spark, gold):
        spark.sql(f"INSERT OVERWRITE {gold} {query}")
    else:
        spark.sql(f"CREATE TABLE {gold} USING DELTA AS {query}")
    totals = spark.sql(f"SELECT count(*) AS rows, sum(events) AS events, sum(delivered) AS delivered FROM {gold}").collect()[0]
    return {"gold_rows": totals["rows"], "events": totals["events"], "delivered": totals["delivered"]}


# ---------------------------------------------------------------- Delta features, shown on the result


def table_files(spark: SparkSession, name: str) -> int:
    return spark.sql(f"DESCRIBE DETAIL {name}").collect()[0]["numFiles"]


def try_append(df: DataFrame, table: str) -> str:
    try:
        df.write.format("delta").mode("append").saveAsTable(table)
        return "accepted"
    except Exception as e:  # noqa: BLE001 - the exception class differs between local Spark and Databricks
        error_class = re.search(r"\[([A-Z_]+)\]", str(e))
        return f"rejected ({error_class.group(1) if error_class else type(e).__name__})"


def check_schema_enforcement(spark: SparkSession, cfg: Config) -> dict:
    """Three appends to an empty table with silver's schema. Silver itself is never written to."""
    scratch = cfg.table("scratch_enforcement")
    spark.sql(f"DROP TABLE IF EXISTS {scratch}")
    spark.table(cfg.table("silver_events")).limit(0).write.format("delta").saveAsTable(scratch)
    results = {
        "unknown column (discount_code)": try_append(
            spark.createDataFrame([("evt_x", "SAVE10")], "event_id STRING, discount_code STRING"), scratch),
        "weight_kg as the string 'heavy'": try_append(
            spark.createDataFrame([("evt_y", "heavy")], "event_id STRING, weight_kg STRING"), scratch),
        "weight_kg as the string '12.5'": try_append(
            spark.createDataFrame([("evt_z", "12.5")], "event_id STRING, weight_kg STRING"), scratch),
    }
    stored = [(r["event_id"], r["weight_kg"]) for r in spark.table(scratch).collect()]
    spark.sql(f"DROP TABLE {scratch}")
    return {**results, "rows stored": stored}


def show_delta_features(spark: SparkSession, cfg: Config) -> dict:
    silver = cfg.table("silver_events")
    history = spark.sql(f"DESCRIBE HISTORY {silver}").orderBy("version").collect()
    versions = [{"version": h["version"], "operation": h["operation"],
                 "rows": spark.read.option("versionAsOf", h["version"]).table(silver).count()} for h in history]

    # Time travel: how the corrected events looked before batch 2
    first = history[0]["version"]
    before = spark.read.option("versionAsOf", first).table(silver)
    now = spark.table(silver)
    changed = (before.alias("b").join(now.alias("n"), "event_id")
               .where("b.status <> n.status OR b.updated_at <> n.updated_at").count())

    enforcement = check_schema_enforcement(spark, cfg)

    files_before = table_files(spark, silver)
    spark.sql(f"OPTIMIZE {silver}")
    files_after = table_files(spark, silver)
    return {"versions": versions, "rows_changed_since_first_version": changed,
            "schema_enforcement": enforcement, "optimize_files": (files_before, files_after)}


# ---------------------------------------------------------------- one entry for both runtimes


def timed(label: str, fn, *args) -> dict:
    start = time.perf_counter()
    result = fn(*args)
    result["seconds"] = round(time.perf_counter() - start, 1)
    print(f"{label}: {json.dumps(result, default=str)}", flush=True)
    return result


def run(spark: SparkSession, cfg: Config, batch: int | None, features: bool) -> dict:
    results = {}
    if batch:
        results["bronze"] = timed("bronze", ingest_bronze, spark, cfg, batch)
        results["silver"] = timed("silver", build_silver, spark, cfg, batch)
        results["gold"] = timed("gold", build_gold, spark, cfg)
    if features:
        results["delta"] = timed("delta", show_delta_features, spark, cfg)
    return results
