import { config } from "./config.js";

/** Run a Druid SQL query through the router and return rows as objects. */
export async function sql(query, parameters = []) {
  const res = await fetch(`${config.druidUrl}/druid/v2/sql`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, parameters }),
  });
  const body = await res.json();
  if (!res.ok) {
    const error = new Error(body.errorMessage ?? body.error ?? `Druid returned ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return body;
}

/** Until the first event is ingested the table does not exist yet; treat that as "no data". */
export function isMissingTable(error) {
  return /not found|does not exist/i.test(error.message);
}

export const queries = {
  topPages: `
    SELECT page, COUNT(*) AS views, COUNT(DISTINCT userId) AS users
    FROM "${config.dataSource}"
    GROUP BY page
    ORDER BY views DESC
    LIMIT 10`,
  // Last 10 minutes, one row per minute
  perMinute: `
    SELECT TIME_FLOOR(__time, 'PT1M') AS bucket, COUNT(*) AS views
    FROM "${config.dataSource}"
    WHERE __time >= CURRENT_TIMESTAMP - INTERVAL '10' MINUTE
    GROUP BY 1
    ORDER BY 1`,
  totals: `
    SELECT COUNT(*) AS events, MAX(__time) AS latest
    FROM "${config.dataSource}"`,
};
