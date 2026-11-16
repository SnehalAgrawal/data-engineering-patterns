"""Database access: the schema the model sees, EXPLAIN, and running a query as the read-only user."""

import psycopg

from .config import MAX_ROWS, READER_URL


def schema_text(url: str = READER_URL) -> str:
    """CREATE TABLE-like text for every table, with the column descriptions stored in the database."""
    query = """
        SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
               col_description(format('%I', c.table_name)::regclass, c.ordinal_position) AS note,
               obj_description(format('%I', c.table_name)::regclass, 'pg_class') AS table_note
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        ORDER BY c.table_name, c.ordinal_position"""
    with psycopg.connect(url) as conn:
        rows = conn.execute(query).fetchall()
        foreign_keys = conn.execute("""
            SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'""").fetchall()
    references = {(t, c): f"{rt}.{rc}" for t, c, rt, rc in foreign_keys}
    tables: dict[str, list[str]] = {}
    notes: dict[str, str] = {}
    for table, column, dtype, nullable, note, table_note in rows:
        parts = [f"  {column} {dtype}", "" if nullable == "YES" else " NOT NULL"]
        if (table, column) in references:
            parts.append(f" REFERENCES {references[(table, column)]}")
        if note:
            parts.append(f"  -- {note}")
        tables.setdefault(table, []).append("".join(parts))
        notes[table] = table_note or ""
    return "\n\n".join(
        f"-- {notes[t]}\nCREATE TABLE {t} (\n" + ",\n".join(cols) + "\n);" for t, cols in tables.items()
    )


def explain(sql: str, url: str = READER_URL) -> None:
    """Raise if PostgreSQL cannot plan the query (unknown column, type error, ...). Nothing is executed."""
    with psycopg.connect(url) as conn:
        conn.execute(f"EXPLAIN {sql}")


def run(sql: str, url: str = READER_URL) -> tuple[list[str], list[tuple]]:
    """Run a query and return (column names, up to MAX_ROWS rows)."""
    with psycopg.connect(url) as conn:
        cur = conn.execute(sql)
        return [d.name for d in cur.description], cur.fetchmany(MAX_ROWS)
