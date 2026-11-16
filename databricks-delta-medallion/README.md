# Databricks Delta Medallion

Bronze, silver, and gold Delta Lake tables built from three batches of shipment-tracking events: one clean, one with duplicates, late corrections, and malformed lines, and one with a new column. The same code runs on open-source Spark with Delta Lake in Docker (no account needed) and as a serverless job on Databricks Free Edition. Both produced the same counts at every step.

## What it shows

- **Bronze: raw data, kept as received.** Each batch is appended once. Loading the same batch again is skipped, so a retried job does not duplicate data. Lines that are not valid JSON are kept in a `_corrupt_record` column instead of failing the load.
- **Silver: validated, deduplicated, upserted.**
  - **Validation:** bad rows are set aside in a `silver_rejects` table with a reason, instead of being dropped silently or failing the job.
  - **Deduplication:** within a batch, only the latest version of each event is kept.
  - **Upsert:** `MERGE` on `event_id`, where only a newer `updated_at` replaces a row. A late correction updates the row; a redelivered copy changes nothing.
  - **Schema evolution:** a new field (`carrier`) is added to the table when it first appears, with `withSchemaEvolution()`.
- **Gold: what the business reads.** Daily totals per company, rebuilt from silver in one transaction.
- **Delta Lake features, checked on the result:** the table's history, time travel to an earlier version, schema enforcement, and `OPTIMIZE`.
- **One codebase, two runtimes.** Only APIs that Databricks serverless supports (no RDDs, no cluster-level Spark settings), with table names as `<prefix>.<table>`, so the same module runs locally and on Databricks.

## How it works

```text
data/raw/batch=N/events.json          (newline-delimited JSON; on Databricks, a Unity Catalog volume)
        │
        ▼
bronze_events        append once per batch; _corrupt_record, _source_file, _batch, _ingested_at
        │
        ▼  validate ──► silver_rejects   (batch, reason, record as received)
        │
        ▼  deduplicate within the batch, then MERGE on event_id (newer updated_at wins; new columns added)
silver_events
        │
        ▼  INSERT OVERWRITE (one transaction)
gold_daily_company   day, company, events, delivered, problems, avg_temperature_c
```

- **The pipeline** ([`pipeline/medallion.py`](pipeline/medallion.py)): the three steps, the Delta feature checks, and `run()`, which both entry points call.
- **Entry points:**
  - **Local:** [`pipeline/run_local.py`](pipeline/run_local.py), with Spark 4.2.0 and Delta Lake 4.4.1 in Docker. Tables are in a local Hive metastore, so they persist between runs.
  - **Databricks:** [`pipeline/run_databricks.py`](pipeline/run_databricks.py), a notebook deployed as a serverless job by [`databricks.yml`](databricks.yml). Tables are in Unity Catalog; the raw files are in a volume.
- **Test data** ([`scripts/generate_batches.py`](scripts/generate_batches.py)), generated with a fixed seed:

  | Batch | Lines | What is in it |
  |---|---|---|
  | 1 | 50,000 | Clean events, October 1–10, 2026 |
  | 2 | 53,200 | 50,000 new events; 2,000 unchanged copies of batch-1 events; 1,000 corrections of batch-1 events (status `delivered`, `updated_at` 6 hours later); 200 malformed lines: 50 each of an invalid date, a missing `event_id`, a negative weight, and truncated JSON |
  | 3 | 50,000 | New events with a new field, `carrier` |

- **The check** ([`pipeline/verify.py`](pipeline/verify.py)): runs batches 1, 2, 2 again, and 3, then the feature checks, in a scratch database, and stops at the first count that differs from what the generator implies. CI runs it on every change.

## Run it locally

Requirements: Docker (about 2 GB of memory for Spark) and Python 3.10 or newer, used only to generate the data.

