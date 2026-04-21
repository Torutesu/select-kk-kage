"""Stage 1 classifier: deterministic DOM → ComponentKind。"""

from __future__ import annotations

import pytest

from kage_pipeline.components.classifier_stage1 import classify_node
from kage_pipeline.utils.dom_parse import ELEMENT_NODE, DomNode


def _node(
    tag: str,
    *,
    role: str = "",
    class_: str = "",
    attrs: dict[str, str] | None = None,
    text: str = "",
    bbox: tuple[float, float, float, float] | None = None,
    styles: dict[str, str] | None = None,
    children: list[DomNode] | None = None,
) -> DomNode:
    a: dict[str, str] = dict(attrs or {})
    if role:
        a["role"] = role
    if class_:
        a["class"] = class_
    n = DomNode(
        index=0,
        node_type=ELEMENT_NODE,
        tag_name=tag.upper(),
        attributes=a,
        text=text,
        bbox=bbox,
        computed_styles=dict(styles or {}),
        children=list(children or []),
    )
    for c in n.children:
        c.parent = n
    return n


# ── ARIA role 優先 ────────────────────────────────────────
@pytest.mark.parametrize(
    "role,expected",
    [
        ("button", "Button"),
        ("link", "Link"),
        ("heading", "Heading"),
        ("dialog", "Dialog"),
        ("alert", "Alert"),
        ("complementary", "Sidebar"),
        ("menu", "DropdownMenu"),
        ("tablist", "Tabs"),
        ("table", "Table"),
        ("grid", "DataTable"),
        ("checkbox", "Checkbox"),
        ("switch", "Switch"),
        ("textbox", "Input"),
        ("img", "Image"),
        ("separator", "Separator"),
        ("tooltip", "Tooltip"),
        ("status", "Badge"),
    ],
)
def test_aria_role_mapping(role: str, expected: str) -> None:
    n = _node("div", role=role)
    assert classify_node(n) == expected


# ── semantic tag ─────────────────────────────────────────
@pytest.mark.parametrize(
    "tag,expected",
    [
        ("button", "Button"),
        ("a", "Link"),
        ("textarea", "Textarea"),
        ("select", "Select"),
        ("form", "Form"),
        ("label", "Label"),
        ("aside", "Sidebar"),
        ("header", "Navbar"),
        ("dialog", "Dialog"),
        ("ul", "List"),
        ("ol", "List"),
        ("h1", "Heading"),
        ("h3", "Heading"),
        ("p", "Paragraph"),
        ("img", "Image"),
        ("video", "Video"),
        ("hr", "Separator"),
        ("svg", "Icon"),
    ],
)
def test_semantic_tag_mapping(tag: str, expected: str) -> None:
    n = _node(tag)
    assert classify_node(n) == expected


# ── input type 細分化 ────────────────────────────────────
@pytest.mark.parametrize(
    "input_type,expected",
    [
        ("text", "Input"),
        ("email", "Input"),
        ("password", "Input"),
        ("search", "Input"),
        ("checkbox", "Checkbox"),
        ("radio", "Radio"),
        ("range", "Slider"),
        ("submit", "Button"),
        ("file", "Input"),
    ],
)
def test_input_type_mapping(input_type: str, expected: str) -> None:
    n = _node("input", attrs={"type": input_type})
    assert classify_node(n) == expected


def test_input_default_text() -> None:
    n = _node("input")  # type 未指定
    assert classify_node(n) == "Input"


# ── className heuristic ────────────────────────────────────
@pytest.mark.parametrize(
    "class_name,expected",
    [
        ("btn btn-primary", "Button"),
        ("shadcn-btn", "Button"),
        ("sidebar-root", "Sidebar"),
        ("side-nav", "Sidebar"),
        ("top-bar", "Navbar"),
        ("breadcrumb-list", "Breadcrumb"),
        ("data-table", "DataTable"),
        ("card card-bordered", "Card"),
        ("badge", "Badge"),
        ("avatar", "Avatar"),
        ("divider", "Separator"),
        ("scroll-area", "ScrollArea"),
        ("modal-backdrop", "Dialog"),
        ("popover-content", "Popover"),
        ("toast-root", "Toast"),
        ("dropdown-menu", "DropdownMenu"),
        ("switch-root", "Switch"),
    ],
)
def test_class_name_heuristic(class_name: str, expected: str) -> None:
    n = _node("div", class_=class_name)
    assert classify_node(n) == expected


# ── <nav> の位置で Navbar vs Sidebar ───────────────────────
def test_nav_becomes_sidebar_when_narrow_on_left() -> None:
    n = _node("nav", bbox=(0, 0, 240, 900))
    assert classify_node(n, viewport_width=1440) == "Sidebar"


def test_nav_is_navbar_when_wide() -> None:
    n = _node("nav", bbox=(0, 0, 1440, 60))
    assert classify_node(n, viewport_width=1440) == "Navbar"


# ── <table> 行数で DataTable ──────────────────────────────
def test_table_with_many_rows_is_data_table() -> None:
    rows = [_node("tr"), _node("tr"), _node("tr")]
    tbody = _node("tbody", children=rows)
    table = _node("table", children=[tbody])
    assert classify_node(table) == "DataTable"


def test_table_with_one_row_is_table() -> None:
    tbody = _node("tbody", children=[_node("tr")])
    table = _node("table", children=[tbody])
    assert classify_node(table) == "Table"


# ── data-component 明示指定 ───────────────────────────────
def test_data_component_attribute_wins_over_tag() -> None:
    n = _node("div", attrs={"data-component": "Card"})
    assert classify_node(n) == "Card"


def test_data_component_invalid_kind_ignored() -> None:
    n = _node("div", attrs={"data-component": "NotInSchema"})
    # class も無いので Custom になる
    assert classify_node(n) == "Custom"


# ── 無指定の div / span は Custom ─────────────────────────
def test_bare_div_is_custom() -> None:
    assert classify_node(_node("div")) == "Custom"


def test_bare_span_is_custom() -> None:
    assert classify_node(_node("span")) == "Custom"


# ── ARIA role が tag より優先 ─────────────────────────────
def test_role_wins_over_tag() -> None:
    n = _node("a", role="button")
    assert classify_node(n) == "Button"
