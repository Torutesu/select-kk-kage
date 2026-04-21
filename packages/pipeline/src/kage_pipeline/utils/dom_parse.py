"""
CDP DOMSnapshot (flattened) → 木構造の DomNode に変換する。

入力フォーマット(Chrome DevTools Protocol 準拠):
{
  "documents": [{
    "nodes": {
      "parentIndex": [int],         # -1 = root, それ以外は index
      "nodeType": [int],            # 1=Element, 3=Text, 9=Document ...
      "nodeName": [strIdx],         # tagName、#text、#document など
      "nodeValue": [strIdx],        # text content (非 Element)
      "backendNodeId": [int],
      "attributes": [[strIdx, strIdx, ...]],   # 2 つずつで name/value の組
      "textValue": {"index":[int], "value":[strIdx]},   # sparse
      "isClickable": {"index":[int]},
      ...
    },
    "layout": {
      "nodeIndex": [int],           # どの nodes index に対応
      "bounds": [[x,y,w,h]],
      "styles": [[strIdx,...]],     # computedStyles = recorder で指定した順
      "text": [strIdx],
    }
  }],
  "strings": [str]
}

nodeType (W3C 準拠):
  1 = ELEMENT, 3 = TEXT, 8 = COMMENT, 9 = DOCUMENT, 10 = DOCTYPE, 11 = DOCUMENT_FRAGMENT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ELEMENT_NODE = 1
TEXT_NODE = 3
DOCUMENT_NODE = 9


@dataclass
class DomNode:
    """DOMSnapshot の 1 ノードを表す木。"""

    index: int
    node_type: int
    tag_name: str  # "HTML", "DIV", "#text", "#document" など
    attributes: dict[str, str] = field(default_factory=dict)
    text: str = ""
    computed_styles: dict[str, str] = field(default_factory=dict)
    bbox: tuple[float, float, float, float] | None = None  # (x, y, w, h)
    is_clickable: bool = False
    parent: "DomNode | None" = None
    children: list["DomNode"] = field(default_factory=list)

    @property
    def role(self) -> str | None:
        """aria role 属性。"""
        return self.attributes.get("role")

    @property
    def class_name(self) -> str:
        return self.attributes.get("class", "")

    @property
    def tag_lower(self) -> str:
        return self.tag_name.lower()

    def walk(self) -> "list[DomNode]":
        """自分と子孫を DFS で列挙(自分が先頭)。"""
        out: list[DomNode] = [self]
        for c in self.children:
            out.extend(c.walk())
        return out

    def __repr__(self) -> str:  # デバッグ用
        head = f"<{self.tag_lower}"
        if "id" in self.attributes:
            head += f"#{self.attributes['id']}"
        if self.class_name:
            head += f".{self.class_name.split()[0]}"
        head += ">"
        return f"DomNode({head}, children={len(self.children)})"


class DomParseError(Exception):
    """DOMSnapshot の構造が想定外のとき。"""


def _str_lookup(strings: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(strings):
        return ""
    return strings[idx]


def _sparse_lookup(sparse: dict[str, Any] | None, node_index: int) -> int | None:
    """CDP の sparse array を1ノードぶん引く。"""
    if not sparse:
        return None
    indices = sparse.get("index") or []
    values = sparse.get("value") or []
    try:
        pos = indices.index(node_index)
    except ValueError:
        return None
    if pos >= len(values):
        return None
    v = values[pos]
    return int(v) if isinstance(v, int) else v


def _sparse_flag(sparse: dict[str, Any] | None, node_index: int) -> bool:
    if not sparse:
        return False
    indices = sparse.get("index") or []
    return node_index in indices


def parse_dom_snapshot(
    snapshot: dict[str, Any],
    *,
    computed_style_keys: list[str] | None = None,
) -> DomNode | None:
    """
    CDP DOMSnapshot オブジェクト 1 件を DomNode tree に変換する。
    最初の Document (documents[0]) のみ対象。iframe の子ドキュメントは今日は扱わない。

    戻り値は DOCUMENT_NODE ではなく、最初に見つかった HTML (Element) ノードを
    ツリーのルートとして返す。<html> が無ければ documents[0] の最初の Element 子を返す。
    Element が 1 つも無ければ None。

    computed_style_keys: snapshot 取得時に指定した recorder.ts の順番と揃える必要あり。
        Default は recorder.ts で指定している:
        ["background-color", "color", "font-size", "font-family",
         "padding", "margin", "border-radius", "display", "flex-direction"]
    """
    documents = snapshot.get("documents") or []
    strings = snapshot.get("strings") or []
    if not documents:
        raise DomParseError("snapshot has no documents")

    doc = documents[0]
    nodes = doc.get("nodes") or {}
    layout = doc.get("layout") or {}

    parent_index = nodes.get("parentIndex") or []
    node_type = nodes.get("nodeType") or []
    node_name = nodes.get("nodeName") or []
    node_value = nodes.get("nodeValue") or []
    attributes_arr = nodes.get("attributes") or []
    text_value = nodes.get("textValue") or {}
    input_value = nodes.get("inputValue") or {}
    is_clickable = nodes.get("isClickable") or {}

    n = len(parent_index)
    if not (len(node_type) == n == len(node_name)):
        raise DomParseError("nodes arrays length mismatch")

    # layout を node_index -> index_in_layout に変換
    layout_node_index = layout.get("nodeIndex") or []
    layout_bounds = layout.get("bounds") or []
    layout_styles = layout.get("styles") or []
    layout_text = layout.get("text") or []
    layout_of: dict[int, int] = {ni: i for i, ni in enumerate(layout_node_index)}

    style_keys = computed_style_keys or [
        "background-color",
        "color",
        "font-size",
        "font-family",
        "padding",
        "margin",
        "border-radius",
        "display",
        "flex-direction",
    ]

    all_nodes: list[DomNode] = []
    for i in range(n):
        tag = _str_lookup(strings, node_name[i]) if i < len(node_name) else ""
        node = DomNode(
            index=i,
            node_type=int(node_type[i]) if i < len(node_type) else 0,
            tag_name=tag,
        )
        # attributes: [name0, value0, name1, value1, ...]
        if i < len(attributes_arr):
            attrs = attributes_arr[i] or []
            for a in range(0, len(attrs) - 1, 2):
                name = _str_lookup(strings, attrs[a])
                value = _str_lookup(strings, attrs[a + 1])
                if name:
                    node.attributes[name] = value

        # text: Element なら layout.text、#text なら nodeValue
        if node.node_type == TEXT_NODE and i < len(node_value) and node_value[i] >= 0:
            node.text = _str_lookup(strings, node_value[i])
        else:
            # <input> 等の textValue
            tv_idx = _sparse_lookup(text_value, i)
            if isinstance(tv_idx, int) and tv_idx >= 0:
                node.text = _str_lookup(strings, tv_idx)
            # <input> の inputValue
            iv_idx = _sparse_lookup(input_value, i)
            if isinstance(iv_idx, int) and iv_idx >= 0 and not node.text:
                node.text = _str_lookup(strings, iv_idx)

        # layout (bbox + computedStyles) — あれば
        pos = layout_of.get(i)
        if pos is not None:
            if pos < len(layout_bounds):
                b = layout_bounds[pos]
                if isinstance(b, list) and len(b) == 4:
                    node.bbox = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            if pos < len(layout_styles):
                styles = layout_styles[pos] or []
                for k, v_idx in zip(style_keys, styles, strict=False):
                    v = _str_lookup(strings, v_idx) if isinstance(v_idx, int) else ""
                    if v:
                        node.computed_styles[k] = v
            if pos < len(layout_text):
                t_idx = layout_text[pos]
                if isinstance(t_idx, int) and t_idx >= 0 and not node.text:
                    node.text = _str_lookup(strings, t_idx)

        node.is_clickable = _sparse_flag(is_clickable, i)
        all_nodes.append(node)

    # Parent linking
    for i in range(n):
        pi = parent_index[i]
        if pi is not None and pi >= 0 and pi < n:
            parent = all_nodes[pi]
            child = all_nodes[i]
            child.parent = parent
            parent.children.append(child)

    # Root: 最初の <html> か、document の最初の Element 子
    html_root = next(
        (
            node
            for node in all_nodes
            if node.node_type == ELEMENT_NODE and node.tag_lower == "html"
        ),
        None,
    )
    if html_root is not None:
        return html_root
    # document の子で最初の Element
    doc_node = next(
        (node for node in all_nodes if node.node_type == DOCUMENT_NODE),
        None,
    )
    if doc_node is not None:
        for child in doc_node.children:
            if child.node_type == ELEMENT_NODE:
                return child
    # フォールバック: Element node の先頭
    return next(
        (node for node in all_nodes if node.node_type == ELEMENT_NODE),
        None,
    )
