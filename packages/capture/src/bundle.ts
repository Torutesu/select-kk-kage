/**
 * KAGE Capture - Bundler
 *
 * runDir を <projectName>-<runId>.kage.zip に固める。
 * pipeline はこの zip を受け取って IR を生成する。
 */

import AdmZip from "adm-zip";
import * as path from "node:path";
import * as fs from "node:fs/promises";

export async function bundleRun(runDir: string, outputPath: string): Promise<string> {
  const zip = new AdmZip();
  await addDirToZip(zip, runDir, "");

  // video ファイルは Playwright が context.close() 後に <random>.webm として置くので拾って名前揃える
  const entries = await fs.readdir(runDir);
  const videoFile = entries.find((f) => f.endsWith(".webm"));
  if (videoFile && videoFile !== "recording.webm") {
    const buf = await fs.readFile(path.join(runDir, videoFile));
    zip.addFile("recording.webm", buf);
    zip.deleteFile(videoFile);
  }

  zip.writeZip(outputPath);
  return outputPath;
}

async function addDirToZip(zip: AdmZip, dir: string, prefix: string): Promise<void> {
  const items = await fs.readdir(dir, { withFileTypes: true });
  for (const item of items) {
    const full = path.join(dir, item.name);
    const rel = prefix ? `${prefix}/${item.name}` : item.name;
    if (item.isDirectory()) {
      await addDirToZip(zip, full, rel);
    } else {
      const buf = await fs.readFile(full);
      zip.addFile(rel, buf);
    }
  }
}
