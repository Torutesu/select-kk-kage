# @kage/ir — Changelog

All notable changes to the IR schema are documented here. The IR is the
single contract between `capture`, `pipeline`, `editor`, `generator`, and
`validator`. Breaking changes require coordinated updates across every
downstream package.

## v1.0.0 — 2026-04-21 (Week 1 Day 3 Freeze)

Runtime schema SHA256: `38d537aa533e92f90393eb47e593d32b984fe11ca3c1968ffe8d2632c4be73b2`

(computed: `shasum -a 256 packages/ir/src/schema.ts`)

### Contract guarantees (v1.x)

- `z.infer<typeof IRSchema>` — TypeScript 型は後方互換
- v1.0.0 時点で valid な `ir.json` は v1.x でも valid
- 新規フィールドは必ず optional
- enum 値は削除・改名しない(追加のみ可)

### Allowed non-breaking changes (ハッシュは変わるがバージョンは据え置き)

- JSDoc / コメントの追加・修正
- タイポ修正(識別子に影響しないもの)
- optional フィールドの追加
- enum 値の追加
- `validateIRIntegrity` の追加チェック

### Breaking changes (v2.0.0 が必要)

- 既存フィールドの削除・型変更
- required フィールドの追加
- enum 値の削除・改名
- ネスト構造の変更

### Initial shape (reference)

- `version: "1.0.0"` literal
- `source`, `projectName`, `designTokens`
- `screens[]`, `transitions[]`, `sharedStates[]`
- `entities[]`, `apiActions[]`, `dataBindings[]`
- `hasAuth`, `openQuestions[]`
- Helper: `validateIRIntegrity(ir) -> string[]`

See `src/schema.ts` for the authoritative definition.
