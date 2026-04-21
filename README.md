# KAGE

> Record a SaaS. Get a scaffold.

**KAGE (影)** is Select KK / SLCT's internal tool for accelerating MVP delivery.

Record a web SaaS session → get a Next.js + shadcn/ui + tRPC + Prisma project scaffold
with multi-screen routing, shared state, and inferred backend schema already wired up.

**This is an internal tool. Not for external distribution.**

## Why

Existing tools (v0, Lovable, bolt) work on a single screenshot. Real products have
many screens, shared state, auth flows, and API contracts. That wiring is where
MVP cost lives — and what KAGE automates by capturing **video + DOM + A11y + HAR**
and producing a Screen Graph as a first-class primitive.

## Architecture

```
Web SaaS recording
  ├── recording.webm          (Playwright video)
  ├── network.har             (all requests)
  ├── dom_snapshots.jsonl     (CDP DOMSnapshot at each event)
  ├── a11y_snapshots.jsonl    (CDP Accessibility.getFullAXTree)
  └── events.jsonl            (clicks, submits, inputs)
        ↓
  @kage/pipeline (Python)
    Component Tree / Screen Graph / Backend Inference
        ↓
  IR (ir.json, validated by @kage/ir Zod schema)
        ↓
  @kage/editor (Next.js web UI)
    Human reviews & edits IR
        ↓
  @kage/generator
    IR → Next.js + shadcn/ui + tRPC + Prisma project
        ↓
  @kage/validator
    Playwright replays original events against generated project
    Auto-repair loop (max 3 iterations) using Claude
        ↓
  Ready-to-edit SLCT project seed
```

## Stack (fixed, non-negotiable)

### KAGE itself
- TypeScript (Node 20+), Python 3.12, pnpm workspaces, turbo
- Playwright + CDP for capture
- Claude Sonnet 4.5 (main) + Haiku (parallel components) via Anthropic SDK
- Zod for IR validation

### Generated projects
- Next.js 15 App Router, TypeScript strict
- Tailwind + shadcn/ui
- tRPC v11
- Prisma + Supabase (Postgres + Auth)
- Zustand (client state) + TanStack Query (server state)

Stack is fixed to maximize template reuse and generation accuracy. Per-project
customization happens after generation.

## Quick Start

```bash
pnpm install

# 1. Record
pnpm --filter @kage/capture dev record \
  --url https://linear.app \
  --name linear-clone

# 2. Pipeline (Python, produces ir.json)
cd packages/pipeline
uv run python -m kage_pipeline ../../runs/linear-clone-*.kage.zip

# 3. Review / edit IR
pnpm --filter @kage/editor dev
# open http://localhost:3000

# 4. Generate
pnpm --filter @kage/generator dev ../../runs/linear-clone-*.ir.json

# 5. Validate
pnpm --filter @kage/validator dev
```

## 2-week sprint

See `CLAUDE.md` for the full sprint plan and development rules.

**Week 1**: capture + IR schema + pipeline skeleton + editor
**Week 2**: generator + validator + end-to-end test

## License

Proprietary — Select KK internal use only. Do not distribute.
