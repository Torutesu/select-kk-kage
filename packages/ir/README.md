# @kage/ir

KAGE Intermediate Representation — the single contract shared by
`capture`, `pipeline`, `editor`, `generator`, and `validator`.

## Status: FROZEN (v1.0.0, 2026-04-21)

Week 1 Day 3 以降、**破壊的変更は禁止**。拡張は「optional フィールド追加」
と「enum 値追加」のみ許可。

詳細な運用ルールは [`CHANGELOG.md`](./CHANGELOG.md) を参照。

### Why this is frozen

IR スキーマは KAGE の全パイプラインの土台。
pipeline / editor / generator / validator がすべて同じ構造を前提にしている。
ここを破壊的に変えると 4 パッケージ同時改修になり、Week 2 のスプリントが崩壊する。

### Non-breaking changes (PR で OK)

- JSDoc / コメント
- タイポ修正
- optional フィールドの追加
- enum 値の追加
- `validateIRIntegrity` のチェック追加

### Breaking changes (v2.0.0 RFC 必須)

- フィールドの削除・型変更
- required フィールド追加
- enum 値の削除・改名
- ネスト構造の変更

変更したい場合は `docs/rfcs/YYYY-MM-DD-ir-v2.md` を先に書くこと。

## Schema entry point

```ts
import { IRSchema, validateIRIntegrity } from "@kage/ir";

const ir = IRSchema.parse(json); // zod で runtime 検証
const issues = validateIRIntegrity(ir); // ID 参照整合性等
```

## Python 側

`packages/pipeline/src/kage_pipeline/ir_schema.py` に pydantic モデルを
ミラーで持っている。TS と Python は同じ shape を満たす義務を負う。
TS を変えたら Python 側も必ず追従すること。
