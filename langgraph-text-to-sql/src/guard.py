"""Static check before anything reaches the database: exactly one read-only SELECT statement.

This is the first line of defence; the read-only database user is the second (see postgres/03-readonly-user.sql).
"""

import sqlglot
from sqlglot import exp

# Anything that writes, changes the schema, or runs a non-query command
FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Grant, exp.Copy, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
)
# Functions that can touch the server or files, even inside a SELECT
FORBIDDEN_FUNCTIONS = {"pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "lo_import", "lo_export",
                       "dblink", "pg_terminate_backend", "pg_cancel_backend", "set_config"}


class UnsafeQuery(ValueError):
    """The SQL is not a single read-only SELECT."""


def check(sql: str) -> str:
    """Return the statement, normalised, if it is a single SELECT; raise UnsafeQuery or sqlglot.ParseError otherwise."""
    statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    if len(statements) != 1:
        raise UnsafeQuery(f"expected exactly one statement, got {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Query):  # SELECT, UNION, ..., including WITH ... SELECT
        raise UnsafeQuery(f"only SELECT queries are allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise UnsafeQuery(f"{type(node).__name__} is not allowed")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeQuery(f"function {name}() is not allowed")
    return tree.sql(dialect="postgres")
