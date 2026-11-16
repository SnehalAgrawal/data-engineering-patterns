# Databricks notebook source
# MAGIC %md
# MAGIC Runs the medallion pipeline as a Databricks serverless job (deployed by `databricks.yml`). Same steps as
# MAGIC `run_local.py`, on Unity Catalog: tables are `<catalog>.<schema>.<table>`, and the raw batches are read from
# MAGIC the volume `/Volumes/<catalog>/<schema>/raw/`. Job parameters arrive as widgets.

# COMMAND ----------

# MAGIC %run ./medallion

# COMMAND ----------

# ruff: noqa: F821 - spark and dbutils are provided by Databricks; Config and run come from %run ./medallion
import json

catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
batch = int(dbutils.widgets.get("batch") or 0)  # 0 means no batch, only the Delta features
features = dbutils.widgets.get("features").lower() == "true"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.raw")
cfg = Config(prefix=f"{catalog}.{schema}", raw_root=f"/Volumes/{catalog}/{schema}/raw")
results = run(spark, cfg, batch or None, features)
dbutils.notebook.exit(json.dumps(results, default=str))  # the job's output, readable with `databricks jobs get-run-output`
