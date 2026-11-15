-- The next day arrives: 100,000 more events on October 31, 2026, for the incremental load.
SELECT setseed(0.31);

INSERT INTO tracking_events (event_time, device_id, package_id, company_id, status, lat, lon, battery_pct, temperature_c)
SELECT
  timestamptz '2026-10-31 00:00:00+00' + (g - 1) * (interval '1 day' / 100000),
  'device_' || (1 + floor(random() * 500))::int,
  'pkg_' || (1 + floor(random() * 200000))::int,
  'company_' || (1 + floor(random() * 12))::int,
  (ARRAY['in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit', 'in_transit',
         'delivered', 'delivered', 'delayed', 'exception'])[1 + floor(random() * 11)::int],
  8 + random() * 27,
  68 + random() * 29,
  (5 + floor(random() * 96))::smallint,
  (-5 + random() * 45)::real
FROM generate_series(1, 100000) AS g;
