-- Every click as its own row: exact, and the largest table.
REPLACE INTO clicks_raw OVERWRITE ALL
SELECT
  TIME_PARSE("timestamp") AS __time,
  user_id, page, country, device, referrer
FROM TABLE(
  EXTERN(
    '{"type": "local", "baseDir": "/data/generated", "filter": "clicks.json"}',
    '{"type": "json"}'
  )
) EXTEND ("timestamp" VARCHAR, user_id VARCHAR, page VARCHAR, country VARCHAR, device VARCHAR, referrer VARCHAR)
PARTITIONED BY DAY
