-- Source table: append-only tracking events from delivery devices.
CREATE TABLE tracking_events (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_time    timestamptz NOT NULL,
  device_id     text NOT NULL,
  package_id    text NOT NULL,
  company_id    text NOT NULL,
  status        text NOT NULL,
  lat           double precision NOT NULL,
  lon           double precision NOT NULL,
  battery_pct   smallint NOT NULL,
  temperature_c real NOT NULL
);
