"""
HN fixture 上で entity_inferer を動かす。apiActions=0 なので entities=0 が期待値、
ただし crash しないこと + LLM 呼び出し発生しないことを保証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kage_pipeline.bundle import load_bundle
from kage_pipeline.components.entity_inferer import infer_entities
from kage_pipeline.ir_builder import build_ir


class _ShouldNotBeCalled:
    """LLM が呼ばれたら即失敗するスパイ。"""

    async def call_structured(self, **kwargs: object) -> object:
        raise AssertionError(
            f"LLM client was called unexpectedly for HN fixture (task={kwargs.get('task')!r})"
        )


@pytest.mark.asyncio
async def test_hn_no_apis_no_llm_no_crash(hn_minimal_dir: Path) -> None:
    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")
    # HN は JSON API を持たないので apiActions は 0 件
    assert ir.apiActions == []

    entities, updated = await infer_entities(
        api_actions=ir.apiActions,
        screens=ir.screens,
        has_auth=ir.hasAuth,
        llm_client=_ShouldNotBeCalled(),  # type: ignore[arg-type]
    )
    assert entities == []
    assert updated == []
