-- 3,000,000 events spread evenly over October 1-30, 2026 (UTC), in id order.
-- setseed makes random() repeatable, so every fresh database holds the same rows.
SELECT setseed(0.42);

INSERT INTO tracking_events (event_time, device_id, package_id, company_id, status, lat, lon, battery_pct, temperature_c)
SELECT
  timestamptz '2026-10-01 00:00:00+00' + (g - 1) * (interval '30 days' / 3000000),
  'device_' || (1 + floor(random() * 500))::int,
  'pkg_' || (1 + floor(random() * 200000))::int,
  'company_' || (1 + floor(random() * 12))::int,
  (ARRAY['in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit',
         'delivered', 'delivered', 'delayed', 'exception'])[1 + floor(random() * 11)::int],
  8 + random() * 27,   -- latitude within India's bounding box
  68 + random() * 29,  -- longitude
  (5 + floor(random() * 96))::smallint,
  (-5 + random() * 45)::real
FROM generate_series(1, 3000000) AS g;

ANALYZE tracking_events;
