# Spark: PostgreSQL to Parquet ETL

Extract a 3-million-row PostgreSQL table with Spark, write it as date-partitioned Parquet, and load new rows incrementally. In the recorded runs, parallel JDBC reads made the full load 3× faster than Spark's default, and a one-day query opened 1 file instead of 40.

## What it shows

- **Spark reads a JDBC table through one connection unless you tell it otherwise.** With no partitioning options, the whole table is one query and one task. Giving Spark a numeric column and bounds (`partitionColumn`, `lowerBound`, `upperBound`, `numPartitions`) splits the read into parallel range queries. Measured below: 13.5 s with one connection, 4.5 s with eight.
- **Partitioned Parquet lets queries skip files.** Written with `partitionBy("event_date")`, a filter on `event_date` opens only that day's folder. The same day filtered on `event_time` opens every file.
- **Incremental loads with a watermark.** After the full load, the job saves the highest `id` it loaded. The next run reads only rows above it, and a run with nothing new does nothing.
- **Columnar storage.** The same 3 million rows take 416 MB in PostgreSQL (table and primary key) and 122 MB as Parquet.

## How it works

```text
PostgreSQL 17 ─── tracking_events (3,000,000 rows, Oct 1–30, 2026; seeded on first start)
      │
      │  extract.py --partitions N     one JDBC query per id range, N in parallel
      ▼
Spark 4.2.1 (local[*]) ── adds event_date ──► lake/tracking_events/event_date=YYYY-MM-DD/*.parquet
      │                                        lake/_state/tracking_events.json  (watermark: max id loaded)
      │
      ├─ read_back.py      the same one-day question, filtered by partition column vs by timestamp
      └─ incremental.py    rows with id > watermark only, appended; watermark moved forward
```

- **Source** ([`postgres/`](postgres/)): an append-only `tracking_events` table (device, package, company, status, location, battery, temperature) with an identity `id`. Seeded with `setseed`, so every fresh database holds the same rows. [`sql/add_day.sql`](sql/add_day.sql) adds 100,000 rows for October 31.
- **Spark** ([`spark/Dockerfile`](spark/Dockerfile)): the official `apache/spark:4.2.1-python3` image plus the PostgreSQL JDBC driver 42.7.14, checked against a pinned SHA-256. Both images run natively on arm64 and amd64.
- **Jobs** ([`jobs/`](jobs/)): plain PySpark. Every JDBC read sets `fetchsize` to 10,000. The PostgreSQL driver's default (0) loads the whole result set into memory, which a 3-million-row single-partition read cannot afford.
- **Fixed ranges:** each job reads `id BETWEEN lo AND hi`, with both bounds taken at the start. Rows inserted while a job runs are left for the next incremental load, not half-read.

## Run it

Requirements: Docker with at least 3 GB of memory (PostgreSQL and Spark together peaked at 2.1 GiB during the 8-partition load). Nothing else on the host: Spark, Java, and Python run in the container.

```bash
# 1. Start PostgreSQL; the first start creates and seeds 3,000,000 rows (a few seconds), and --wait waits for it
docker compose up -d --wait postgres

# 2. Full load (the first run also builds the Spark image)
docker compose run --rm spark extract.py --partitions 1   # Spark's default: one connection
docker compose run --rm spark extract.py --partitions 8   # eight parallel range reads

# 3. Query the Parquet back: partition pruning
docker compose run --rm spark read_back.py

# 4. A new day arrives; load only the new rows (the second run finds nothing to do)
docker compose exec postgres psql -U etl -d tracking -f /sql/add_day.sql
docker compose run --rm spark incremental.py
docker compose run --rm spark incremental.py
```

Output goes to `lake/` in this folder (ignored by git). To start over: `docker compose down -v && rm -rf lake`.

## Configuration

Set in `docker-compose.yml` for local use:

