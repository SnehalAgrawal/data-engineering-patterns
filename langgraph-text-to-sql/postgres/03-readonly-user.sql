-- The agent connects as this user: it can read the four tables and nothing else.
CREATE ROLE agent_reader LOGIN PASSWORD 'reader';
GRANT CONNECT ON DATABASE fleet TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON companies, devices, packages, events TO agent_reader;
-- Every transaction is read-only, and no query runs longer than 5 seconds
ALTER ROLE agent_reader SET default_transaction_read_only = on;
ALTER ROLE agent_reader SET statement_timeout = '5s';
