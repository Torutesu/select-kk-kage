# KAGE IR Spec

**Status**: Draft, locks at Week 1 Day 3
**Version**: 1.0.0
**SSOT**: `packages/ir/src/schema.ts` (Zod)

## 設計原則

### 1. 「推測」と「観測」を分離する

IR は Vision LLM による推測と、DOM/HAR からの観測の混在物。
すべての主要ノードに `confidence: "high" | "medium" | "low"` を持たせる。

- `high`: DOM/HAR から直接観測できた事実
- `medium`: 観測 + LLM推論で高確度
- `low`: LLM推論のみ、人間レビュー必須

Editor では `low` の項目を赤く表示する。

### 2. 参照は ID ベース

Component / Screen / Entity などはすべて UUID を持つ。
参照は ID(文字列)で行う。ネスト構造にしない。
理由: IR Editor で部分編集・並び替えが安全にできる。

### 3. Screen Graph は一級市民

既存ツール(v0等)との最大の差別化ポイント。
`screens + transitions + sharedStates` の 3 点セットで表現する。
XState のステートチャートに直接マップできる構造にする。

### 4. Backend は「仮説」として扱う

HAR で観測した API は事実として保持するが、
そこから推測した DB エンティティは `Entity.confidence` + `questions` フィールドで
「人間に確認したいこと」を明示する。

### 5. 生成スタックに最適化

Component の `kind` は shadcn/ui のコンポーネント名に寄せる。
これにより Generator 側が「kind → import + JSX」の単純マッピングで済む。

## トップレベル構造

```ts
IR = {
  version: "1.0.0",
  source: {targetUrl, recordedAt, durationSeconds, captureTool},
  projectName,
  designTokens: {colors, fontFamilies, fontSizes, spacing, borderRadius},
  screens: Screen[],          // 画面一覧
  transitions: Transition[],  // 画面遷移
  sharedStates: SharedState[],// 画面を跨ぐ状態
  entities: Entity[],         // 推測された DB テーブル
  apiActions: ApiAction[],    // 観測された API
  dataBindings: DataBinding[],// UI と API の結び
  hasAuth: boolean,
  openQuestions: [],          // LLM から人間への質問
}
```

## なぜこう分割したか

| レイヤ | 役割 | 情報源 | 誰が最終確定 |
|---|---|---|---|
| Screen / Component | 何が画面に出るか | DOM + Vision | 人間 |
| Transition | 画面の繋がり | events + HAR | 人間(低精度箇所のみ) |
| SharedState | 画面を跨ぐ状態 | LLM推論 | 人間必須 |
| Entity | DB スキーマ | HAR + LLM | 人間必須 |
| ApiAction | API仕様 | HAR | 自動確定可 |
| DataBinding | UI と data の結び | Vision + HAR | 自動確定可 |

**人間に確認すべき箇所を最小化**しつつ、
**確認が必要な箇所は確実に確認する**構造にしている。

## 整合性ルール(スキーマ外)

`validateIRIntegrity(ir)` で以下をチェック:

1. `transition.from / to` が存在する Screen.id
2. `transition.actionIds` が存在する ApiAction.id
3. `dataBinding.apiActionId` が存在する ApiAction.id
4. `screen.initialDataBindingIds` が存在する DataBinding.id
5. `apiAction.entityIds` が存在する Entity.id
6. `component.dataBindingIds / actionIds` が存在する ID

違反があれば Generator は実行させない。Editor で修正させる。

## 拡張方針

Week 1 Day 3 以降:
- **追加**: 新しいオプショナルフィールド、新しい enum 値 → OK
- **破壊的変更**: `version` を上げる + 全パッケージのマイグレーション → RFC必須

## サンプル

最小構成のサンプル IR は `docs/examples/minimal-ir.json` を参照。
