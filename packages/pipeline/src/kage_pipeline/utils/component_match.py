"""
イベントの target (bbox + text + selector) から IR 上の Component.id を逆引きする。

IR スキーマは凍結のため tagName/className を直接保持しない(customFallback は kind=Custom のみ)。
そのため bbox + text を主軸にマッチさせ、最後に (あれば) customFallback の selector を使う。

優先順位:
  1. bbox IoU > COMPONENT_MATCH_MIN_IOU (>= 0.5) — 最優先
  2. 中心点が Component.bbox に含まれる(IoU 計算不能な 0 サイズ対策)
  3. text prefix 一致(bbox が無いイベントへの backup)
  4. customFallback.className / role と event.target の selector に含まれるトークンの一致
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..ir_schema import Component


COMPONENT_MATCH_MIN_IOU = 0.5
TEXT_MATCH_PREFIX_LEN = 40


def _iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """2 つの bbox (x, y, w, h) の Intersection over Union。"""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, aw) * max(0.0, ah)
    area_b = max(0.0, bw) * max(0.0, bh)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _component_bbox_tuple(
    component: "Component",
) -> tuple[float, float, float, float] | None:
    b = component.bbox
    if b is None:
        return None
    return (b.x, b.y, b.width, b.height)


def _point_inside(
    px: float, py: float, box: tuple[float, float, float, float]
) -> bool:
    x, y, w, h = box
    return x <= px <= x + w and y <= py <= y + h


def _event_bbox(event_target: dict[str, Any] | None) -> tuple[float, float, float, float] | None:
    if not isinstance(event_target, dict):
        return None
    b = event_target.get("bbox")
    if not isinstance(b, dict):
        return None
    try:
        return (
            float(b.get("x") or 0),
            float(b.get("y") or 0),
            float(b.get("width") or 0),
            float(b.get("height") or 0),
        )
    except (TypeError, ValueError):
        return None


def _iter_components(root: "Component") -> "Iterator[Component]":
    yield root
    for c in root.children:
        yield from _iter_components(c)


def _text_prefix(s: str | None) -> str:
    if not s:
        return ""
    return s.strip()[:TEXT_MATCH_PREFIX_LEN]


def _selector_class_tokens(selector: str | None) -> set[str]:
    """event.selector = "div.btn.primary" 等から class 名の set を取り出す。"""
    if not selector:
        return set()
    out: set[str] = set()
    for tok in selector.split("."):
        tok = tok.strip()
        if not tok:
            continue
        # 先頭要素は tag#id の可能性、# より後と [ より前だけ取る
        if "#" in tok:
            tok = tok.split("#")[0]
        if "[" in tok:
            tok = tok.split("[")[0]
        if tok and not tok[0].isupper():
            # class 名候補はタグ名を除外したいので、2 文字以上で記号無しなら採用
            if len(tok) >= 2 and tok.isidentifier() or "-" in tok or "_" in tok:
                out.add(tok)
    return out


def match_component(
    screen_root: "Component", event: dict[str, Any]
) -> "Component | None":
    """
    1 つのユーザイベントに最も合う Component を返す。見つからなければ None。
    """
    target = event.get("target") if isinstance(event, dict) else None
    ev_bbox = _event_bbox(target)
    ev_text = _text_prefix((target or {}).get("text") if isinstance(target, dict) else None)
    ev_selector = event.get("selector") if isinstance(event, dict) else None

    best: "Component | None" = None
    best_score = 0.0

    for c in _iter_components(screen_root):
        comp_bbox = _component_bbox_tuple(c)

        score = 0.0
        # 1) IoU
        if ev_bbox is not None and comp_bbox is not None:
            iou = _iou(ev_bbox, comp_bbox)
            if iou >= COMPONENT_MATCH_MIN_IOU:
                score = max(score, iou)
            # 2) point-in-box: event の中心が comp に含まれるなら
            elif comp_bbox is not None:
                cx = ev_bbox[0] + ev_bbox[2] / 2
                cy = ev_bbox[1] + ev_bbox[3] / 2
                if _point_inside(cx, cy, comp_bbox):
                    # 小さい comp ほど優先(深い子要素の方が選択対象)
                    comp_area = max(1.0, comp_bbox[2] * comp_bbox[3])
                    score = max(score, 0.6 + 1.0 / comp_area)

        # 3) text prefix match
        if ev_text and c.text:
            ct = c.text.strip()[:TEXT_MATCH_PREFIX_LEN]
            if ct and (ct.startswith(ev_text) or ev_text.startswith(ct)):
                score = max(score, 0.55)

        # 4) customFallback class / role と selector class 合致
        if isinstance(ev_selector, str) and c.customFallback is not None:
            sel_cls = _selector_class_tokens(ev_selector)
            comp_cls = set()
            cf_cls = c.customFallback.className or ""
            for tok in cf_cls.split():
                if tok:
                    comp_cls.add(tok)
            if sel_cls and comp_cls and sel_cls & comp_cls:
                score = max(score, 0.52)

        if score > best_score:
            best_score = score
            best = c

    return best if best_score > 0 else None
