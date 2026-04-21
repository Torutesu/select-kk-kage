"""
Stage 3: DOM tree の剪定(Stage 2 = LLM に入れる前にトークン節約)。

剪定対象:
  - Tracking pixel: <img width=1 height=1>
  - 空の div / span: text も子も computed_styles も (ほぼ) 無い
  - aria-hidden="true" のノードと、その全子孫
  - style.display == "none" のノード
  - <script> / <style> / <link> / <meta> / <noscript> / <br>
  - コメントノード・非 Element
  - DOCTYPE

剪定後のツリーは元の dom_parse.DomNode の新しい tree (元を破壊しない) を返す。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..utils.dom_parse import ELEMENT_NODE, TEXT_NODE

if TYPE_CHECKING:
    from ..utils.dom_parse import DomNode


# 完全に削除したいタグ(自分と子孫をすべて落とす)
DROP_TAGS: set[str] = {
    "script",
    "style",
    "link",
    "meta",
    "noscript",
    "template",
    "br",
    "title",
    "head",
}


def _is_tracking_pixel(node: "DomNode") -> bool:
    if node.tag_lower != "img":
        return False
    w = node.attributes.get("width", "").strip()
    h = node.attributes.get("height", "").strip()
    return w in {"1", "0"} and h in {"1", "0"}


def _is_empty_wrapper(node: "DomNode") -> bool:
    """子も text も無い div/span はただの wrapper として剪定。"""
    if node.tag_lower not in {"div", "span"}:
        return False
    if node.children:
        return False
    if (node.text or "").strip():
        return False
    return True


def _display_is_none(node: "DomNode") -> bool:
    d = node.computed_styles.get("display", "").strip().lower()
    return d == "none"


def _aria_hidden(node: "DomNode") -> bool:
    v = node.attributes.get("aria-hidden", "").strip().lower()
    return v == "true"


def _should_drop(node: "DomNode") -> bool:
    if node.node_type != ELEMENT_NODE and node.node_type != TEXT_NODE:
        # comment, doctype 等は落とす
        return True
    if node.node_type == ELEMENT_NODE:
        if node.tag_lower in DROP_TAGS:
            return True
        if _aria_hidden(node):
            return True
        if _display_is_none(node):
            return True
        if _is_tracking_pixel(node):
            return True
    if node.node_type == TEXT_NODE and not (node.text or "").strip():
        return True
    return False


def _clone(node: "DomNode") -> "DomNode":
    """parent / children なしで DomNode をコピー。木を作り直すため。"""
    from dataclasses import replace

    return replace(node, parent=None, children=[])


def prune(root: "DomNode") -> "DomNode | None":
    """
    剪定後のツリーを返す。完全に消える場合 None。
    単一子の wrapper div/span は子を引き上げて折りたたむ(flatten)。
    """
    if _should_drop(root):
        return None

    new_root = _clone(root)
    for child in root.children:
        pruned = prune(child)
        if pruned is None:
            continue
        new_root.children.append(pruned)
        pruned.parent = new_root

    # 空 wrapper が残ってたら最終チェック
    if _is_empty_wrapper(new_root):
        return None

    # 1 子だけの意味のない wrapper を flatten
    # (ただしルート自身は flatten しない)
    if (
        new_root.tag_lower in {"div", "span"}
        and not new_root.class_name
        and not new_root.role
        and not new_root.text
        and len(new_root.children) == 1
    ):
        only = new_root.children[0]
        only.parent = None
        return only

    return new_root
