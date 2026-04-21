# KAGE — Claude Code 開発指示書

## プロジェクト概要

**KAGE**(影) は Select KK の SLCT 事業部向け内部ツール。
Web SaaS の画面操作を録画し、Next.js プロジェクトのスケルトンを自動生成する。
**外販しない。SLCT 案件の MVP 開発を 2 週間 → 10 日に短縮するのが目的。**

### コアコンセプト

```
画面録画 + DOM + A11y tree + Network (HAR)
  ↓
IR (Intermediate Representation) = Component Tree + Screen Graph + Backend仮説
  ↓
人間がIRをレビュー・修正 (Human-in-the-loop)
  ↓
Next.js + shadcn/ui + tRPC + Prisma プロジェクト自動生成
  ↓
Playwright で元操作を再生して検証ループ
```

### なぜ作るのか

v0 / Lovable / bolt などの既存ツールは **単一画面・浅い階層** しか扱えない。
実プロダクト開発では、画面遷移・状態共有・認証・データフロー・バックエンドとの整合が必要で、
それを人間が毎回手配線するのが MVP 開発コストの大半。

KAGE は **動画 + DOM + HAR を入力** にすることで配線情報そのものを取り込み、
Screen Graph として一級市民で扱う。

## 技術スタック(固定)

### KAGE 自体

| 層 | 技術 |
|---|---|
| Capture | Playwright + CDP (Chrome DevTools Protocol) |
| Pipeline | Python 3.12 + uv |
| IR | TypeScript + Zod |
| Editor | Next.js 15 (App Router) |
| Generator | TypeScript + Anthropic SDK (Claude Sonnet 4.5 + Haiku) |
| Validator | Playwright |
| Monorepo | pnpm workspaces + turbo |

### 生成されるプロジェクト

| 層 | 技術 |
|---|---|
| Framework | Next.js 15 (App Router) |
| Language | TypeScript strict |
| Styling | Tailwind + shadcn/ui |
| API | tRPC v11 |
| DB | Prisma + Supabase (Postgres) |
| Auth | Supabase Auth |
| Client State | Zustand |
| Server State | TanStack Query (via tRPC) |
| Tests | Playwright (生成時に元録画から自動生成) |

**スタック固定は絶対。案件ごとに変えない。**
生成テンプレ・プロンプト・検証スイートを使い回すことが KAGE の精度の源泉。
カスタマイズは生成後に人間が手作業で行う。

## ディレクトリ構造

```
kage/
├── CLAUDE.md                    # このファイル
├── README.md
├── package.json                 # pnpm workspaces root
├── turbo.json
├── packages/
│   ├── capture/                 # Playwright + CDP でキャプチャ
│   ├── ir/                      # IR スキーマ定義(全パッケージから参照)
│   ├── pipeline/                # Capture → IR 変換(Python)
│   ├── editor/                  # IR 可視化・編集 Web UI
│   ├── generator/               # IR → Next.js プロジェクト生成
│   └── validator/               # 生成物の検証
└── docs/
    ├── ARCHITECTURE.md
    ├── IR_SPEC.md
    └── PROMPTS.md
```

## 開発ルール

### 1. IR を絶対に変えるな(Week 1 Day 3 以降)

IR スキーマは `packages/ir/src/schema.ts` が Single Source of Truth。
Day 3 までに固定し、以降は **追加のみ許可、破壊的変更は全体レビュー必須**。
理由: pipeline / editor / generator / validator 全部が IR に依存する。

### 2. 生成プロジェクトのスタックを変えるな

「今回は Remix で」「今回は Drizzle で」を許すと破綻する。
生成スタックは上記に固定のものだけ。

### 3. Human-in-the-loop を前提にする

完全自動を目指さない。IR Editor で人間が介入する前提で設計する。
「LLM の誤認識を上流で潰す」ほうが、下流での修正より圧倒的に安い。

### 4. コスト管理

Vision LLM のコールは高い。以下を徹底:
- キーフレーム抽出 (pixel diff threshold) で画像数を 1/10 に削減
- 可能な限り DOM/A11y tree のテキスト情報で済ませる
- コンポーネント生成は Claude Haiku で並列化、全体構造のみ Sonnet

### 5. ログ・観測性

pipeline の各ステップで中間成果物を `./runs/<run_id>/` に全部保存する。
デバッグ時に IR 生成をやり直せるようにする。

### 6. テスト

- `packages/ir`: スキーマ validation のユニットテスト必須
- `packages/generator`: ゴールデンテスト(IR サンプル → 生成物の snapshot)
- `packages/validator`: E2E は実録画サンプルで回す

## コーディング規約

### TypeScript
- `strict: true`
- `noUncheckedIndexedAccess: true`
- Zod でランタイム検証、型は `z.infer` で派生

### Python (pipeline)
- Python 3.12+
- `uv` でパッケージ管理
- 型ヒント必須、`mypy --strict`
- 非同期は `asyncio`、LLM コールは並列化

### Git
- ブランチ: `feat/xxx`, `fix/xxx`, `chore/xxx`
- Commit: Conventional Commits
- PR は Small に保つ、大きい変更は RFC を docs/ に置いてから

## 2 週間スプリント

### Week 1: Capture + IR 生成

- Day 1-2: capture パッケージ (Playwright + CDP)
- Day 3-4: IR スキーマ確定 + pipeline 骨格
- Day 5-7: IR Editor (Next.js)

### Week 2: Generator + Validator

- Day 8-10: Generator (IR → Next.js project)
- Day 11-12: Validator (Playwright replay + 自動修正ループ)
- Day 13-14: E2E 検証 (実 SaaS を録画 → 生成 → 検証)

## 用語集

- **IR** (Intermediate Representation): 中間表現。KAGE のすべての処理の中心。
- **Screen Graph**: 画面間の遷移を表す有向グラフ。XState のステートチャート相当。
- **Component Tree**: 1 画面内のコンポーネント階層。
- **Backend Inference**: HAR + UI から DB スキーマ + API を逆算した「仮説」。

## 対象外 (やらないこと)

- 外販・SaaS 化
- Desktop アプリのキャプチャ (SHOGUN でやる別案件)
- モバイルアプリのキャプチャ
- 生成プロジェクトのデプロイ機能(人間がやる)
- リアルタイム協業(単独使用前提)

## 連絡先

Select (@select) — Select KK 代表
