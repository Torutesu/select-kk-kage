# @kage/pipeline

KAGE Pipeline — converts a capture bundle (`<name>.kage.zip`) into an IR JSON
(`packages/ir` schema, v1.0.0).

## Run

```bash
cd packages/pipeline
uv sync                                   # setup venv + install deps
uv run python -m kage_pipeline <path/to/bundle.kage.zip> \
    --out ir.json \
    --project-name <slug>
```

出力は `packages/ir` の `IRSchema` に準拠した JSON。TS 側で `IRSchema.parse()`
が通る形であることが最低保証。

## Current capability (Day 3-4)

- [x] Bundle (zip) 展開 + 7 要素存在チェック
- [x] HAR → `ApiAction[]` (deterministic, heuristic な urlPattern)
- [x] Events → `Screen[]` (URL 単位でグルーピング、最小 Component tree)
- [ ] DOM snapshot → Component tree (Day 4)
- [ ] Vision LLM → Entity 推論 (Day 4-5)
- [ ] Events → Transition (Day 5)

## Testing

```bash
uv run pytest
```

Fixture: `tests/fixtures/hn-minimal/` (HN スモーク録画の最小化版、
`tests/fixtures/make_minimal.py` で生成)。
