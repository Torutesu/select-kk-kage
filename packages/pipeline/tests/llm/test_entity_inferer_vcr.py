"""
Entity 推論の LLM コールを VCR で固定するテスト scaffold。

cassette 無いときは graceful skip。cassette 記録は
  ANTHROPIC_API_KEY=sk-ant-... uv run python -m kage_pipeline.tools.record_cassettes
"""

from __future__ import annotations

import os
import uuid

import pytest

from kage_pipeline.components.entity_inferer import infer_entities
from kage_pipeline.ir_schema import ApiAction, ApiActionObserved
from kage_pipeline.llm.client import AnthropicClient, LlmSettings
from kage_pipeline.llm.cost_logger import CostLogger

from .conftest import require_cassette_or_skip


CASSETTE_NAME = "entity_infer_basic.yaml"


def _api(
    name: str, method: str, url_pattern: str, sample: object | None = None
) -> ApiAction:
    return ApiAction(
        id=uuid.uuid4(),
        name=name,
        kind="query" if method == "GET" else "mutation",
        observed=ApiActionObserved(
            method=method,  # type: ignore[arg-type]
            urlPattern=url_pattern,
            sampleResponse=sample,
        ),
        entityIds=[],
        confidence="medium",
    )


@pytest.mark.vcr(CASSETTE_NAME)
async def test_entity_inferer_returns_proposals(tmp_path) -> None:
    require_cassette_or_skip(CASSETTE_NAME)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "test-recording-placeholder"

    cost_log = tmp_path / "llm.log.jsonl"
    logger = CostLogger(cost_log, limit_usd=0.25)
    client = AnthropicClient(cost_logger=logger, settings=LlmSettings(max_concurrent=2))

    actions = [
        _api(
            "users.list",
            "GET",
            "/api/users",
            [{"id": 1, "email": "a@b.c", "name": "Alice", "createdAt": "2026-01-01T00:00:00Z"}],
        ),
        _api(
            "users.get",
            "GET",
            "/api/users/:id",
            {"id": 1, "email": "a@b.c", "name": "Alice", "createdAt": "2026-01-01T00:00:00Z"},
        ),
    ]

    entities, updated = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=True,
        llm_client=client,
    )

    # 最小保証: 1 entity、id field が先頭、apiActions が entityIds を持つ
    assert len(entities) == 1
    e = entities[0]
    assert e.fields[0].isId is True
    assert len(e.fields) >= 2
    for a in updated:
        assert a.entityIds == [str(e.id)]
