"""
Component tree orchestrator.

入力: DomNode tree (utils/dom_parse.parse_dom_snapshot の結果)
出力: IR の Component (recursive)

処理順:
  Stage 1 (deterministic classifier) → Stage 3 (pruner) → Stage 2 (LLM, optional)

use_llm=False ならば Stage 2 はスキップし、Stage 1 で Custom のまま残った
ノードは Component.customFallback にフォールバック情報を埋めて保存する。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..ir_schema import Component, ComponentKind, CustomFallback
from .classifier_stage1 import classify_node
from .pruner import prune


if TYPE_CHECKING:
    from ..llm.client import AnthropicClient
    from ..utils.dom_parse import DomNode


def _heading_level(tag: str) -> int | None:
    """h1..h6 → 1..6。"""
    if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
        return int(tag[1])
    return None


def _props_for(node: "DomNode", kind: ComponentKind) -> dict[str, object]:
    """最低限の props をハエ打ちで拾う(Day 4 はベストエフォート)。"""
    props: dict[str, object] = {}
    if kind == "Heading":
        lvl = _heading_level(node.tag_lower)
        if lvl:
            props["level"] = lvl
    if kind == "Link":
        href = node.attributes.get("href")
        if href:
            props["href"] = href
    if kind == "Input":
        t = node.attributes.get("type")
        if t:
            props["type"] = t
        name = node.attributes.get("name")
        if name:
            props["name"] = name
        placeholder = node.attributes.get("placeholder")
        if placeholder:
            props["placeholder"] = placeholder
    if kind == "Image":
        alt = node.attributes.get("alt")
        if alt:
            props["alt"] = alt
    return props


def _src_for(node: "DomNode", kind: ComponentKind) -> str | None:
    if kind in ("Image", "Video"):
        src = node.attributes.get("src")
        if src:
            return src
    return None


def _custom_fallback_for(node: "DomNode") -> CustomFallback | None:
    return CustomFallback(
        tagName=node.tag_lower,
        className=node.class_name or None,
        role=node.role,
    )


def _text_of(node: "DomNode") -> str | None:
    t = (node.text or "").strip()
    if not t:
        # 直下の #text 子要素を拾う
        for c in node.children:
            ct = (c.text or "").strip()
            if ct:
                return ct
        return None
    return t


def _bbox_dict(
    node: "DomNode",
) -> dict[str, float] | None:
    if node.bbox is None:
        return None
    x, y, w, h = node.bbox
    return {"x": x, "y": y, "width": w, "height": h}


def _build_one(
    node: "DomNode",
    parent_kind: ComponentKind,
    viewport_width: float | None,
    *,
    custom_buffer: list[tuple["DomNode", ComponentKind]],
) -> Component:
    kind = classify_node(node, viewport_width=viewport_width)
    is_custom = kind == "Custom"
    text = _text_of(node)
    component = Component(
        id=uuid.uuid4(),
        kind=kind,
        customFallback=_custom_fallback_for(node) if is_custom else None,
        variant=None,
        text=text,
        src=_src_for(node, kind),
        props=_props_for(node, kind),
        bbox=_bbox_dict(node),  # type: ignore[arg-type]
        dataBindingIds=[],
        actionIds=[],
        confidence="high" if not is_custom else "low",
    )
    # Custom なら後で Stage 2 に送るためバッファに積む
    if is_custom:
        custom_buffer.append((node, parent_kind))
    # 子を再帰
    for child in node.children:
        if child.node_type != 1:  # ELEMENT_NODE 以外は skip
            continue
        child_component = _build_one(
            child,
            parent_kind=kind,
            viewport_width=viewport_width,
            custom_buffer=custom_buffer,
        )
        component.children.append(child_component)
    return component


def build_component_tree_sync(
    dom_root: "DomNode",
    *,
    viewport_width: float | None = None,
) -> Component:
    """
    LLM を呼ばない deterministic-only モード。
    Stage 1 → Stage 3 の順で組み立てる。Custom は customFallback 付きで残る。
    """
    pruned = prune(dom_root)
    if pruned is None:
        # 剪定で全消去された場合は最小限のルート
        return Component(id=uuid.uuid4(), kind="Container", confidence="low")
    buffer: list[tuple["DomNode", ComponentKind]] = []
    return _build_one(
        pruned,
        parent_kind="Container",
        viewport_width=viewport_width,
        custom_buffer=buffer,
    )


async def build_component_tree(
    dom_root: "DomNode",
    *,
    viewport_width: float | None = None,
    use_llm: bool = False,
    llm_client: "AnthropicClient | None" = None,
) -> Component:
    """
    非同期 orchestrator。use_llm=True のときのみ Stage 2 を呼ぶ。

    use_llm=True で llm_client 未指定ならランタイムエラー。
    """
    pruned = prune(dom_root)
    if pruned is None:
        return Component(id=uuid.uuid4(), kind="Container", confidence="low")

    custom_buffer: list[tuple["DomNode", ComponentKind]] = []
    root = _build_one(
        pruned,
        parent_kind="Container",
        viewport_width=viewport_width,
        custom_buffer=custom_buffer,
    )
    if not use_llm:
        return root
    if llm_client is None:
        raise ValueError("use_llm=True requires llm_client to be set")

    # Stage 2: Custom ノードを LLM 分類
    from .classifier_stage2 import classify_custom_nodes

    classifications = await classify_custom_nodes(llm_client, custom_buffer)

    # Component ツリーを走査して、同じ DomNode を参照してるコンポーネントに kind を書き戻す
    # 対応づけは buffer 順 = ランダム DFS 順なので、Component 側の order を取り直す必要がある。
    # ここではシンプルに: Component.customFallback が tag=node.tag_lower のものを
    # 先頭から塗りつぶす方式にする(精度より scaffolding 優先)。
    _apply_classifications(root, custom_buffer, classifications)
    return root


def _apply_classifications(
    component: Component,
    custom_buffer: list[tuple["DomNode", ComponentKind]],
    classifications: dict,
) -> None:
    """
    custom_buffer は DFS 順で積んだので、component ツリーを同じ DFS 順で巡回しながら
    Custom → LLM 結果の kind に書き換える。
    """
    buffer_idx = 0

    def walk(c: Component) -> None:
        nonlocal buffer_idx
        if c.kind == "Custom" and buffer_idx < len(custom_buffer):
            item = classifications.get(buffer_idx)
            if item is not None and item.kind != "Custom":
                c.kind = item.kind
                c.customFallback = None
                c.confidence = item.confidence
                c.evidence = item.evidence or None
            buffer_idx += 1
        for ch in c.children:
            walk(ch)

    walk(component)
