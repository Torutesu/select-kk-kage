"""DOMSnapshot flat → DomNode tree 変換のユニットテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kage_pipeline.utils.dom_parse import (
    DOCUMENT_NODE,
    ELEMENT_NODE,
    TEXT_NODE,
    DomNode,
    parse_dom_snapshot,
)


def _stringify(strings: list[str], s: str) -> int:
    if s not in strings:
        strings.append(s)
    return strings.index(s)


def _build_snapshot(*nodes: dict) -> dict:
    """
    簡易ビルダ: ノードの list を受け取って DOMSnapshot の dict を返す。
    各 node dict は {parent, type, name, attrs?, text?, bbox?, styles?} を持つ。
    name はタグ名 ("DIV") または "#text" / "#document"。
    """
    strings: list[str] = []
    parent_index: list[int] = []
    node_type: list[int] = []
    node_name: list[int] = []
    node_value: list[int] = []
    attributes_arr: list[list[int]] = []
    layout_node_index: list[int] = []
    layout_bounds: list[list[float]] = []
    layout_styles: list[list[int]] = []
    layout_text: list[int] = []

    for i, n in enumerate(nodes):
        parent_index.append(n.get("parent", -1))
        node_type.append(n["type"])
        node_name.append(_stringify(strings, n["name"]))
        nv = n.get("node_value")
        node_value.append(_stringify(strings, nv) if nv is not None else -1)
        attrs = n.get("attrs", {})
        arr: list[int] = []
        for k, v in attrs.items():
            arr.append(_stringify(strings, k))
            arr.append(_stringify(strings, v))
        attributes_arr.append(arr)
        if "bbox" in n or "styles" in n or "text" in n:
            layout_node_index.append(i)
            b = n.get("bbox") or [0.0, 0.0, 0.0, 0.0]
            layout_bounds.append(list(b))
            styles_dict = n.get("styles") or {}
            style_order = [
                "background-color", "color", "font-size", "font-family",
                "padding", "margin", "border-radius", "display", "flex-direction",
            ]
            layout_styles.append([
                _stringify(strings, styles_dict[k]) if k in styles_dict else -1
                for k in style_order
            ])
            layout_text.append(_stringify(strings, n["text"]) if "text" in n else -1)

    return {
        "strings": strings,
        "documents": [
            {
                "nodes": {
                    "parentIndex": parent_index,
                    "nodeType": node_type,
                    "nodeName": node_name,
                    "nodeValue": node_value,
                    "attributes": attributes_arr,
                    "textValue": {"index": [], "value": []},
                    "inputValue": {"index": [], "value": []},
                    "isClickable": {"index": []},
                },
                "layout": {
                    "nodeIndex": layout_node_index,
                    "bounds": layout_bounds,
                    "styles": layout_styles,
                    "text": layout_text,
                },
            }
        ],
    }


def test_empty_document_returns_none() -> None:
    snap = _build_snapshot(
        {"parent": -1, "type": DOCUMENT_NODE, "name": "#document"},
    )
    assert parse_dom_snapshot(snap) is None


def test_html_root_returned() -> None:
    snap = _build_snapshot(
        {"parent": -1, "type": DOCUMENT_NODE, "name": "#document"},
        {"parent": 0, "type": ELEMENT_NODE, "name": "HTML"},
    )
    root = parse_dom_snapshot(snap)
    assert isinstance(root, DomNode)
    assert root.tag_lower == "html"


def test_tree_building_and_attrs() -> None:
    snap = _build_snapshot(
        {"parent": -1, "type": DOCUMENT_NODE, "name": "#document"},
        {"parent": 0, "type": ELEMENT_NODE, "name": "HTML"},
        {"parent": 1, "type": ELEMENT_NODE, "name": "BODY"},
        {"parent": 2, "type": ELEMENT_NODE, "name": "DIV",
         "attrs": {"id": "main", "class": "wrapper"}},
        {"parent": 3, "type": ELEMENT_NODE, "name": "BUTTON",
         "attrs": {"role": "button", "class": "btn btn-primary"}},
        {"parent": 4, "type": TEXT_NODE, "name": "#text", "node_value": "Click me"},
    )
    root = parse_dom_snapshot(snap)
    assert root is not None
    assert root.tag_lower == "html"
    body = root.children[0]
    assert body.tag_lower == "body"
    div = body.children[0]
    assert div.attributes["id"] == "main"
    assert div.class_name == "wrapper"
    button = div.children[0]
    assert button.role == "button"
    assert button.class_name == "btn btn-primary"
    text = button.children[0]
    assert text.text == "Click me"
    # walk: html → body → div → button → text の 5 ノード
    assert len(root.walk()) == 5


def test_layout_bbox_and_computed_styles() -> None:
    snap = _build_snapshot(
        {"parent": -1, "type": DOCUMENT_NODE, "name": "#document"},
        {"parent": 0, "type": ELEMENT_NODE, "name": "HTML"},
        {"parent": 1, "type": ELEMENT_NODE, "name": "DIV",
         "bbox": [0, 0, 1440, 900],
         "styles": {"display": "flex", "flex-direction": "row"}},
    )
    root = parse_dom_snapshot(snap)
    assert root is not None
    div = root.children[0]
    assert div.bbox == (0.0, 0.0, 1440.0, 900.0)
    assert div.computed_styles.get("display") == "flex"
    assert div.computed_styles.get("flex-direction") == "row"


def test_parse_hn_minimal_fixture() -> None:
    """実 HN fixture が crash せず木を返すこと。ルートが <html>、子孫に <table> を含む。"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "hn-minimal"
    if not fixture.exists():
        pytest.skip("hn-minimal fixture not found")
    line = (fixture / "dom_snapshots.jsonl").read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(line)
    root = parse_dom_snapshot(obj["snapshot"])
    assert root is not None
    assert root.tag_lower == "html"
    walked = root.walk()
    tags = {n.tag_lower for n in walked}
    assert "table" in tags  # HN はテーブルレイアウト
    assert "body" in tags
