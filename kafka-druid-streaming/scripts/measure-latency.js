// How long until a click is visible to Druid SQL?
// Each trial sends one uniquely tagged click through the app, then polls Druid until a query finds it.
// Usage: npm run latency -- --trials 20
import { parseArgs } from "node:util";
import { config } from "../src/config.js";
import { sql } from "../src/druid.js";

const { values } = parseArgs({ options: { trials: { type: "string", default: "20" } } });
const trials = Number(values.trials);
const POLL_MS = 50;
const TIMEOUT_MS = 60_000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function trial(n) {
  const userId = `latency-${Date.now()}-${n}`;
  const started = performance.now();
  const res = await fetch(`http://localhost:${config.port}/click`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId, page: "/latency-test" }),
  });
  if (!res.ok) throw new Error(`POST /click failed: ${res.status}`);
  while (performance.now() - started < TIMEOUT_MS) {
    const [row] = await sql(`SELECT COUNT(*) AS n FROM "${config.dataSource}" WHERE userId = ?`, [
      { type: "VARCHAR", value: userId },
    ]);
    if (row?.n > 0) return performance.now() - started;
    await sleep(POLL_MS);
  }
  throw new Error(`Click ${userId} not visible after ${TIMEOUT_MS / 1000} s`);
}

const results = [];
for (let n = 1; n <= trials; n++) {
  const ms = await trial(n);
  results.push(ms);
  console.log(`trial ${String(n).padStart(2)}: ${Math.round(ms)} ms`);
  await sleep(250);
}

const sorted = [...results].sort((a, b) => a - b);
const pct = (p) => sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
console.log(`\nClick sent → visible in Druid SQL, ${trials} trials (polling every ${POLL_MS} ms):`);
console.log(`  min ${Math.round(sorted[0])} ms · median ${Math.round(pct(50))} ms · p90 ${Math.round(pct(90))} ms · max ${Math.round(sorted.at(-1))} ms`);
