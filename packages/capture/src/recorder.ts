/**
 * KAGE Capture - Recorder
 *
 * Playwright + CDP を使って以下を同時記録する:
 *
 * 1. 動画 (webm)                    → Playwright の recordVideo
 * 2. ネットワーク通信 (HAR)          → Playwright の recordHar
 * 3. DOM スナップショット (JSONL)    → CDP の DOMSnapshot.captureSnapshot
 * 4. A11y tree スナップショット       → CDP の Accessibility.getFullAXTree
 * 5. ユーザーイベント (JSONL)        → page.on('*') + CDP Input events
 * 6. スクリーンショット (各イベント時) → page.screenshot
 *
 * 出力:
 *   <runDir>/
 *     recording.webm
 *     network.har
 *     dom_snapshots.jsonl
 *     a11y_snapshots.jsonl
 *     events.jsonl
 *     screenshots/<event_id>.png
 *     metadata.json
 */

import { chromium, type Browser, type BrowserContext, type Page, type CDPSession } from "playwright";
import * as path from "node:path";
import * as fs from "node:fs/promises";
import { randomUUID } from "node:crypto";

export interface RecorderOptions {
  targetUrl: string;
  runDir: string;
  /** 録画を止める待機時間(ms)。ユーザーが Ctrl+C で止めるまで待つ場合は Infinity。 */
  maxDurationMs?: number;
  /** ヘッドレスモード(デフォルトは false = 可視ブラウザ) */
  headless?: boolean;
  /** ビューポートサイズ */
  viewport?: { width: number; height: number };
}

interface EventRecord {
  id: string;
  type:
    | "navigation"
    | "click"
    | "dblclick"
    | "input"
    | "submit"
    | "keydown"
    | "scroll"
    | "load"
    | "request"
    | "response";
  timestamp: number; // ms since recording start
  url?: string;
  selector?: string;
  target?: {
    tagName: string;
    role?: string;
    text?: string;
    bbox?: { x: number; y: number; width: number; height: number };
  };
  value?: string;
  method?: string;
  status?: number;
  screenshotPath?: string;
}

export class Recorder {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private cdp: CDPSession | null = null;
  private startedAt: number = 0;
  private events: EventRecord[] = [];
  private domSnapshotsStream: fs.FileHandle | null = null;
  private a11ySnapshotsStream: fs.FileHandle | null = null;

  constructor(private readonly opts: RecorderOptions) {}

  /** Read-only access to the underlying page after start(). Used for scripted smoke tests. */
  getPage(): Page | null {
    return this.page;
  }

