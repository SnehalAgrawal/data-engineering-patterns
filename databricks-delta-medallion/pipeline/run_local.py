"""Run the medallion pipeline on local Spark with Delta Lake (inside the Docker image).

    docker compose run --rm spark pipeline/run_local.py --batch 1
    docker compose run --rm spark pipeline/run_local.py --batch 2 --features
    docker compose run --rm spark pipeline/run_local.py --reset

Tables live in the database `medallion`: files in data/warehouse, catalog in data/metastore_db (both on your machine).
"""

import argparse
import shutil
from pathlib import Path

from pyspark.sql import SparkSession

from pipeline.medallion import Config, run

WAREHOUSE = "/data/warehouse"
METASTORE = "/data/metastore_db"


def spark_session() -> SparkSession:
    return (SparkSession.builder.appName("delta-medallion")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.sql.warehouse.dir", WAREHOUSE)
            # A persistent catalog, so tables survive between runs (embedded Derby, stored next to the data)
            .config("spark.sql.catalogImplementation", "hive")
            .config("spark.hadoop.javax.jdo.option.ConnectionURL", f"jdbc:derby:;databaseName={METASTORE};create=true")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", "8")
            .config("spark.ui.enabled", "false")
            .getOrCreate())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, help="ingest and process this batch (1, 2, or 3)")
    parser.add_argument("--features", action="store_true", help="show history, time travel, schema enforcement, OPTIMIZE")
    parser.add_argument("--reset", action="store_true", help="delete all tables and start again")
    args = parser.parse_args()

    if args.reset:
        shutil.rmtree(WAREHOUSE, ignore_errors=True)
        shutil.rmtree(METASTORE, ignore_errors=True)
        Path("/data/derby.log").unlink(missing_ok=True)
        print("reset: warehouse deleted")
        return

    spark = spark_session()
    spark.sparkContext.setLogLevel("ERROR")
    if not spark.catalog.databaseExists("medallion"):
        spark.sql("CREATE DATABASE medallion")
    cfg = Config(prefix="medallion", raw_root="/data/raw")
    run(spark, cfg, args.batch, args.features)
    spark.stop()


if __name__ == "__main__":
    main()
