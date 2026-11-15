-- Rolled up at ingestion: one row per hour per (page, country, device).
-- views counts the clicks in that row; users_sketch is an HLL sketch of user IDs, so unique users
-- can still be estimated across any combination of rows. user_id and referrer are not kept.
-- Runs with finalizeAggregations = false, so Druid stores the sketch itself, not a number.
REPLACE INTO clicks_hourly OVERWRITE ALL
SELECT
  TIME_FLOOR(TIME_PARSE("timestamp"), 'PT1H') AS __time,
  page, country, device,
  COUNT(*) AS views,
  DS_HLL(user_id) AS users_sketch
FROM TABLE(
  EXTERN(
    '{"type": "local", "baseDir": "/data/generated", "filter": "clicks.json"}',
    '{"type": "json"}'
  )
) EXTEND ("timestamp" VARCHAR, user_id VARCHAR, page VARCHAR, country VARCHAR, device VARCHAR, referrer VARCHAR)
GROUP BY 1, 2, 3, 4
PARTITIONED BY DAY