  async start(): Promise<void> {
    await fs.mkdir(this.opts.runDir, { recursive: true });
    await fs.mkdir(path.join(this.opts.runDir, "screenshots"), { recursive: true });

    this.startedAt = Date.now();

    this.browser = await chromium.launch({
      headless: this.opts.headless ?? false,
      args: ["--disable-blink-features=AutomationControlled"],
    });

    this.context = await this.browser.newContext({
      viewport: this.opts.viewport ?? { width: 1440, height: 900 },
      recordVideo: {
        dir: this.opts.runDir,
        size: this.opts.viewport ?? { width: 1440, height: 900 },
      },
      recordHar: {
        path: path.join(this.opts.runDir, "network.har"),
        content: "embed",
      },
    });

    this.page = await this.context.newPage();
    this.cdp = await this.context.newCDPSession(this.page);

    // CDP domains
    await this.cdp.send("DOM.enable");
    await this.cdp.send("DOMSnapshot.enable");
    await this.cdp.send("Accessibility.enable");
    await this.cdp.send("Runtime.enable");
    await this.cdp.send("Page.enable");

    // Open streaming files
    this.domSnapshotsStream = await fs.open(
      path.join(this.opts.runDir, "dom_snapshots.jsonl"),
      "w"
    );
    this.a11ySnapshotsStream = await fs.open(
      path.join(this.opts.runDir, "a11y_snapshots.jsonl"),
      "w"
    );

    this.setupEventListeners();

    // ブラウザから飛んでくるカスタムイベントを受ける
    // exposeFunction は navigation を越えて維持される
    await this.page.exposeFunction(
      "__kage_receive",
      async (ev: { type: string; detail: Record<string, unknown> }) => {
        await this.recordUserEvent(ev.type, ev.detail);
      }
    );

    // ブラウザ内に記録ヘルパーを注入(クリック検知等)
    // addInitScript は navigation ごとに再実行されるため、
    // リスナもここに同梱しないと遷移後に捕捉できない
    await this.page.addInitScript(() => {
      // @ts-expect-error - injected into page context
      window.__kageRecord = (event: { type: string; detail: unknown }) => {
        window.dispatchEvent(new CustomEvent("__kage_event", { detail: event }));
      };

      window.addEventListener("__kage_event", (e) => {
        // @ts-expect-error - exposed via exposeFunction
        window.__kage_receive((e as CustomEvent).detail);
      });

      // すべてのクリックを記録
      document.addEventListener(
        "click",
        (e) => {
          const target = e.target as HTMLElement | null;
          if (!target) return;
          const rect = target.getBoundingClientRect();
          // @ts-expect-error - injected
          window.__kageRecord({
            type: "click",
            detail: {
              tagName: target.tagName,
              role: target.getAttribute("role") ?? undefined,
              text: target.textContent?.slice(0, 200) ?? "",
              selector: buildSelector(target),
              bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
            },
          });
        },
        true
      );

      document.addEventListener(
        "submit",
        (e) => {
          const form = e.target as HTMLFormElement | null;
          if (!form) return;
          // @ts-expect-error - injected
          window.__kageRecord({
            type: "submit",
            detail: {
              selector: buildSelector(form),
              action: form.action,
            },
          });
        },
        true
      );

      document.addEventListener(
        "input",
        (e) => {
          const t = e.target as HTMLInputElement | HTMLTextAreaElement | null;
          if (!t) return;
          if (t.type === "password") return; // パスワードは記録しない
          // @ts-expect-error - injected
          window.__kageRecord({
            type: "input",
            detail: {
              selector: buildSelector(t),
              value: t.value.slice(0, 500),
              inputType: t.type,
            },
          });
        },
        true
      );

      function buildSelector(el: Element): string {
        // data-testid 優先 → id → タグ+クラス
        const testid = el.getAttribute("data-testid");
        if (testid) return `[data-testid="${testid}"]`;
        if (el.id) return `#${el.id}`;
        const cls = (el.className ?? "")
          .toString()
          .split(" ")
          .filter(Boolean)
          .slice(0, 2)
          .map((c) => `.${c}`)
          .join("");
        return `${el.tagName.toLowerCase()}${cls}`;
      }
    });

    // Navigation
    this.page.on("framenavigated", async (frame) => {
      if (frame !== this.page?.mainFrame()) return;
      await this.recordEvent({
        type: "navigation",
        url: frame.url(),
      });
      await this.captureDomAndA11y();
    });

    // Request / Response のハイレベル記録(詳細は HAR に入るのでここでは軽く)
    this.page.on("request", (req) => {
      const url = req.url();
      if (!isApiLike(url)) return;
      this.events.push({
        id: randomUUID(),
        type: "request",
        timestamp: Date.now() - this.startedAt,
        url,
        method: req.method(),
      });
    });
    this.page.on("response", (resp) => {
      const url = resp.url();
      if (!isApiLike(url)) return;
      this.events.push({
        id: randomUUID(),
        type: "response",
        timestamp: Date.now() - this.startedAt,
        url,
        status: resp.status(),
      });
    });

    await this.page.goto(this.opts.targetUrl, { waitUntil: "domcontentloaded" });
  }

  private setupEventListeners(): void {
    // 追加のリスナーが必要ならここに
  }

