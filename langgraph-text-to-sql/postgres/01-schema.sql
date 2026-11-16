-- Fleet tracking: companies ship packages; devices travel with packages and report events.
CREATE TABLE companies (
  id       integer PRIMARY KEY,
  name     text NOT NULL,
  country  text NOT NULL            -- ISO country code, e.g. 'IN'
);

CREATE TABLE devices (
  id            integer PRIMARY KEY,
  company_id    integer NOT NULL REFERENCES companies (id),
  model         text NOT NULL,      -- 'T100', 'T200', or 'T300'
  installed_on  date NOT NULL
);

CREATE TABLE packages (
  id                integer PRIMARY KEY,
  company_id        integer NOT NULL REFERENCES companies (id),
  origin_city       text NOT NULL,
  destination_city  text NOT NULL,
  weight_kg         numeric(6, 2) NOT NULL,
  shipped_at        timestamptz NOT NULL,
  delivered_at      timestamptz      -- NULL while not delivered
);

CREATE TABLE events (
  id             bigint PRIMARY KEY,
  device_id      integer NOT NULL REFERENCES devices (id),
  package_id     integer NOT NULL REFERENCES packages (id),
  event_time     timestamptz NOT NULL,
  status         text NOT NULL,     -- 'in_transit', 'delayed', 'exception', or 'delivered'
  city           text NOT NULL,
  temperature_c  numeric(4, 1) NOT NULL,
  battery_pct    smallint NOT NULL
);

CREATE INDEX ON events (package_id);
CREATE INDEX ON events (event_time);

-- Descriptions the agent reads together with the schema
COMMENT ON TABLE companies IS 'Shipping companies (customers)';
COMMENT ON COLUMN companies.country IS 'ISO 3166 country code, e.g. IN, US, SG';
COMMENT ON TABLE devices IS 'Tracking devices; each belongs to one company';
COMMENT ON COLUMN devices.model IS 'One of: T100, T200, T300';
COMMENT ON TABLE packages IS 'Packages shipped by a company, from origin_city to destination_city';
COMMENT ON COLUMN packages.delivered_at IS 'NULL means the package has not been delivered';
COMMENT ON TABLE events IS 'Tracking events reported by a device for a package';
COMMENT ON COLUMN events.status IS 'One of: in_transit, delayed, exception, delivered';
COMMENT ON COLUMN events.temperature_c IS 'Temperature in degrees Celsius at the time of the event';
COMMENT ON COLUMN events.battery_pct IS 'Device battery level, 0 to 100';
