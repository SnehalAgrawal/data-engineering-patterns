import pytest

from src.llm import extract_sql

SQL = "SELECT count(*) FROM packages"


@pytest.mark.parametrize("reply", [
    f"```sql\n{SQL}\n```",
    f"```sql\n{SQL};\n```",
    f"```sql\n{SQL}",  # opened but never closed (seen from llama3.2:3b)
    f"```postgresql\n{SQL}\n```",
    f"```\n{SQL}\n```",
    f"Here is the query:\n```sql\n{SQL}\n```\nIt counts packages.",
    SQL,
    f"{SQL};",
])
def test_extracts_the_query_from_common_reply_shapes(reply):
    assert extract_sql(reply) == SQL
