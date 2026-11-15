// Send synthetic clicks through the app's API (the same path a browser uses).
// Usage: npm run simulate -- --rate 20 --seconds 60
import { parseArgs } from "node:util";
import { config } from "../src/config.js";

const { values } = parseArgs({
  options: {
    rate: { type: "string", default: "10" }, // events per second
    seconds: { type: "string", default: "60" },
  },
});
const rate = Number(values.rate);
const seconds = Number(values.seconds);

// Uneven traffic, so the top-pages ranking is meaningful.
const pages = [
  ["/home", 35], ["/pricing", 20], ["/products", 15], ["/docs", 12],
  ["/blog", 8], ["/about", 5], ["/careers", 3], ["/contact", 2],
];
const totalWeight = pages.reduce((sum, [, weight]) => sum + weight, 0);
function randomPage() {
  let pick = Math.random() * totalWeight;
  for (const [page, weight] of pages) {
    pick -= weight;
    if (pick < 0) return page;
  }
  return pages[0][0];
}

const url = `http://localhost:${config.port}/click`;
let sent = 0;
let failed = 0;

async function sendOne() {
  const body = { userId: `user-${Math.floor(Math.random() * 200)}`, page: randomPage() };
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.ok) sent++;
    else failed++;
  } catch {
    failed++;
  }
}

console.log(`Sending ${rate} clicks/s for ${seconds} s to ${url}`);
const timer = setInterval(sendOne, 1000 / rate);
const progress = setInterval(() => console.log(`  sent ${sent}, failed ${failed}`), 5000);
setTimeout(() => {
  clearInterval(timer);
  clearInterval(progress);
  setTimeout(() => console.log(`Done: sent ${sent}, failed ${failed}`), 500);
}, seconds * 1000);
