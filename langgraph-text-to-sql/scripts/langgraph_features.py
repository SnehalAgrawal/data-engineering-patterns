"""What LangGraph itself adds to the agent, shown with a scripted fake model and fake database.

No Ollama and no PostgreSQL: every number here is about the framework, not the model.

    python scripts/langgraph_features.py            # all five demonstrations
    python scripts/langgraph_features.py --only overhead

1. stream:     stream_mode="updates" yields each node's update as it finishes.
2. pause:      an approval node calls interrupt(); with a checkpointer the run stops before the SQL runs, and
               Command(resume=...) continues it.
3. merge:      a node's return value replaces a state key unless the key has a reducer.
4. recursion:  without the graph's own repair cap, how far a failing loop runs before LangGraph stops it.
5. overhead:   time per invocation of the compiled graph against a plain Python function doing the same work.
"""

import argparse
import operator
import platform
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, TypedDict

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.errors import GraphRecursionError  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

from src import guard  # noqa: E402
from src.graph import build  # noqa: E402
from src.llm import extract_sql  # noqa: E402

GOOD = "```sql\nSELECT count(*) FROM packages WHERE delivered_at IS NULL\n```"
BAD = "```sql\nSELECT count(*) FROM packages WHERE shipped IS NULL\n```"


def scripted(*replies, repeat_last=False):
    """A fake model: returns the replies in order (or the last one forever), and counts calls."""
    calls = []

    def llm(model, messages):
        calls.append(messages)
        index = min(len(calls), len(replies)) - 1 if repeat_last else len(calls) - 1
        return replies[index], 0.0

    return llm, calls


def explain(sql):
    if "shipped" in sql:
        raise psycopg.errors.UndefinedColumn('column "shipped" does not exist')


def run(sql):
    return ["count"], [(457,)]


def schema():
    return "packages(id, delivered_at)"


QUESTION = {"question": "How many packages are undelivered?", "model": "fake", "max_repairs": 2, "trace": []}


class Overwrite(TypedDict):
    trace: list[str]


class Append(TypedDict):
    trace: Annotated[list[str], operator.add]


def demo_stream():
    print("== 1. stream_mode='updates': one event per finished node (a query that fails once, then is repaired)")
    llm, _ = scripted(BAD, GOOD)
    app = build(llm, schema, explain, run)
    for event in app.stream(QUESTION, stream_mode="updates"):
        for node, update in event.items():
            detail = {k: update[k] for k in ("sql", "error", "outcome") if update.get(k)}
            print(f"  {node:<13} keys={sorted(update)}  {detail}")


def demo_pause():
    print("\n== 2. approval with interrupt() and a checkpointer: pause before the SQL runs, then approve or reject")
    for decision in ("approve", "reject"):
        llm, calls = scripted(GOOD)
        executed = []

        def run_and_record(sql, executed=executed):
            executed.append(sql)
            return run(sql)

        app = build(llm, schema, explain, run_and_record, approval=True, checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": f"question-{decision}"}}
        result = app.invoke(QUESTION, config)
        paused = app.get_state(config)
        if decision == "approve":
            print(f"  after invoke: next={paused.next}  executed={len(executed)}")
            print(f"  interrupt payload: {result['__interrupt__'][0].value}")
        final = app.invoke(Command(resume=decision), config)
        print(f"  resume with {decision!r}: outcome={final['outcome']!r} executed={len(executed)} "
              f"model calls={len(calls)} checkpoints={len(list(app.get_state_history(config)))}")

    # A node that pauses runs again from its first line when resumed, so work before interrupt() repeats.
    entered = []

    def notify_then_wait(state):
        entered.append("notify reviewer")  # a side effect before the pause
        return {"trace": [interrupt("approve?")]}

    graph = StateGraph(Append)
    graph.add_node("notify_then_wait", notify_then_wait)
    graph.add_edge(START, "notify_then_wait")
    graph.add_edge("notify_then_wait", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "side-effect"}}
    app.invoke({"trace": []}, config)
    app.invoke(Command(resume="approve"), config)
    print(f"  a node with a side effect before interrupt(): the side effect ran {len(entered)} times for one approval")


