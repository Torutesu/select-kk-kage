# Pipeline test fixtures

pipeline の pytest が参照する最小 capture bundle 群。

## ポリシー

- **すべてコミットする。** pipeline のテストはネットワーク無し・再現可能に走らせる。
- **最小化する。** フルサイズの bundle は数 MB 行くが、テストに必要なのは HAR + events +
  先頭数行のスナップショットと数枚のスクリーンショット。目標 **500 KB / fixture 以下**。
- **生成は必ず `make_minimal.py` で。** 手作業で切り詰めないこと。切り出しロジックを
  再現可能に残すため。

## 新しい fixture を追加する手順

```bash
# 1. capture で本物を録る
pnpm --filter @kage/capture dev record \
    --url <対象URL> \
    --name <project-slug> \
    --headless \
    --max-duration 15
# => packages/capture/runs/<project-slug>-<ts>.kage.zip

# 2. 最小化して fixture ディレクトリとして置く
cd packages/pipeline
uv run python tests/fixtures/make_minimal.py \
    ../../packages/capture/runs/<project-slug>-<ts>.kage.zip \
    tests/fixtures/<project-slug>-minimal

# 3. pytest で利用されることを確認してコミット
uv run pytest
git add tests/fixtures/<project-slug>-minimal tests/fixtures/make_minimal.py
```

## 現在の fixtures

| name              | source                     | 用途                                        |
| ----------------- | -------------------------- | ------------------------------------------- |
| `hn-minimal/`     | Hacker News top → `newest` | smoke / bundle validation / api_extractor   |
