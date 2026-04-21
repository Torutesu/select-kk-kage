# KAGE プロンプト管理

KAGE の pipeline は各 extractor / classifier ごとにプロンプトをファイル化して扱う。
本 doc は「プロンプトをどう保存・更新・評価するか」を定めた運用ルール。

## 置き場所

```
packages/pipeline/src/kage_pipeline/llm/prompts/
    <task>_<ver>.md.j2     # Jinja2 テンプレート
    ...
```

例:

- `component_classify_v1.md.j2` — Stage 2 Custom ノード分類
- `entity_infer_v1.md.j2` — Day 4-5 で追加予定

## バージョニング(絶対ルール)

プロンプトは **immutable**。改訂が必要なときは **新バージョン** を作る。

- `component_classify_v1.md.j2` → 破壊的改訂が要るなら `v2` を作る
- v1 ファイルは **消さない**。VCR cassette が v1 の出力で録画されているため、
  消すと過去テストが再現不能になる
- `record_cassettes` tool は最新 prompt でしか録画しない。古い prompt で
  recording 済みの cassette は履歴として保全される

## Jinja2 の制約

- `StrictUndefined` で運用(未定義 variable はエラー)
- ループ・条件分岐のみ使用。マクロは避ける(可読性のため)
- プロンプト本文はテンプレ外に固定情報(`## Allowed kinds`, `## Rules`)を
  まず置き、下に動的な per-item ブロックを続ける。
  → 理由: Anthropic prompt caching の 5 分 TTL を最大化できる

## Tool-use による structured output

すべての分類 / 抽出プロンプトは **Anthropic tool_use モード** で structured
output を強制する。

```python
await client.call_structured(
    model="haiku",
    task="component_classify_v1",
    user_prompt=render("component_classify_v1.md.j2", nodes=payload),
    output_model=ClassifyOutput,
    tool_name="classify_nodes",
    tool_description="...",
)
```

pydantic model をそのまま `tool` の `input_schema` に落とし、戻りを pydantic で
再 validate する。`response_format` パラメータは使わない(Anthropic 0.96.0 推奨)。

## VCR cassette の運用

- `tests/llm/` 配下の LLM テストは **必ず** `@pytest.mark.vcr(<cassette>)` を使う
- cassette が無いとテストは `pytest.skip()` で明確にメッセージを出して落ちる
  (CI / 初期セットアップ時の誤判定を避ける)
- cassette 記録: `ANTHROPIC_API_KEY=... uv run python -m kage_pipeline.tools.record_cassettes`
- record_mode は **`once`** 固定。cassette 有りなら絶対 API を叩かない、
  cassette 無しのみ新規記録

## コスト上限

すべての LLM コールは `CostLogger` 経由。

- `.env` の `KAGE_LLM_COST_LIMIT_USD`(default 1.00 USD)で 1 bundle あたり上限
- 超過した時点で `CostLimitExceeded`(RuntimeError) を投げる
- ログは `./.kage-logs/<project-slug>-<iso>/llm.log.jsonl` に JSONL で追記される

## モデル選択ガイドライン

| Use case | Model alias | 理由 |
|---|---|---|
| 構造抽出 (分類、エンティティ推論) | `haiku` | 数が多い、トークン単価重視 |
| 全体設計 (Screen Graph の高レベル推論) | `sonnet` | 局所より広い文脈が必要 |
| 複雑なデバッグ or 人間の相談 | `opus` | 頻度は低いが深さが要る場合のみ |

`LlmSettings.max_concurrent` で並列度を絞ると rate limit 回避。

## プロンプト作成時のチェックリスト

新しいプロンプトを書くときは以下を満たすこと:

- [ ] ファイル名が `<task>_v<N>.md.j2`
- [ ] `## Allowed ...` セクションで出力 enum / 制約を明示
- [ ] `## Rules` で曖昧ケースのフォールバック方針("unclear なら Custom")を明記
- [ ] 最後に `## Output` で tool 名への誘導
- [ ] 対応する pydantic `OutputModel` が 1 対 1 で存在する
- [ ] `tests/llm/test_<task>_vcr.py` で最小 3 ノードぶんの cassette テスト
- [ ] few-shot を入れる場合はプロンプトの先頭寄り(キャッシュ領域)に固定
