// One-time setup after `docker compose up -d`:
// 1. wait until Druid is ready, 2. create the Kafka topic, 3. start Druid's Kafka ingestion (the supervisor).
import { readFile } from "node:fs/promises";
import { config } from "../src/config.js";
import { kafka } from "../src/kafka.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(label, check, timeoutMs = 300_000) {
  const started = Date.now();
  process.stdout.write(`Waiting for ${label}`);
  while (Date.now() - started < timeoutMs) {
    try {
      if (await check()) {
        console.log(` ready (${Math.round((Date.now() - started) / 1000)} s)`);
        return;
      }
    } catch {
      // not up yet
    }
    process.stdout.write(".");
    await sleep(3000);
  }
  throw new Error(`${label} was not ready after ${timeoutMs / 1000} s. Check: docker compose ps`);
}

const druid = (path, init) => fetch(`${config.druidUrl}${path}`, init);

await waitFor("the Druid router", async () => (await druid("/status/health")).ok);
// The supervisor API is served by the Overlord; the router proxies it once the Overlord is up.
await waitFor("the Druid Overlord", async () => (await druid("/druid/indexer/v1/supervisor")).ok);

const admin = kafka.admin();
await admin.connect();
const created = await admin.createTopics({ topics: [{ topic: config.topic, numPartitions: 1 }] });
console.log(created ? `Created Kafka topic "${config.topic}"` : `Kafka topic "${config.topic}" already exists`);
await admin.disconnect();

const spec = await readFile(new URL("../supervisor.json", import.meta.url), "utf8");
const res = await druid("/druid/indexer/v1/supervisor", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: spec,
});
if (!res.ok) throw new Error(`Submitting the supervisor failed (${res.status}): ${await res.text()}`);
console.log(`Submitted Kafka supervisor: ${JSON.stringify(await res.json())}`);

// RUNNING means the supervisor is up; its ingestion task starts its own JVM a few seconds later.
// The task is reading once it reports current offsets for the topic's partitions.
await waitFor("the ingestion task to start reading", async () => {
  const { payload } = await (await druid(`/druid/indexer/v1/supervisor/${config.dataSource}/status`)).json();
  return payload?.state === "RUNNING" && payload.activeTasks?.some((task) => Object.keys(task.currentOffsets ?? {}).length > 0);
});
console.log(`Done. Start the app (npm start), then open ${config.druidUrl} for the Druid console.`);
