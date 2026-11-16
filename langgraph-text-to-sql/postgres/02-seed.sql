-- Repeatable data: setseed makes random() return the same sequence on every fresh database.
SELECT setseed(0.17);

INSERT INTO companies (id, name, country)
SELECT g,
       (ARRAY['Northwind Freight', 'Blue Dart Logistics', 'Kestrel Cargo', 'Monsoon Movers', 'Harbor Line',
              'Alpine Express', 'Saffron Shipping', 'Coastal Couriers', 'Granite Haulage', 'Lotus Logistics',
              'Meridian Mail', 'Vertex Transport'])[g],
       (ARRAY['IN', 'IN', 'SG', 'IN', 'US', 'DE', 'IN', 'AU', 'US', 'SG', 'GB', 'DE'])[g]
FROM generate_series(1, 12) AS g;

INSERT INTO devices (id, company_id, model, installed_on)
SELECT g,
       1 + floor(random() * 12)::int,
       (ARRAY['T100', 'T200', 'T300'])[1 + floor(random() * 3)::int],
       date '2025-01-01' + floor(random() * 600)::int
FROM generate_series(1, 400) AS g;

-- 3,000 packages shipped in October 2026; about 85% delivered, 1 to 6 days after shipping
INSERT INTO packages (id, company_id, origin_city, destination_city, weight_kg, shipped_at, delivered_at)
SELECT g, company_id, origin, destination, weight, shipped,
       CASE WHEN random() < 0.85 THEN shipped + (interval '1 day' * (1 + random() * 5)) END
FROM (
  SELECT g,
         1 + floor(random() * 12)::int AS company_id,
         (ARRAY['Mumbai', 'Delhi', 'Bengaluru', 'Chennai', 'Pune', 'Hyderabad', 'Kolkata', 'Ahmedabad'])[1 + floor(random() * 8)::int] AS origin,
         (ARRAY['Mumbai', 'Delhi', 'Bengaluru', 'Chennai', 'Pune', 'Hyderabad', 'Kolkata', 'Ahmedabad'])[1 + floor(random() * 8)::int] AS destination,
         round((0.5 + random() * 39.5)::numeric, 2) AS weight,
         timestamptz '2026-10-01 00:00+00' + interval '1 second' * floor(random() * 30 * 86400) AS shipped
  FROM generate_series(1, 3000) AS g
) AS p;

-- About 60 events per package, between shipping and delivery (or 3 days after shipping if not delivered)
INSERT INTO events (id, device_id, package_id, event_time, status, city, temperature_c, battery_pct)
SELECT row_number() OVER (),
       1 + floor(random() * 400)::int,
       p.id,
       p.shipped_at + (coalesce(p.delivered_at, p.shipped_at + interval '3 days') - p.shipped_at) * (n / 60.0),
       CASE WHEN n = 60 AND p.delivered_at IS NOT NULL THEN 'delivered'
            WHEN random() < 0.08 THEN 'delayed'
            WHEN random() < 0.03 THEN 'exception'
            ELSE 'in_transit' END,
       CASE WHEN n < 30 THEN p.origin_city ELSE p.destination_city END,
       round((-5 + random() * 45)::numeric, 1),
       (100 - n - floor(random() * 10))::smallint
FROM packages AS p, generate_series(1, 60) AS n;

ANALYZE;
