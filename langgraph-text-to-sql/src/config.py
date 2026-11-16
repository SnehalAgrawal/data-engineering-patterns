"""Settings, from environment variables (see .env.example)."""

import os

# The agent connects as a read-only user (postgres/03-readonly-user.sql)
READER_URL = os.environ.get("READER_URL", "postgresql://agent_reader:reader@localhost:5433/fleet")
# The owner is used only to freeze the expected answers and to check that nothing was written
OWNER_URL = os.environ.get("OWNER_URL", "postgresql://owner:owner@localhost:5433/fleet")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("MODEL", "qwen2.5:3b")
MAX_ROWS = 200  # rows fetched from any query
