"""
Stage 2: LLM (Haiku) による Custom ノードの分類。

Stage 1 で "Custom" になったノードを 50 件単位でまとめて Haiku に投げ、
tool-use で structured output (classify_nodes tool) を強制して結果を受ける。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, get_args

from pydantic import BaseModel, ConfigDict, Field

from ..ir_schema import ComponentKind, Confidence
from ..llm.client import AnthropicClient
from ..llm.prompts import render


if TYPE_CHECKING:
    from ..utils.dom_parse import DomNode


DEFAULT_BATCH_SIZE = 50
DEFAULT_TEXT_CLIP = 80


# Valid kinds as a Python set for runtime validation in pydantic
_ALL_KINDS: set[str] = set(get_args(ComponentKind))


class ClassifyItem(BaseModel):
    """1 ノードぶんの分類結果。"""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="Index in the submitted nodes list")
    kind: ComponentKind = Field(description="Classified kind")
    confidence: Confidence
    evidence: list[str] = Field(
        default_factory=list, description="1-2 short reasons for the classification"
    )


class ClassifyOutput(BaseModel):
    """tool-use の output。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ClassifyItem]


@dataclass
class NodePayload:
    """LLM に渡す軽量な 1 ノードの表現。"""

    index: int
    tagName: str
    className: str
    role: str
    text: str
    parent_kind: str
    bbox: tuple[float, float, float, float] | None


def _node_to_payload(
    original_index: int,
    node: "DomNode",
    parent_kind: ComponentKind,
    *,
    text_clip: int = DEFAULT_TEXT_CLIP,
) -> NodePayload:
    text = (node.text or "").strip().replace("\n", " ")
    if len(text) > text_clip:
        text = text[:text_clip] + "…"
    return NodePayload(
        index=original_index,
        tagName=node.tag_lower,
        className=node.class_name,
        role=node.role or "",
        text=text,
        parent_kind=parent_kind,
        bbox=node.bbox,
    )


def _chunks(items: list[NodePayload], size: int) -> list[list[NodePayload]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def classify_custom_nodes(
    client: AnthropicClient,
    nodes: list[tuple["DomNode", ComponentKind]],  # (node, parent_kind)
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[int, ClassifyItem]:
    """
    Stage 1 で Custom になった list を受け取り、Haiku に分類を頼む。

    返り値: id(node) → ClassifyItem の dict。
    失敗したバッチは結果に含めない(caller がフォールバックを判断)。
    """
    if not nodes:
        return {}

    payloads = [
        _node_to_payload(i, n, pk) for i, (n, pk) in enumerate(nodes)
    ]
    batches = _chunks(payloads, batch_size)

    async def _run_batch(batch: list[NodePayload]) -> list[ClassifyItem]:
        prompt = render(
            "component_classify_v1.md.j2",
            nodes=[_payload_to_dict(p) for p in batch],
        )
        out = await client.call_structured(
            model="haiku",
            task="component_classify_v1",
            user_prompt=prompt,
            output_model=ClassifyOutput,
            tool_name="classify_nodes",
            tool_description=(
                "Submit classification results for each DOM node. Each item's "
                "`index` field must match the Node index shown in the prompt."
            ),
        )
        # index を "this batch の順序" に解釈してから、caller 側の id にマップし直す
        local_items: list[ClassifyItem] = []
        for item in out.items:
            if 0 <= item.index < len(batch):
                # LLM の index はバッチ内 0..N-1 のはず。呼び出し側の元 index に置き換える。
                remapped = ClassifyItem(
                    index=batch[item.index].index,
                    kind=item.kind,
                    confidence=item.confidence,
                    evidence=item.evidence,
                )
                local_items.append(remapped)
        return local_items

    results: dict[int, ClassifyItem] = {}
    batch_results = await asyncio.gather(
        *(_run_batch(b) for b in batches), return_exceptions=True
    )
    for br in batch_results:
        if isinstance(br, BaseException):
            # バッチ単位で失敗しても他は活かす。ログだけ出して続行。
            continue
        for item in br:
            results[item.index] = item
    return results


def _payload_to_dict(p: NodePayload) -> dict[str, Any]:
    return {
        "tagName": p.tagName,
        "className": p.className,
        "role": p.role,
        "text": p.text,
        "parent_kind": p.parent_kind,
        "bbox": list(p.bbox) if p.bbox else None,
    }


__all__ = [
    "ClassifyItem",
    "ClassifyOutput",
    "classify_custom_nodes",
]


# Runtime guard: ComponentKind の Literal と pydantic model の同期チェック(開発時便利)
if not _ALL_KINDS:  # pragma: no cover — never true, but keeps import side-effect honest
    raise RuntimeError("ComponentKind literal appears empty")