| Setting | Value | Where |
|---|---|---|
| PostgreSQL user, password, database | `etl` / `etl` / `tracking` | `postgres` service; `PG_*` variables of the `spark` service |
| Spark master and driver memory | `local[*]`, 2 GB | `spark` service entrypoint |
| Lake path | `/lake` (this folder's `lake/`) | `LAKE` variable |
| JDBC fetch size | 10,000 rows | [`jobs/common.py`](jobs/common.py) |

## What you'll see

Recorded on 2026-11-15:

- **Machine:** Apple silicon Mac, Docker 29.9.3 with 12 CPUs and 7.75 GiB.
- **Images and driver:** `apache/spark:4.2.1-python3`, `postgres:17.6`, PostgreSQL JDBC 42.7.14.

**How the timings were taken.** Other local workloads (model runs on the same machine) can slow a run several-fold, so every timed run waited for 30 quiet seconds first. A sampler then checked every second whether another workload became active. A run that overlapped was rejected and repeated. One earlier single-partition load that overlapped other work took 59.4 s; it is not used. A final run from scratch (empty database, image rebuilt) gave 13.3 s with one partition and 4.7 s with eight, in line with the table.

**Full load**, read + transform + write, 3 accepted runs each (all runs moved exactly 3,000,000 rows):

| JDBC partitions | Runs | Median | Parquet files |
|---|---|---|---|
| 1 (Spark's default) | 13.2, 13.5, 13.8 s | **13.5 s** | 30 |
| 4 | 5.7, 5.5, 6.2 s | **5.7 s** | 32 |
| 8 | 5.5, 4.5, 4.2 s | **4.5 s** | 36 |
| 12 | 5.4, 4.3, 5.0 s | **5.0 s** | 36 |

Eight partitions was the sweet spot here: 3× faster than one. Twelve did not help, because PostgreSQL and writing Parquet become the limit, not the number of connections. More partitions also means more files: a read task whose id range crosses midnight writes one file per day it touches.

**Read back** (`read_back.py`, after the incremental load, so 31 days and 40 files): events and average temperature by status, median of 5 runs. Two runs of the job:

```text
  filter                                           rows  files  dates      MB     time
  whole table                                 3,100,000     40     31   126.2    122 ms
  event_date = day (partition column)           100,000      1      1     4.1     43 ms
  event_time within day (not partitioned)       100,000     40     31   126.2     94 ms
```
```text
  whole table                                 3,100,000     40     31   126.2    114 ms
  event_date = day (partition column)           100,000      1      1     4.1     43 ms
  event_time within day (not partitioned)       100,000     40     31   126.2     97 ms
```

Files, dates, and MB are what the scan selected after partition pruning (from Spark's scan metrics). Filtering on the partition column opened 1 file out of 40 and ran about 2.2× faster. Filtering the same day by timestamp opened all 40: Spark cannot map `event_time` to `event_date` folders.

**Incremental load** (`incremental.py`, after `add_day.sql`):

```text
Incremental load from watermark id 3,000,000
  read: 100,000 new rows (ids 3,000,001-3,100,000) in 1.3 s
  Parquet: 4 new files, 1 new date partition(s)
  totals: 3,100,000 rows in Parquet, 3,100,000 in PostgreSQL (match)
  watermark: id 3,000,000 -> 3,100,000
```
and the second run:
```text
Incremental load: no rows above watermark id 3,100,000. Nothing to do.
```

## Limitations

- **The watermark assumes an append-only table with ids that appear in order.** Updated or deleted rows are never picked up. With concurrent writers, a transaction can commit a lower id after a higher one, and an id watermark would skip it. For those cases, use change data capture, or re-read an overlap window and deduplicate. A table format with `MERGE` (Delta Lake, Iceberg) handles updates in the lake.
- **Even ranges need an evenly spread column.** The ids here are dense and sequential, so each partition gets the same number of rows. On a skewed column, some tasks get most of the rows and the speed-up shrinks.
- **One machine.** Spark runs in `local[*]` mode with a 2 GB driver. On a cluster, the same options spread the read across executors, and PostgreSQL's capacity to serve parallel queries becomes the limit.
- **Small files.** Partitioning by day and reading in many tasks writes several small files per day. Large tables need compaction or a `repartition` before writing.
- **Bytes read are not reported.** Spark's `inputBytes` metric reported implausibly low numbers for these local Parquet reads, so the read-back table shows what was selected, not bytes read.
- **Local credentials.** `etl`/`etl` is for your own machine only.

## Background

This example rebuilds the Spark part of [ai-analytics-postgres-spark-weaviate](https://github.com/SnehalAgrawal/ai-analytics-postgres-spark-weaviate) (2025), which read the table through one connection and wrote one Parquet file. It also fell back to pandas when PySpark was missing, so Spark might not run at all. The question-answering part of that repository was not carried forward.

Two bugs were fixed while building this:
- **Read-back timing.** The first version of `read_back.py` timed the same DataFrame repeatedly, and Spark reused its earlier shuffle output instead of scanning again, so the times were too fast. The job now builds a new query for every run.
- **Healthcheck.** The PostgreSQL healthcheck first used `pg_isready` over the local socket, which already succeeds while first-start seeding is still running. It now checks over TCP, which only answers once seeding is done.
