"""The graph's control flow, with a scripted fake model and fake database (no Ollama, no PostgreSQL)."""

import psycopg

from src.graph import ask, build


def scripted(*replies):
    """A fake model that returns the given replies in order, and records what it was sent."""
    calls = []

    def llm(model, messages):
        calls.append(messages)
        return replies[len(calls) - 1], 0.01

    return llm, calls


def fake_db(bad_columns=()):
    """EXPLAIN fails for queries that mention one of bad_columns (the guard normalises SQL, so match on a word)."""

    def explain(sql):
        if any(column in sql for column in bad_columns):
            raise psycopg.errors.UndefinedColumn('column "shipped" does not exist')

    def run(sql):
        return ["count"], [(457,)]

    return explain, run


def test_answers_on_the_first_attempt():
    llm, calls = scripted("```sql\nSELECT count(*) FROM packages WHERE delivered_at IS NULL\n```")
    explain, run = fake_db()
    state = ask("How many packages are undelivered?", "fake", app=build(llm, lambda: "schema", explain, run))
    assert state["outcome"] == "answered" and state["rows"] == [(457,)] and state["attempts"] == 1
    assert len(calls) == 1


def test_repairs_a_query_after_an_error_and_shows_the_model_the_error():
    bad = "SELECT count(*) FROM packages WHERE shipped IS NULL"
    llm, calls = scripted(f"```sql\n{bad}\n```", "```sql\nSELECT count(*) FROM packages WHERE delivered_at IS NULL\n```")
    explain, run = fake_db(bad_columns={"shipped"})
    state = ask("How many packages are undelivered?", "fake", app=build(llm, lambda: "schema", explain, run))
    assert state["outcome"] == "answered" and state["attempts"] == 2
    assert 'column "shipped" does not exist' in calls[1][-1]["content"]


def test_gives_up_after_max_repairs():
    bad = "SELECT nope FROM packages"
    llm, calls = scripted(*[f"```sql\n{bad}\n```"] * 3)
    explain, run = fake_db(bad_columns={"nope"})
    state = ask("?", "fake", max_repairs=2, app=build(llm, lambda: "schema", explain, run))
    assert state["outcome"] == "failed" and state["attempts"] == 3 and len(calls) == 3


def test_no_repair_when_max_repairs_is_zero():
    bad = "SELECT nope FROM packages"
    llm, calls = scripted(f"```sql\n{bad}\n```")
    explain, run = fake_db(bad_columns={"nope"})
    state = ask("?", "fake", max_repairs=0, app=build(llm, lambda: "schema", explain, run))
    assert state["outcome"] == "failed" and len(calls) == 1


def test_a_model_refusal_ends_the_run():
    llm, calls = scripted("REFUSE")
    explain, run = fake_db()
    state = ask("Delete all events", "fake", app=build(llm, lambda: "schema", explain, run))
    assert state["outcome"] == "refused" and "sql" not in state


def test_the_guard_stops_a_write_the_model_produced_and_it_is_never_repaired():
    llm, calls = scripted("```sql\nDELETE FROM events\n```")
    ran = []
    explain, _ = fake_db()
    state = ask("Delete all events", "fake", app=build(llm, lambda: "schema", explain, lambda sql: ran.append(sql)))
    assert state["outcome"] == "refused" and ran == [] and len(calls) == 1
