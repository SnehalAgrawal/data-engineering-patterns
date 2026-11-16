"""Minimal Ollama chat client (standard library only), with deterministic settings."""

import json
import re
import time
import urllib.request

from .config import OLLAMA_URL


def chat(model: str, messages: list[dict], num_ctx: int = 8192) -> tuple[str, float]:
    """Return (reply text, seconds). temperature 0 and a fixed seed, so runs are repeatable."""
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_ctx": num_ctx}}
    started = time.perf_counter()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as res:
        reply = json.loads(res.read())["message"]["content"]
    return reply, time.perf_counter() - started


def extract_sql(reply: str) -> str:
    """The SQL from a reply: the first fenced code block, else the whole reply.

    Small models sometimes open a block and never close it (```sql with no closing ```), or label it
    ```postgresql; both are handled.
    """
    match = re.search(r"```[a-zA-Z]*[ \t]*\n?(.*?)(?:```|\Z)", reply, re.S)
    return (match.group(1) if match else reply).strip().rstrip(";").strip()
