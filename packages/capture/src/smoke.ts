/**
 * KAGE Capture - Smoke test
 *
 * Recorder を直接叩いて scripted なクリック操作を挟み、
 * events.jsonl に click / input / navigation が載ることを検証する。
 *
 * 実行:
 *   pnpm --filter @kage/capture tsx src/smoke.ts
 */

import * as path from "node:path";
import * as fs from "node:fs/promises";
import { Recorder } from "./recorder.js";
import { bundleRun } from "./bundle.js";

async function main(): Promise<void> {
  const runDir = path.resolve(
    "./runs",
    `smoke-${new Date().toISOString().replace(/[:.]/g, "-")}`,
  );

  const recorder = new Recorder({
    targetUrl: "https://news.ycombinator.com",
    runDir,
    headless: true,
  });

  await recorder.start();

  const page = recorder.getPage();
  if (!page) throw new Error("page not ready");

  await page.waitForLoadState("domcontentloaded");
  // HN top page: click the "new" nav link (stable) to trigger click + navigation
  try {
    await page.getByRole("link", { name: "new", exact: true }).first().click({ timeout: 5000 });
    await page.waitForLoadState("domcontentloaded");
  } catch (err) {
    console.warn("[smoke] click on 'new' link failed:", err);
  }

  // Give a moment for events to flush
  await new Promise((r) => setTimeout(r, 1500));

  await recorder.stop();
  const zipPath = `${runDir}.kage.zip`;
  await bundleRun(runDir, zipPath);

  // Inspect events.jsonl
  const events = await fs.readFile(path.join(runDir, "events.jsonl"), "utf8");
  const lines = events.split("\n").filter(Boolean);
  console.log(`[smoke] events captured: ${lines.length}`);
  for (const l of lines) {
    const e = JSON.parse(l) as { type: string; timestamp: number; url?: string };
    console.log(`  - ${e.type.padEnd(10)} @${e.timestamp}ms${e.url ? " " + e.url : ""}`);
  }

  const hasClick = lines.some((l) => JSON.parse(l).type === "click");
  const hasNav = lines.some((l) => JSON.parse(l).type === "navigation");
  console.log(`[smoke] has click: ${hasClick}`);
  console.log(`[smoke] has navigation: ${hasNav}`);

  if (!hasClick) {
    console.error("[smoke] FAIL: expected at least one click event");
    process.exit(1);
  }
  console.log(`[smoke] OK: bundle at ${zipPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
