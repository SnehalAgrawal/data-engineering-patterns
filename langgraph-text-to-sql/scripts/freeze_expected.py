"""Run every gold query once (as the owner) and store the expected answers in data/expected.json.

Also checks that "top 1" questions have no tie, so a correct answer cannot be marked wrong.
"""

import json
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.compare import normalise  # noqa: E402
from src.config import OWNER_URL  # noqa: E402

questions = json.loads((ROOT / "data" / "questions.json").read_text())["read"]
expected = {}
with psycopg.connect(OWNER_URL) as conn:
    for q in questions:
        rows = conn.execute(q["gold"]).fetchall()
        expected[q["id"]] = normalise(rows)
        if "LIMIT 1" in q["gold"]:
            # Re-run without LIMIT 1 and check the first two ranks differ
            ranked = conn.execute(q["gold"].replace("LIMIT 1", "LIMIT 2").replace(
                "SELECT ", "SELECT count(*) AS n_for_tie_check, ", 1)).fetchall()
            tie = len(ranked) == 2 and ranked[0][0] == ranked[1][0]
            print(f"{q['id']}: top {ranked[0][1:]} with {ranked[0][0]}, next {ranked[1][1:]} with {ranked[1][0]}{'  TIE!' if tie else ''}")
        shown = expected[q["id"]] if len(expected[q["id"]]) <= 3 else f"{len(expected[q['id']])} rows"
        print(f"{q['id']} {q['kind']:9} {shown}")
(ROOT / "data" / "expected.json").write_text(json.dumps(expected, indent=1) + "\n")
print(f"\nWrote expected answers for {len(expected)} questions to data/expected.json")