  private async recordUserEvent(
    type: string,
    detail: Record<string, unknown>
  ): Promise<void> {
    const eventId = randomUUID();
    const screenshotPath = path.join("screenshots", `${eventId}.png`);

    // スクショはベストエフォート
    try {
      await this.page?.screenshot({
        path: path.join(this.opts.runDir, screenshotPath),
        fullPage: false,
      });
    } catch {
      // ignore
    }

    const bbox = detail.bbox as EventRecord["target"] extends infer T
      ? T extends { bbox?: infer B }
        ? B
        : undefined
      : undefined;

    this.events.push({
      id: eventId,
      type: type as EventRecord["type"],
      timestamp: Date.now() - this.startedAt,
      selector: detail.selector as string | undefined,
      value: detail.value as string | undefined,
      target: {
        tagName: (detail.tagName as string) ?? "",
        role: detail.role as string | undefined,
        text: detail.text as string | undefined,
        bbox,
      },
      screenshotPath,
    });

    // DOM + A11y スナップショット(負荷高いので click/submit 時だけ)
    if (type === "click" || type === "submit") {
      await this.captureDomAndA11y(eventId);
    }
  }

  private async recordEvent(partial: Partial<EventRecord> & { type: EventRecord["type"] }): Promise<void> {
    this.events.push({
      id: randomUUID(),
      type: partial.type,
      timestamp: Date.now() - this.startedAt,
      url: partial.url,
      selector: partial.selector,
    });
  }

  private async captureDomAndA11y(triggerEventId?: string): Promise<void> {
    if (!this.cdp || !this.domSnapshotsStream || !this.a11ySnapshotsStream) return;

    try {
      const domSnap = await this.cdp.send("DOMSnapshot.captureSnapshot", {
        computedStyles: [
          "background-color",
          "color",
          "font-size",
          "font-family",
          "padding",
          "margin",
          "border-radius",
          "display",
          "flex-direction",
        ],
        includePaintOrder: false,
        includeDOMRects: true,
      });
      await this.domSnapshotsStream.write(
        JSON.stringify({
          timestamp: Date.now() - this.startedAt,
          triggerEventId,
          url: this.page?.url(),
          snapshot: domSnap,
        }) + "\n"
      );
    } catch (e) {
      console.error("DOM snapshot failed:", e);
    }

    try {
      const ax = await this.cdp.send("Accessibility.getFullAXTree");
      await this.a11ySnapshotsStream.write(
        JSON.stringify({
          timestamp: Date.now() - this.startedAt,
          triggerEventId,
          url: this.page?.url(),
          tree: ax.nodes,
        }) + "\n"
      );
    } catch (e) {
      console.error("A11y snapshot failed:", e);
    }
  }

  async stop(): Promise<void> {
    // flush events
    await fs.writeFile(
      path.join(this.opts.runDir, "events.jsonl"),
      this.events.map((e) => JSON.stringify(e)).join("\n") + "\n"
    );

    await fs.writeFile(
      path.join(this.opts.runDir, "metadata.json"),
      JSON.stringify(
        {
          targetUrl: this.opts.targetUrl,
          startedAt: new Date(this.startedAt).toISOString(),
          durationMs: Date.now() - this.startedAt,
          eventCount: this.events.length,
          captureTool: "kage-capture",
          version: "0.0.1",
        },
        null,
        2
      )
    );

    await this.domSnapshotsStream?.close();
    await this.a11ySnapshotsStream?.close();

    await this.page?.close();
    await this.context?.close(); // これで video / har が確定保存される
    await this.browser?.close();
  }
}

function isApiLike(url: string): boolean {
  // ざっくり: XHR/fetch 的な URL。静的アセットを除外
  if (/\.(js|css|png|jpg|jpeg|gif|svg|woff2?|ttf|ico|map)(\?|$)/.test(url)) return false;
  if (url.startsWith("data:")) return false;
  if (url.startsWith("blob:")) return false;
  return true;
}
