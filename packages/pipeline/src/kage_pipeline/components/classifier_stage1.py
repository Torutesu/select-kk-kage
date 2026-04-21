"""
Stage 1: Deterministic DOM → ComponentKind classifier (LLM 不要)。

優先順位:
  1. ARIA role
  2. セマンティックタグ
  3. class 名 heuristic (btn / card / modal 等)
  4. 属性 heuristic (data-testid / data-component)

マッチしなければ "Custom"。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..ir_schema import ComponentKind

if TYPE_CHECKING:
    from ..utils.dom_parse import DomNode


# ─────────────────────────────────────────────────────────────
# ARIA role → ComponentKind
# ─────────────────────────────────────────────────────────────
ROLE_TO_KIND: dict[str, ComponentKind] = {
    "button": "Button",
    "link": "Link",
    "heading": "Heading",
    "dialog": "Dialog",
    "alertdialog": "Dialog",
    "alert": "Alert",
    "navigation": "Navbar",  # bbox で Sidebar に上書きされうる
    "complementary": "Sidebar",  # <aside> 相当
    "toolbar": "Navbar",
    "menu": "DropdownMenu",
    "menuitem": "DropdownMenu",
    "tablist": "Tabs",
    "tab": "Tabs",
    "tabpanel": "Tabs",
    "list": "List",
    "listitem": "List",
    "table": "Table",
    "grid": "DataTable",
    "combobox": "Select",
    "checkbox": "Checkbox",
    "radio": "Radio",
    "switch": "Switch",
    "slider": "Slider",
    "textbox": "Input",
    "searchbox": "Input",
    "img": "Image",
    "separator": "Separator",
    "tooltip": "Tooltip",
    "status": "Badge",
    "progressbar": "Skeleton",
    "form": "Form",
    "banner": "Navbar",
    "contentinfo": "Container",
    "main": "Container",
    "region": "Container",
    "presentation": "Container",
    "none": "Container",
}

# ─────────────────────────────────────────────────────────────
# Tag name → ComponentKind
# ─────────────────────────────────────────────────────────────
TAG_TO_KIND: dict[str, ComponentKind] = {
    "button": "Button",
    "a": "Link",
    "input": "Input",  # type で上書き
    "textarea": "Textarea",
    "select": "Select",
    "option": "Select",
    "form": "Form",
    "label": "Label",
    "nav": "Navbar",  # bbox で Sidebar に上書きされうる
    "aside": "Sidebar",
    "header": "Navbar",
    "footer": "Container",
    "main": "Container",
    "section": "Container",
    "article": "Card",
    "dialog": "Dialog",
    "table": "Table",
    "thead": "Table",
    "tbody": "Table",
    "tr": "Custom",  # table の row はツリーとして処理、kind は Custom
    "td": "Custom",
    "th": "Custom",
    "ul": "List",
    "ol": "List",
    "li": "List",
    "h1": "Heading",
    "h2": "Heading",
    "h3": "Heading",
    "h4": "Heading",
    "h5": "Heading",
    "h6": "Heading",
    "p": "Paragraph",
    "img": "Image",
    "picture": "Image",
    "video": "Video",
    "hr": "Separator",
    "svg": "Icon",
    "i": "Icon",
    "code": "Paragraph",
    "pre": "Paragraph",
    "blockquote": "Paragraph",
    "span": "Custom",
    "div": "Custom",
    "body": "Container",
    "html": "Container",
    "center": "Container",
    "br": "Custom",
}

# ─────────────────────────────────────────────────────────────
# input[type=...] → ComponentKind
# ─────────────────────────────────────────────────────────────
INPUT_TYPE_TO_KIND: dict[str, ComponentKind] = {
    "text": "Input",
    "email": "Input",
    "password": "Input",
    "search": "Input",
    "tel": "Input",
    "url": "Input",
    "number": "Input",
    "date": "Input",
    "datetime-local": "Input",
    "month": "Input",
    "week": "Input",
    "time": "Input",
    "color": "Input",
    "file": "Input",
    "checkbox": "Checkbox",
    "radio": "Radio",
    "range": "Slider",
    "submit": "Button",
    "reset": "Button",
    "button": "Button",
    "image": "Button",
    "hidden": "Custom",
}


# ─────────────────────────────────────────────────────────────
# className heuristic(優先: ユーティリティ > プロダクト)
# ─────────────────────────────────────────────────────────────
# 順序が意味を持つ: 先に match したものを採用
CLASS_PATTERNS: list[tuple[re.Pattern[str], ComponentKind]] = [
    # dialog / modal / drawer
    (re.compile(r"\b(modal|dialog)\b", re.I), "Dialog"),
    (re.compile(r"\b(drawer|sheet)\b", re.I), "Drawer"),
    (re.compile(r"\b(popover|popup)\b", re.I), "Popover"),
    (re.compile(r"\b(tooltip)\b", re.I), "Tooltip"),
    (re.compile(r"\b(toast|snackbar|notification)\b", re.I), "Toast"),
    (re.compile(r"\b(alert|banner-message)\b", re.I), "Alert"),
    # nav / sidebar
    (re.compile(r"\b(sidebar|side-?nav|side-?menu)\b", re.I), "Sidebar"),
    (re.compile(r"\b(navbar|top-?bar|top-?nav|header-?nav)\b", re.I), "Navbar"),
    (re.compile(r"\b(breadcrumb)\b", re.I), "Breadcrumb"),
    (re.compile(r"\b(pagination|pager)\b", re.I), "Pagination"),
    (re.compile(r"\b(tabs?-list|tab-?list|tabbar)\b", re.I), "Tabs"),
    # data display
    (re.compile(r"\b(data-?table|grid-?table)\b", re.I), "DataTable"),
    (re.compile(r"\b(card)\b", re.I), "Card"),
    (re.compile(r"\b(badge|chip|pill|tag)\b", re.I), "Badge"),
    (re.compile(r"\b(avatar)\b", re.I), "Avatar"),
    (re.compile(r"\b(skeleton|placeholder-?loader)\b", re.I), "Skeleton"),
    (re.compile(r"\b(separator|divider)\b", re.I), "Separator"),
    (re.compile(r"\b(scroll-?area|overflow-?auto)\b", re.I), "ScrollArea"),
    # form controls
    (re.compile(r"\b(checkbox)\b", re.I), "Checkbox"),
    (re.compile(r"\b(switch|toggle)\b", re.I), "Switch"),
    (re.compile(r"\b(slider)\b", re.I), "Slider"),
    (re.compile(r"\b(dropdown-?menu|context-?menu)\b", re.I), "DropdownMenu"),
    # buttons / links
    (re.compile(r"\b(btn|button|cta)\b", re.I), "Button"),
    # layout
    (re.compile(r"\b(stack|flex-col|flex-row|hstack|vstack)\b", re.I), "Stack"),
    (re.compile(r"\b(grid-?container|grid-?layout)\b", re.I), "Grid"),
    (re.compile(r"\b(container|wrapper)\b", re.I), "Container"),
]


# Sidebar 判定: 画面幅に対する bbox.x の閾値
SIDEBAR_MAX_WIDTH_PX = 400
SIDEBAR_LEFT_FRACTION = 0.2  # viewport の左 20% に収まるなら Sidebar 候補


def _normalize_kind_for_table(node: "DomNode") -> ComponentKind | None:
    """<table> の行数から DataTable 判定。tr 数 > 1 なら DataTable。"""
    rows = 0
    for n in node.walk():
        if n.tag_lower == "tr":
            rows += 1
    return "DataTable" if rows > 1 else "Table"


def _refine_nav(node: "DomNode", viewport_width: float | None) -> ComponentKind:
    """<nav> の位置情報で Navbar vs Sidebar を切り替える。"""
    bbox = node.bbox
    if bbox is None:
        return "Navbar"
    x, _y, w, _h = bbox
    if w < SIDEBAR_MAX_WIDTH_PX:
        if viewport_width and viewport_width > 0:
            if x < viewport_width * SIDEBAR_LEFT_FRACTION:
                return "Sidebar"
        else:
            if x < viewport_width_fallback() * SIDEBAR_LEFT_FRACTION:
                return "Sidebar"
    return "Navbar"


def viewport_width_fallback() -> float:
    """ビューポート幅不明時の fallback。recorder は 1440x900 デフォルト。"""
    return 1440.0


def _match_class_patterns(class_name: str) -> ComponentKind | None:
    if not class_name:
        return None
    for pat, kind in CLASS_PATTERNS:
        if pat.search(class_name):
            return kind
    return None


def _from_data_component(attrs: dict[str, str]) -> ComponentKind | None:
    """data-component="Button" 等を直接拾う(shadcn の data 属性にありがち)。"""
    for key in ("data-component", "data-ui", "data-kind"):
        if key in attrs:
            v = attrs[key].strip()
            # 先頭大文字の英単語 → enum に一致するか
            if re.fullmatch(r"[A-Z][a-zA-Z]+", v):
                # 列挙と照合 (スキーマ enum を硬参照しない: ComponentKind の Literal は文字列)
                kinds: set[str] = set(get_all_kinds())
                if v in kinds:
                    return v  # type: ignore[return-value]
    return None


def get_all_kinds() -> list[ComponentKind]:
    """ir_schema の ComponentKind Literal を総ざらいする。"""
    # typing.get_args でランタイムに取得
    from typing import get_args

    from ..ir_schema import ComponentKind as CK

    return list(get_args(CK))


def classify_node(node: "DomNode", *, viewport_width: float | None = None) -> ComponentKind:
    """
    DomNode 1 つを ComponentKind に分類する。
    決まらない場合 "Custom"。
    """
    # 1) ARIA role
    role = (node.role or "").strip().lower()
    if role:
        kind = ROLE_TO_KIND.get(role)
        if kind == "Navbar":  # 位置で Sidebar に refine
            return _refine_nav(node, viewport_width)
        if kind is not None:
            return kind

    # 2) data-component etc.
    dc = _from_data_component(node.attributes)
    if dc is not None:
        return dc

    tag = node.tag_lower

    # 3) <input type=...> は type で細分化
    if tag == "input":
        t = node.attributes.get("type", "text").strip().lower()
        return INPUT_TYPE_TO_KIND.get(t, "Input")

    # 4) <nav> は位置で Sidebar or Navbar
    if tag == "nav":
        return _refine_nav(node, viewport_width)

    # 5) <table> は行数で Table vs DataTable
    if tag == "table":
        return _normalize_kind_for_table(node) or "Table"

    # 6) タグから
    tag_kind = TAG_TO_KIND.get(tag)
    if tag_kind is not None and tag_kind != "Custom":
        return tag_kind

    # 7) className heuristic
    cls_kind = _match_class_patterns(node.class_name)
    if cls_kind is not None:
        return cls_kind

    # 8) タグから Custom 確定
    if tag_kind == "Custom":
        return "Custom"

    # 9) フォールバック
    return "Custom"
