"""Ask one question and see every step the agent takes.

    python ask.py "Which city shipped the most packages?"
    python ask.py --model llama3.2:3b --max-repairs 0 "How many events are delayed?"
"""

import argparse
import json

from src.config import MODEL
from src.graph import ask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--max-repairs", type=int, default=2)
    args = parser.parse_args()

    state = ask(args.question, args.model, args.max_repairs)
    for step in state["trace"]:
        print(json.dumps(step))
    print(f"\noutcome: {state['outcome']} after {state['attempts']} attempt(s), {state['llm_seconds']:.1f} s of model time")
    if state["outcome"] == "answered":
        print(f"SQL: {state['sql']}")
        print(" | ".join(state["columns"]))
        for row in state["rows"][:20]:
            print(" | ".join(str(v) for v in row))
        if len(state["rows"]) > 20:
            print(f"... {len(state['rows']) - 20} more rows")


if __name__ == "__main__":
    main()
