import express from "express";
import { config } from "./config.js";
import { connectProducer, disconnectProducer, sendClick } from "./kafka.js";
import { isMissingTable, queries, sql } from "./druid.js";

const app = express();
app.use(express.json());
app.use(express.static(new URL("../public", import.meta.url).pathname));

// Ingest: validate, stamp the time on the server, publish to Kafka.
app.post("/click", async (req, res) => {
  const { userId, page } = req.body ?? {};
  if (typeof userId !== "string" || typeof page !== "string" || !userId || !page.startsWith("/")) {
    return res.status(400).json({ error: "Send JSON with a userId string and a page path starting with /" });
  }
  const event = { userId, page, timestamp: new Date().toISOString() };
  await sendClick(event);
  res.status(202).json({ status: "queued", event });
});

// Query: three Druid SQL queries, run in parallel, with the time they took.
app.get("/stats", async (_req, res) => {
  const started = performance.now();
  try {
    const [topPages, perMinute, [totals]] = await Promise.all([
      sql(queries.topPages),
      sql(queries.perMinute),
      sql(queries.totals),
    ]);
    res.json({ topPages, perMinute, totals, queryMs: Math.round(performance.now() - started) });
  } catch (error) {
    if (isMissingTable(error)) {
      return res.json({ topPages: [], perMinute: [], totals: { events: 0, latest: null }, queryMs: null });
    }
    res.status(502).json({ error: `Druid query failed: ${error.message}` });
  }
});

// Express 5 forwards rejected promises here (for example, Kafka unavailable).
app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(503).json({ error: error.message });
});

await connectProducer();
const server = app.listen(config.port, () => {
  console.log(`Clickstream app on http://localhost:${config.port} (Kafka ${config.kafkaBrokers.join(",")}, Druid ${config.druidUrl})`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    server.close();
    await disconnectProducer();
    process.exit(0);
  });
}
