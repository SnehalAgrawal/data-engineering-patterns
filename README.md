# data-engineering-patterns

Small, runnable examples of data engineering patterns: streaming ingestion, real-time analytics, dashboards, and batch ETL.

Part of [snehalagrawal.com/work](https://snehalagrawal.com/work/). Each example is self-contained in its own folder, runs locally with Docker, and has a README with the exact setup it was tested with.

## Examples

| Example | What it shows | Status |
|---|---|---|
| [`kafka-druid-streaming/`](kafka-druid-streaming/) | Click events from a Node.js API through Kafka into Druid's streaming ingestion, queried with Druid SQL; measured click-to-query latency and memory | Ready (from [real-time-analytics-druid-kafka](https://github.com/SnehalAgrawal/real-time-analytics-druid-kafka)) |
| [`druid-superset-dashboards/`](druid-superset-dashboards/) | SQL-based batch ingestion into Druid, raw and rolled up by hour (measured rows, storage, sketch accuracy, query time), with a Superset dashboard created from code | Ready (from [data-visualization-druid-superset](https://github.com/SnehalAgrawal/data-visualization-druid-superset)) |
| [`spark-postgres-etl/`](spark-postgres-etl/) | Spark extracting a 3-million-row PostgreSQL table: parallel JDBC reads (measured 3× faster), date-partitioned Parquet with pruning, and incremental loads with a watermark | Ready (Spark part of [ai-analytics-postgres-spark-weaviate](https://github.com/SnehalAgrawal/ai-analytics-postgres-spark-weaviate)) |
| [`langgraph-text-to-sql/`](langgraph-text-to-sql/) | A LangGraph agent that answers plain-English questions with SQL over PostgreSQL: a SQL guard, a read-only database user, and a repair loop; accuracy measured on 30 questions with local models, and every write request stopped | Ready |
| `databricks-delta-medallion/` | Bronze, silver, and gold Delta tables on Databricks | Planned |

## Conventions

- **One folder per example**, with its own README, `docker-compose.yml`, `.env.example`, and code. Nothing is shared between examples, so each one can be copied out on its own.
- **Pinned versions.** Docker images use exact tags, never `latest`. Dependencies are pinned.
- **Every README follows the same outline:** what it shows, how it works (with a diagram), how to run it, configuration, what you'll see, and limitations.
- **Real output only.** Screenshots and printed results come from an actual run, recorded with the date and the versions used.
- **Resources are stated up front.** Some of these stacks are heavy (Druid wants about 8 GB of RAM). Each README says what it needs, and how to stop and clean up (`docker compose down -v`).
- **No secrets.** Configuration goes through environment variables; `.env` is never committed.

## Linting

One configuration at the repository root covers every example: [Ruff](https://docs.astral.sh/ruff/) for Python (`ruff.toml`) and [ESLint](https://eslint.org/) for JavaScript (`eslint.config.js`).

```bash
npm install                          # ESLint (the root package.json holds only lint tools)
pip install -r requirements-dev.txt  # Ruff
npm run lint                         # both
```
