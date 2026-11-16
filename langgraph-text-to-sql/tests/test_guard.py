import pytest
import sqlglot

from src.guard import UnsafeQuery, check

ALLOWED = [
    "SELECT count(*) FROM packages",
    "SELECT c.name, count(*) FROM packages p JOIN companies c ON c.id = p.company_id GROUP BY c.name",
    "WITH t AS (SELECT company_id FROM packages) SELECT count(*) FROM t",
    "SELECT 1 UNION SELECT 2",
]

REJECTED = [
    "DELETE FROM events WHERE status = 'exception'",
    "UPDATE packages SET delivered_at = now() WHERE id = 42",
    "INSERT INTO companies VALUES (99, 'Test Logistics', 'FR')",
    "DROP TABLE events",
    "TRUNCATE events",
    "ALTER TABLE events ADD COLUMN x int",
    "CREATE TABLE x (id int)",
    "SELECT 1; DELETE FROM devices",  # a second statement
    "WITH gone AS (DELETE FROM devices RETURNING *) SELECT count(*) FROM gone",  # a write hidden in a CTE
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SET statement_timeout = 0",
    "COPY events TO '/tmp/events.csv'",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql):
    assert check(sql)


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_anything_else(sql):
    with pytest.raises((UnsafeQuery, sqlglot.errors.ParseError)):
        check(sql)