```bash
python3 scripts/generate_batches.py               # data/raw/batch=1..3, about 35 MB
docker compose build                              # Spark 4.2.0 + Delta Lake 4.4.1, jars checked by SHA-256

docker compose run --rm spark pipeline/run_local.py --batch 1
docker compose run --rm spark pipeline/run_local.py --batch 2
docker compose run --rm spark pipeline/run_local.py --batch 2              # again: nothing changes
docker compose run --rm spark pipeline/run_local.py --batch 3
docker compose run --rm spark pipeline/run_local.py --features

docker compose run --rm spark pipeline/verify.py  # the whole sequence, with expected counts
docker compose run --rm spark pipeline/run_local.py --reset                # delete the tables
```

Each step prints one JSON line. Everything is written under `data/` (git-ignored); delete that folder to remove it all.

## Run it on Databricks

Tested on Databricks Free Edition (serverless only). Requirements: the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install) 0.218 or newer, logged in to your workspace (`databricks auth login --host https://<your-workspace>.cloud.databricks.com`).

```bash
# 1. A schema and a volume for the raw files (catalog "workspace" is Free Edition's default)
databricks schemas create medallion workspace
databricks volumes create workspace medallion raw MANAGED

# 2. Upload the three batches (fs cp does not create folders)
for b in 1 2 3; do
  databricks fs mkdir "dbfs:/Volumes/workspace/medallion/raw/batch=$b"
  databricks fs cp data/raw/batch=$b/events.json "dbfs:/Volumes/workspace/medallion/raw/batch=$b/events.json"
done

# 3. Deploy the job, then run each step
databricks bundle deploy
databricks bundle run medallion --params batch=1
databricks bundle run medallion --params batch=2
databricks bundle run medallion --params batch=2
databricks bundle run medallion --params batch=3
databricks bundle run medallion --params batch=0,features=true
```

Each run's results are the notebook's exit value: `databricks jobs get-run-output <task run id>` shows them under `notebook_output.result`. To remove everything: `databricks bundle destroy`, then delete the schema (`databricks schemas delete workspace.medallion --force`).

## Configuration

| Setting | Default | What it does |
|---|---|---|
| `--batch` (local), `batch` (job parameter) | none locally, `1` on Databricks | Which batch to process; `0` on Databricks means none |
| `--features`, `features` | off | Show history, time travel, schema enforcement, and `OPTIMIZE` |
| `catalog`, `schema` (bundle variables) | `workspace`, `medallion` | Where the tables and the `raw` volume live on Databricks: `databricks bundle deploy --var="catalog=main"` |

## What you'll see

Recorded on 2026-11-16 (UTC).

**Locally:** Apple M4 Pro (24 GB), on battery; Docker Engine 29.9.3 with 12 CPUs and 7.7 GiB for its VM. Image `apache/spark:4.2.0-python3` (index digest `sha256:fc64959c04bd87b0ac686be9aaa9008b69cdb1afc695400528279c8b01f43d89`) plus the Delta Lake 4.4.1 jars, checked by SHA-256 in [`spark/Dockerfile`](spark/Dockerfile); Python 3.10.12 and Java 21.0.11 inside it; Spark `local[*]`, 2 GB driver memory, 8 shuffle partitions. No other workload ran during the recorded run (checked every 5 seconds), and `verify.py` passed all 17 checks right after it.

**On Databricks:** Free Edition on AWS, serverless notebook task, Databricks CLI 1.26.0. Each step ran as its own job run.

**Counts.** Identical locally and on Databricks:

| Step | Bronze | Silver | Gold |
|---|---|---|---|
| Batch 1 | 50,000 rows appended | 50,000 inserted | 120 rows (12 companies × 10 days) |
| Batch 2 | 53,200 rows appended | 200 rejected (50 per reason); 50,000 inserted; 1,000 corrections updated; 1,956 copies matched and left unchanged | 240 rows |
| Batch 2 again | skipped: already loaded | 0 inserted, 0 updated; the 200 rejects replaced, not duplicated | 240 rows |
| Batch 3 | 50,000 rows appended; 13 columns | 50,000 inserted; `carrier` added (9 columns) | 360 rows, 150,000 events |

Why 1,956 copies and not 2,000: 44 events were both resent unchanged and corrected in batch 2, so within the batch only the correction was kept.

**Delta Lake features** (silver, after batch 3):

