#!/usr/bin/env node
/**
 * KAGE Capture CLI
 *
 * 使い方:
 *   kage-capture record --url https://linear.app --name linear-clone
 *   → 可視ブラウザが起動。対象サイトを操作する。
 *   → 終了したくなったら Ctrl+C or 提示される「Enter to stop」を押す。
 *   → ./runs/<projectName>-<timestamp>/ に成果物が溜まり、
 *     ./runs/<projectName>-<timestamp>.kage.zip として固められる。
 */

import { Command } from "commander";
import chalk from "chalk";
import * as path from "node:path";
import * as fs from "node:fs/promises";
import { Recorder } from "./recorder.js";
import { bundleRun } from "./bundle.js";

const program = new Command();

program
  .name("kage-capture")
  .description("KAGE: Record a web SaaS for cloning")
  .version("0.0.1");

program
  .command("record")
  .description("Start recording a web SaaS session")
  .requiredOption("-u, --url <url>", "Target SaaS URL to record")
  .requiredOption("-n, --name <name>", "Project name (lowercase, hyphens only)")
  .option("-o, --out <dir>", "Output directory", "./runs")
  .option("--headless", "Run headless (default: false)", false)
  .option("--width <w>", "Viewport width", "1440")
  .option("--height <h>", "Viewport height", "900")
  .option(
    "--max-duration <seconds>",
    "Auto-stop after N seconds (for unattended recording / CI). Default: wait for Ctrl+C",
  )
  .action(async (opts) => {
    const projectName = opts.name as string;
    if (!/^[a-z0-9-]+$/.test(projectName)) {
      console.error(chalk.red("project name must be lowercase alphanumeric with hyphens only"));
      process.exit(1);
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const runId = `${projectName}-${timestamp}`;
    const runDir = path.resolve(opts.out, runId);
    await fs.mkdir(runDir, { recursive: true });

    console.log(chalk.cyan(`KAGE recording started`));
    console.log(chalk.gray(`  target   : ${opts.url}`));
    console.log(chalk.gray(`  project  : ${projectName}`));
    console.log(chalk.gray(`  runDir   : ${runDir}`));
    console.log(chalk.gray(`  viewport : ${opts.width}x${opts.height}`));
    console.log();
    console.log(chalk.yellow("Browser will open. Interact with the target SaaS."));
    console.log(chalk.yellow("Press Ctrl+C (or close the browser) to stop and bundle."));

    const recorder = new Recorder({
      targetUrl: opts.url,
      runDir,
      headless: !!opts.headless,
      viewport: {
        width: parseInt(opts.width, 10),
        height: parseInt(opts.height, 10),
      },
    });

    let stopping = false;
    const stop = async () => {
      if (stopping) return;
      stopping = true;
      console.log(chalk.cyan("\nStopping recorder..."));
      try {
        await recorder.stop();
        const zipPath = path.resolve(opts.out, `${runId}.kage.zip`);
        await bundleRun(runDir, zipPath);
        console.log(chalk.green(`✓ Bundle saved: ${zipPath}`));
        console.log(chalk.gray(`  Run dir   : ${runDir}`));
        console.log();
        console.log(chalk.cyan("Next step:"));
        console.log(chalk.gray(`  cd packages/pipeline && uv run python -m kage_pipeline ${zipPath}`));
      } catch (err) {
        console.error(chalk.red("Failed to stop recorder:"), err);
        process.exit(1);
      }
      process.exit(0);
    };

    process.on("SIGINT", stop);
    process.on("SIGTERM", stop);

    try {
      await recorder.start();
    } catch (err) {
      console.error(chalk.red("Recorder failed to start:"), err);
      process.exit(1);
    }

    if (opts.maxDuration) {
      const seconds = parseInt(opts.maxDuration, 10);
      if (!Number.isFinite(seconds) || seconds <= 0) {
        console.error(chalk.red("--max-duration must be a positive integer"));
        process.exit(1);
      }
      console.log(chalk.gray(`  auto-stop in ${seconds}s`));
      setTimeout(stop, seconds * 1000);
    }
  });

program.parseAsync().catch((err) => {
  console.error(err);
  process.exit(1);
});