def demo_merge():
    print("\n== 3. state merge: a node's return value replaces a key unless the key has a reducer")
    for schema_type in (Overwrite, Append):
        graph = StateGraph(schema_type)
        graph.add_node("first", lambda s: {"trace": ["first"]})
        graph.add_node("second", lambda s: {"trace": ["second"]})
        graph.add_edge(START, "first")
        graph.add_edge("first", "second")
        graph.add_edge("second", END)
        result = graph.compile().invoke({"trace": ["start"]})
        print(f"  {schema_type.__name__:<9} trace={result['trace']}")


def demo_recursion():
    print("\n== 4. a model that never fixes its query, with the graph's own cap removed (max_repairs=10**6)")
    for limit in (None, 25):
        llm, calls = scripted(BAD, repeat_last=True)
        app = build(llm, schema, explain, run)
        config = {} if limit is None else {"recursion_limit": limit}
        label = "default limit" if limit is None else f"recursion_limit={limit}"
        start = time.perf_counter()
        try:
            app.invoke({**QUESTION, "max_repairs": 10**6}, config)
            print(f"  {label}: finished (unexpected)")
        except GraphRecursionError:
            print(f"  {label}: GraphRecursionError after {len(calls):,} model calls "
                  f"({time.perf_counter() - start:.2f} s with a fake model)")


def plain_python(question, llm, max_repairs=2):
    """The same flow as the graph, as a loop: generate, check, execute, repair on error."""
    messages = [{"role": "system", "content": "schema"}, {"role": "user", "content": question}]
    sql, error = None, None
    for attempt in range(1, max_repairs + 2):
        if error:
            messages = messages + [{"role": "assistant", "content": sql}, {"role": "user", "content": error}]
        reply, _ = llm("fake", messages)
        if reply.strip().upper().startswith("REFUSE"):
            return {"outcome": "refused"}
        sql = extract_sql(reply)
        try:
            sql = guard.check(sql)
            explain(sql)
            columns, rows = run(sql)
            return {"outcome": "answered", "rows": rows, "attempts": attempt}
        except guard.UnsafeQuery:
            return {"outcome": "refused"}
        except psycopg.Error as e:
            error = str(e)
    return {"outcome": "failed"}


def timed(fn, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples) * 1e6


def demo_overhead(repeats=2000):
    print(f"\n== 5. time per question, median of {repeats:,} (fake model and database; guard and SQL parsing included)")
    rows = []
    for label, replies in (("first try", (GOOD,)), ("one repair", (BAD, GOOD))):
        state = {"i": 0}

        def llm(model, messages, replies=replies, state=state):  # replays the script; reset before each call
            reply = replies[min(state["i"], len(replies) - 1)]
            state["i"] += 1
            return reply, 0.0

        compiled = build(llm, schema, explain, run)

        def graph_call(compiled=compiled, state=state):
            state["i"] = 0
            return compiled.invoke(QUESTION)

        def loop_call(llm=llm, state=state):
            state["i"] = 0
            return plain_python("q", llm)

        def compile_and_call(llm=llm, state=state):
            state["i"] = 0
            return build(llm, schema, explain, run).invoke(QUESTION)

        assert graph_call()["outcome"] == loop_call()["outcome"] == "answered"
        for _ in range(200):  # warm-up
            graph_call(), loop_call()
        rows.append((label, timed(loop_call, repeats), timed(graph_call, repeats), timed(compile_and_call, repeats // 4)))
    print(f"  {'':<11} {'plain loop':>11} {'graph':>11} {'compile + run':>14}")
    for label, loop_us, graph_us, compile_us in rows:
        print(f"  {label:<11} {loop_us:>8.0f} us {graph_us:>8.0f} us {compile_us:>11.0f} us")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["stream", "pause", "merge", "recursion", "overhead"])
    args = parser.parse_args()
    print(f"langgraph {version('langgraph')}, langgraph-checkpoint {version('langgraph-checkpoint')}, "
          f"Python {platform.python_version()}, {platform.machine()}\n")
    demos = {"stream": demo_stream, "pause": demo_pause, "merge": demo_merge,
             "recursion": demo_recursion, "overhead": demo_overhead}
    for name, demo in demos.items():
        if args.only in (None, name):
            demo()


if __name__ == "__main__":
    main()
