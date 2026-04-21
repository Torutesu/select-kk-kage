"""Stage 3 pruner のユニットテスト。"""

from __future__ import annotations

from kage_pipeline.components.pruner import prune
from kage_pipeline.utils.dom_parse import ELEMENT_NODE, TEXT_NODE, DomNode


def _element(
    tag: str,
    *,
    attrs: dict[str, str] | None = None,
    text: str = "",
    styles: dict[str, str] | None = None,
    children: list[DomNode] | None = None,
) -> DomNode:
    n = DomNode(
        index=0,
        node_type=ELEMENT_NODE,
        tag_name=tag.upper(),
        attributes=dict(attrs or {}),
        text=text,
        computed_styles=dict(styles or {}),
        children=list(children or []),
    )
    for c in n.children:
        c.parent = n
    return n


def _text(value: str) -> DomNode:
    return DomNode(index=0, node_type=TEXT_NODE, tag_name="#text", text=value)


def test_script_and_style_are_dropped() -> None:
    body = _element(
        "body",
        children=[
            _element("script", text="console.log(1)"),
            _element("style", text="body { color: red }"),
            _element("div", text="keep me"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["div"]


def test_tracking_pixel_removed() -> None:
    body = _element(
        "body",
        children=[
            _element("img", attrs={"width": "1", "height": "1", "src": "tracker.gif"}),
            _element("p", text="visible"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["p"]


def test_aria_hidden_subtree_removed() -> None:
    body = _element(
        "body",
        children=[
            _element(
                "div",
                attrs={"aria-hidden": "true"},
                children=[_element("span", text="invisible")],
            ),
            _element("p", text="visible"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["p"]


def test_display_none_removed() -> None:
    body = _element(
        "body",
        children=[
            _element("div", styles={"display": "none"}, children=[_element("p", text="hi")]),
            _element("main"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["main"]


def test_empty_div_span_removed() -> None:
    body = _element(
        "body",
        children=[
            _element("div"),  # empty, no children, no attrs
            _element("span"),
            _element("div", text="keep"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["div"]
    assert pruned.children[0].text == "keep"


def test_single_child_wrapper_flattened() -> None:
    # <body><div><button/></div></body> → <body><button/></body>
    body = _element(
        "body",
        children=[_element("div", children=[_element("button", text="ok")])],
    )
    pruned = prune(body)
    assert pruned is not None
    assert [c.tag_lower for c in pruned.children] == ["button"]


def test_wrapper_with_class_not_flattened() -> None:
    # class 有り wrapper は意味を持つので flatten しない
    body = _element(
        "body",
        children=[
            _element(
                "div",
                attrs={"class": "card"},
                children=[_element("button", text="ok")],
            )
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert len(pruned.children) == 1
    kept = pruned.children[0]
    assert kept.tag_lower == "div"
    assert kept.class_name == "card"
    assert [c.tag_lower for c in kept.children] == ["button"]


def test_returns_none_if_root_itself_dropped() -> None:
    node = _element("script", text="x")
    assert prune(node) is None


def test_empty_text_nodes_removed() -> None:
    body = _element(
        "body",
        children=[
            _text("   "),
            _text("actual content"),
        ],
    )
    pruned = prune(body)
    assert pruned is not None
    assert len(pruned.children) == 1
    assert pruned.children[0].text == "actual content"
