# Superset's official image does not include database drivers; add the Druid one (pydruid).
FROM apache/superset:6.1.0
USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache pydruid==0.6.9
USER superset
