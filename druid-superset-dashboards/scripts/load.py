"""Load data/generated/clicks.json into two Druid tables with SQL-based ingestion.

clicks_raw:    one row per click
clicks_hourly: rolled up at ingestion (see sql/clicks_hourly.sql)
"""

from pathlib import Path

from druid import run_ingestion, sql, wait_for_rows, wait_until_ready

ROOT = Path(__file__).resolve().parent.parent
TABLES = {
    "clicks_raw": {},
    # Keep the HLL sketch as a sketch (not a number), so it can be merged at query time
    "clicks_hourly": {"finalizeAggregations": False},
}


def main():
    if not (ROOT / "data" / "generated" / "clicks.json").exists():
        raise SystemExit("data/generated/clicks.json is missing. Run: python3 scripts/generate_data.py")
    print(f"Druid ready after {wait_until_ready():.0f} s")
    for table, context in TABLES.items():
        query = (ROOT / "sql" / f"{table}.sql").read_text()
        print(f"Ingesting {table} ...", end="", flush=True)
        task_id, seconds = run_ingestion(query, context)
        wait_for_rows(table)
        rows = sql(f'SELECT COUNT(*) AS n FROM "{table}"')[0]["n"]
        print(f" done in {seconds:.0f} s, {rows:,} rows (task {task_id})")


if __name__ == "__main__":
    main()
