"""Evaluate the agent on the frozen question set, per model.

For each read question: correct on the first attempt (no repair), correct after up to 2 repairs, attempts,
and model time. For each write request: refused by the model (REFUSE), stopped by the guard, or executed.
Then checks, as the owner, that no table changed.

    python scripts/evaluate.py --models qwen2.5:3b,llama3.2:3b

Writes one JSON line per question to results/<model>.jsonl.
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.compare import matches  # noqa: E402
from src.config import OWNER_URL  # noqa: E402
from src.graph import ask, build  # noqa: E402

TABLES = ["companies", "devices", "packages", "events"]


def row_counts():
    with psycopg.connect(OWNER_URL) as conn:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def first_attempt_correct(state, expected, run_sql):
    """Was the first generated query correct on its own? Re-runs it if a repair happened later."""
    first = next((t for t in state["trace"] if t["step"] == "generate_sql"), None)
    if not first or "sql" not in first:
        return False
    if state["attempts"] == 1:
        return state["outcome"] == "answered" and matches(state["rows"], expected)
    return False  # the first query failed (that is why there was a repair)


def evaluate(model, questions, expected):
    app = build()
    out = ROOT / "results" / f"{model.replace(':', '_')}.jsonl"
    out.parent.mkdir(exist_ok=True)
    rows = []
    with out.open("w") as f:
        for q in questions["read"]:
            s = ask(q["question"], model, max_repairs=2, app=app)
            correct = s["outcome"] == "answered" and matches(s["rows"], expected[q["id"]])
            record = {"id": q["id"], "kind": q["kind"], "outcome": s["outcome"], "attempts": s["attempts"],
                      "first_try_correct": first_attempt_correct(s, expected[q["id"]], None),
                      "correct": correct, "llm_seconds": round(s["llm_seconds"], 2), "trace": s["trace"],
                      "rows": [list(map(str, r)) for r in s.get("rows", [])[:5]]}
            f.write(json.dumps(record) + "\n")
            rows.append(record)
            print(f"  {q['id']} {q['kind']:9} {s['outcome']:8} attempts {s['attempts']} "
                  f"{'correct' if correct else 'WRONG'}{' (rescued by repair)' if correct and s['attempts'] > 1 else ''}", flush=True)
        for q in questions["write"]:
            s = ask(q["question"], model, max_repairs=2, app=app)
            stopped_by = next((("model" if t.get("reply") == "REFUSE" else "guard") for t in s["trace"]
                               if t.get("reply") == "REFUSE" or "refused" in t), None)
            if s["outcome"] == "answered":
                # It ran something; the guard only lets a single SELECT through, so no write was produced
                stopped_by = "no write produced"
            record = {"id": q["id"], "kind": "write", "outcome": s["outcome"], "stopped_by": stopped_by,
                      "sql": s.get("sql"), "trace": s["trace"]}
            f.write(json.dumps(record) + "\n")
            rows.append(record)
            print(f"  {q['id']} write     {s['outcome']:8} stopped by {stopped_by or '-'}"
                  f"{'' if s['outcome'] == 'refused' else '  (ran: ' + str(s.get('sql'))[:70] + ')'}", flush=True)
    return rows


def summarise(model, rows):
    read = [r for r in rows if r["kind"] != "write"]
    writes = [r for r in rows if r["kind"] == "write"]
    kinds = ["simple", "aggregate", "join", "time"]
    print(f"\n{model}: {len(read)} read questions, {len(writes)} write requests")
    print(f"  {'kind':10} {'first try':>10} {'after repair':>13}")
    for kind in kinds + ["all"]:
        group = read if kind == "all" else [r for r in read if r["kind"] == kind]
        first = sum(r["first_try_correct"] for r in group)
        final = sum(r["correct"] for r in group)
        print(f"  {kind:10} {f'{first}/{len(group)}':>10} {f'{final}/{len(group)}':>13}")
    repaired = [r for r in read if r["attempts"] > 1]
    print(f"  repairs: {len(repaired)} questions needed one; {sum(r['correct'] for r in repaired)} ended correct")
    wrong_but_ran = [r["id"] for r in read if r["outcome"] == "answered" and not r["correct"]]
    print(f"  ran without error but wrong (never repaired): {len(wrong_but_ran)} {wrong_but_ran}")
    print(f"  failed after all repairs: {[r['id'] for r in read if r['outcome'] == 'failed']}")
    by = {k: [w["id"] for w in writes if w["stopped_by"] == k] for k in ("model", "guard", "no write produced")}
    print(f"  write requests: refused by the model {len(by['model'])}, stopped by the guard {len(by['guard'])}, "
          f"answered a read part without producing a write {len(by['no write produced'])} {by['no write produced']}")
    seconds = sorted(r["llm_seconds"] for r in read)
    print(f"  model time per read question: median {seconds[len(seconds) // 2]:.1f} s, max {seconds[-1]:.1f} s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="qwen2.5:3b,llama3.2:3b")
    parser.add_argument("--summarise-only", action="store_true", help="re-print the summary from results/*.jsonl")
    args = parser.parse_args()
    if args.summarise_only:
        for model in args.models.split(","):
            path = ROOT / "results" / f"{model.replace(':', '_')}.jsonl"
            summarise(model, [json.loads(line) for line in path.read_text().splitlines()])
        return
    questions = json.loads((ROOT / "data" / "questions.json").read_text())
    expected = json.loads((ROOT / "data" / "expected.json").read_text())

    before = row_counts()
    for model in args.models.split(","):
        print(f"\n### {model}")
        summarise(model, evaluate(model, questions, expected))
    after = row_counts()
    print(f"\nRow counts before {before}\n           after  {after}\n  -> {'unchanged' if before == after else 'CHANGED'}")


if __name__ == "__main__":
    main()
