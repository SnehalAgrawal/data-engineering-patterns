"""Against the real PostgreSQL (docker compose up -d): the agent's user can read but never write."""

import psycopg
import pytest

from src.config import READER_URL
from src.db import run, schema_text


def test_reader_can_read_and_sees_the_column_descriptions():
    columns, rows = run("SELECT count(*) FROM companies")
    assert rows == [(12,)]
    assert "One of: in_transit, delayed, exception, delivered" in schema_text()


@pytest.mark.parametrize("sql", [
    "DELETE FROM events",
    "UPDATE packages SET weight_kg = 0",
    "INSERT INTO companies VALUES (99, 'x', 'FR')",
    "DROP TABLE events",
])
def test_reader_cannot_write_even_if_the_guard_were_bypassed(sql):
    with psycopg.connect(READER_URL) as conn, pytest.raises(psycopg.Error):
        conn.execute(sql)
