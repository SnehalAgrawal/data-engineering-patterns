"""The Text-to-SQL agent as a LangGraph state graph.

generate_sql -> check_sql -> execute -> END
      ^              |           |
      +--- repair ---+-----------+   (on a parse, plan, or runtime error, up to max_repairs times)

A request to change data ends at "refused": either the model says REFUSE, or the guard rejects the SQL.
Writes are never repaired into something else, and the read-only database user is a second line of defence.
"""

from collections.abc import Callable
from typing import TypedDict

import psycopg
import sqlglot
from langgraph.graph import END, START, StateGraph

from . import db, guard
from .llm import chat, extract_sql

SYSTEM = """You translate questions about a PostgreSQL database into exactly one SQL query.

Rules:
- Reply with a single PostgreSQL SELECT statement in a ```sql code block, and nothing else.
- Only read data. If the question asks to change, add, or delete data, reply with the single word REFUSE.
- Use only the tables and columns in the schema below. Text values are case-sensitive; use the values listed.

Schema:
{schema}"""

REPAIR = """That query failed with this error:
{error}

Write a corrected query. Reply with the SQL in a ```sql code block, and nothing else."""


class State(TypedDict, total=False):
    question: str
    model: str
    max_repairs: int
    schema: str
    sql: str
    error: str | None
    attempts: int
    outcome: str  # answered | refused | failed
    columns: list[str]
    rows: list[tuple]
    trace: list[dict]
    llm_seconds: float


def build(llm: Callable[[str, list[dict]], tuple[str, float]] = chat, schema_loader=db.schema_text,
          explain=db.explain, run=db.run):
    """Compile the graph. The model call and database functions can be swapped out (tests use fakes)."""

    def generate_sql(state: State) -> State:
        schema = state.get("schema") or schema_loader()
        messages = [{"role": "system", "content": SYSTEM.format(schema=schema)},
                    {"role": "user", "content": state["question"]}]
        if state.get("error"):  # repair: show the model its own query and what went wrong
            messages += [{"role": "assistant", "content": f"```sql\n{state['sql']}\n```"},
                         {"role": "user", "content": REPAIR.format(error=state["error"])}]
        reply, seconds = llm(state["model"], messages)
        attempts = state.get("attempts", 0) + 1
        step = {"step": "generate_sql" if attempts == 1 else "repair", "seconds": round(seconds, 2)}
        update: State = {"schema": schema, "attempts": attempts,
                         "llm_seconds": state.get("llm_seconds", 0) + seconds}
        if reply.strip().upper().startswith("REFUSE"):
            update.update(outcome="refused", trace=state.get("trace", []) + [{**step, "reply": "REFUSE"}])
            return update
        sql = extract_sql(reply)
        update.update(sql=sql, error=None, trace=state.get("trace", []) + [{**step, "sql": sql}])
        return update

    def check_sql(state: State) -> State:
        try:
            sql = guard.check(state["sql"])
            explain(sql)
        except guard.UnsafeQuery as e:
            return {"outcome": "refused", "trace": state["trace"] + [{"step": "check_sql", "refused": str(e)}]}
        except (sqlglot.errors.ParseError, psycopg.Error) as e:
            error = str(e).strip().splitlines()[0]
            return {"error": error, "trace": state["trace"] + [{"step": "check_sql", "error": error}]}
        return {"sql": sql, "trace": state["trace"] + [{"step": "check_sql", "ok": True}]}

    def execute(state: State) -> State:
        try:
            columns, rows = run(state["sql"])
        except psycopg.Error as e:
            error = str(e).strip().splitlines()[0]
            return {"error": error, "trace": state["trace"] + [{"step": "execute", "error": error}]}
        return {"outcome": "answered", "columns": columns, "rows": rows,
                "trace": state["trace"] + [{"step": "execute", "rows": len(rows)}]}

    def give_up(state: State) -> State:
        return {"outcome": "failed", "trace": state["trace"] + [{"step": "give_up", "attempts": state["attempts"]}]}

    def after_error(state: State) -> str:
        return "repair" if state["attempts"] <= state.get("max_repairs", 2) else "give_up"

    graph = StateGraph(State)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("check_sql", check_sql)
    graph.add_node("execute", execute)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "generate_sql")
    graph.add_conditional_edges("generate_sql", lambda s: "refused" if s.get("outcome") == "refused" else "check",
                                {"refused": END, "check": "check_sql"})
    graph.add_conditional_edges("check_sql",
                                lambda s: "refused" if s.get("outcome") == "refused" else (after_error(s) if s.get("error") else "ok"),
                                {"refused": END, "repair": "generate_sql", "give_up": "give_up", "ok": "execute"})
    graph.add_conditional_edges("execute", lambda s: after_error(s) if s.get("error") else "done",
                                {"repair": "generate_sql", "give_up": "give_up", "done": END})
    graph.add_edge("give_up", END)
    return graph.compile()


def ask(question: str, model: str, max_repairs: int = 2, app=None) -> State:
    """Run one question through the graph and return the final state."""
    app = app or build()
    return app.invoke({"question": question, "model": model, "max_repairs": max_repairs, "trace": []})
