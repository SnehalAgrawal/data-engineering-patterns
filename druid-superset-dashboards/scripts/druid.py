"""Tiny Druid client on the standard library: SQL queries and SQL-based ingestion tasks."""

import json
import os
import time
import urllib.error
import urllib.request

DRUID_URL = os.environ.get("DRUID_URL", "http://localhost:8888")


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{DRUID_URL}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read() or "null")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {path} -> {error.code}: {error.read().decode()[:500]}") from None


def sql(query, context=None):
    """Run a Druid SQL query and return rows as dicts."""
    return request("POST", "/druid/v2/sql", {"query": query, "context": context or {}})


def wait_until_ready(timeout=300):
    started = time.time()
    while time.time() - started < timeout:
        try:
            request("GET", "/status/health")
            request("GET", "/druid/indexer/v1/tasks?state=running")  # Overlord reachable through the router
            return time.time() - started
        except (RuntimeError, OSError):
            time.sleep(3)
    raise RuntimeError("Druid was not ready in time. Check: docker compose ps")


def run_ingestion(query, context=None):
    """Submit an INSERT/REPLACE statement as a task (multi-stage query engine) and wait for it."""
    task = request("POST", "/druid/v2/sql/task", {"query": query, "context": context or {}})
    task_id = task["taskId"]
    started = time.time()
    while True:
        status = request("GET", f"/druid/indexer/v1/task/{task_id}/status")["status"]
        if status["status"] == "SUCCESS":
            return task_id, time.time() - started
        if status["status"] == "FAILED":
            raise RuntimeError(f"Task {task_id} failed: {status.get('errorMsg')}")
        time.sleep(2)


def wait_for_rows(table, timeout=300):
    """After a task succeeds, segments still have to be loaded by the historical before they are queryable."""
    started = time.time()
    def count(where):
        # An aggregate over sys.segments returns no row at all (not 0) when nothing matches
        rows = sql(f"SELECT COUNT(*) AS n FROM sys.segments WHERE datasource = '{table}' AND {where}")
        return rows[0]["n"] if rows else 0

    while time.time() - started < timeout:
        if count("is_published = 1 AND is_available = 0") == 0 and count("is_available = 1") > 0:
            return
        time.sleep(2)
    raise RuntimeError(f"Segments for {table} were not loaded in time")
