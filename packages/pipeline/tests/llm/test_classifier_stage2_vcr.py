"""
Stage 2 (Haiku) classifier の LLM コールを VCR で固定するテスト。

cassette 無いときは分かりやすいメッセージで skip する。
cassette 作成は `uv run python -m kage_pipeline.tools.record_cassettes`。
"""

from __future__ import annotations

import os

import pytest

from kage_pipeline.components.classifier_stage2 import classify_custom_nodes
from kage_pipeline.llm.client import AnthropicClient, LlmSettings
from kage_pipeline.llm.cost_logger import CostLogger
from kage_pipeline.utils.dom_parse import ELEMENT_NODE, DomNode

from .conftest import require_cassette_or_skip


CASSETTE_NAME = "stage2_classify_basic.yaml"


def _node(tag: str, *, class_: str = "", role: str = "", text: str = "") -> DomNode:
    attrs: dict[str, str] = {}
    if class_:
        attrs["class"] = class_
    if role:
        attrs["role"] = role
    return DomNode(
        index=0,
        node_type=ELEMENT_NODE,
        tag_name=tag.upper(),
        attributes=attrs,
        text=text,
    )


@pytest.mark.vcr(CASSETTE_NAME)
async def test_stage2_classifies_custom_nodes(tmp_path) -> None:
    # cassette 不在なら分かりやすく skip(API key 未設定時も safe)
    require_cassette_or_skip(CASSETTE_NAME)

    # cassette 記録モードでは API key が必須。再生モードでは不要。
    if not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "test-recording-placeholder"

    cost_log = tmp_path / "llm.log.jsonl"
    logger = CostLogger(cost_log, limit_usd=0.10)
    client = AnthropicClient(cost_logger=logger, settings=LlmSettings(max_concurrent=2))

    nodes = [
        (_node("div", class_="modal-root", role="dialog"), "Container"),
        (_node("a", class_="storylink", text="Some title"), "Container"),
        (_node("span", class_="subline", text="by user 2h ago"), "Container"),
    ]

    result = await classify_custom_nodes(client, nodes, batch_size=10)

    # 3 ノードぶんの分類が返ってくる(kind は allowed 集合の一要素)
    assert len(result) == 3
    for idx, item in result.items():
        assert 0 <= idx < 3
        assert item.kind  # 何らかの kind が入っていること
        assert item.confidence in ("high", "medium", "low")

    # cost log にエントリが 1 行以上書かれる
    log_text = cost_log.read_text(encoding="utf-8")
    assert log_text.count("\n") >= 1