- **History:** version 0 `CREATE TABLE AS SELECT` (50,000 rows), then three `MERGE` versions (100,000, 100,000, 150,000 rows). The rerun of batch 2 still made a version, with no rows changed.
- **Time travel:** compared with version 0, exactly 1,000 events differ: the late corrections.
- **Schema enforcement:** three appends to an empty table with silver's schema.

  | Write | Result |
  |---|---|
  | An unknown column, `discount_code` | rejected (`DELTA_METADATA_MISMATCH`) |
  | `weight_kg` as the string `'heavy'` | rejected (`CAST_INVALID_INPUT`) |
  | `weight_kg` as the string `'12.5'` | **accepted**, stored as the number 12.5 |

  Delta checks the column names. A value of the wrong type goes through Spark's cast on write: if the cast succeeds, the write succeeds. Validate types before writing if a string in a number column should be an error.
- **`OPTIMIZE`:** silver went from 6 files to 1 locally, and from 3 to 1 on Databricks.

**Time per step, in seconds:** bronze, silver, and gold, timed inside the pipeline (one run each).

| Run | Local | Databricks |
|---|---|---|
| Batch 1 | 4.2, 5.0, 1.6 | 5.9, 9.9, 3.7 |
| Batch 2 | 5.7, 6.3, 1.7 | 6.3, 13.9, 3.0 |
| Batch 2 again | 4.3 (the check that skips it), 6.1, 1.6 | 1.2, 12.7, 2.7 |
| Batch 3 | 5.4, 5.3, 1.9 | 7.0, 9.3, 2.5 |
| Delta feature checks | 11.6 | 17.9 |

Each whole run, start to finish: 16 to 18 seconds locally (including starting Spark in a new container), and 27 to 35 seconds on Databricks.

On Databricks, about 2 seconds of each job run was setup. This data is far too small for timing to say anything about Spark or Delta performance. The numbers are here to show the runs, not to compare platforms.

## Limitations

- **Small, synthetic data.** 153,200 lines. The patterns are the point, not the scale.
- **Batch, not streaming.** Each batch is a separate run. Databricks Auto Loader or Structured Streaming would track new files by themselves; this example tracks batches by number, which is enough to show idempotent ingestion.
- **Bronze skips a whole batch.** If a batch is partly loaded and the job dies before the commit, Delta's atomic append means nothing was written, so a rerun loads it all. A batch with new files added after loading would need file-level tracking.
- **Gold is rebuilt in full.** Fine at this size. A large table would update only the changed days with `MERGE` or `replaceWhere`.
- **Free Edition** is for non-commercial use, serverless only, with a limit of 5 concurrent job tasks.

### Workspace files did not load on Databricks serverless

The first version ran the pipeline as a Python file task (`spark_python_task`) that imported `medallion.py` from the deployed bundle. On 2026-11-16 it failed every time with `OSError: [Errno 5] Input/output error` while reading the files under `/Workspace/Users/<you>/.bundle/...`:

- **Not the files:** the deployed copy was byte-for-byte identical to the local one, and stored as a plain file.
- **Not a delay after deploying:** a run several minutes later, with no redeploy, failed the same way.
- **Not the serverless environment version:** 2, 3, and 4 all failed.
- **Reported by others:** the same error on `.bundle` paths ([Databricks Community](https://community.databricks.com/t5/data-engineering/intermittent-oserror-errno-5-input-output-error-accessing/td-p/151675)), and on reading workspace files with Databricks Runtime 18 ([Databricks Community](https://community.databricks.com/t5/data-engineering/databricks-dbr-18-1-access-workspace-files-error/td-p/151114)). No fix is documented.

**What works:** a notebook task. `medallion.py` starts with the line `# Databricks notebook source`, so Databricks stores it as a notebook, and the job's notebook loads it with `%run ./medallion`. To Python that line is a comment, so the local runs import the same file as an ordinary module.

## Background

Data pipelines on Databricks were part of production work at 47Billion (see the [About page](https://snehalagrawal.com/about/)). This example is written from scratch for this repository, with synthetic data, and does not reproduce that work. It is one of the [data engineering patterns](../README.md) on [snehalagrawal.com/work](https://snehalagrawal.com/work/).
