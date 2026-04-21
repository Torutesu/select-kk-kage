"""
events.jsonl → Screen 列。

Day 3 時点の方針(deterministic only):
- navigation イベントの URL をキーに Screen を作る
- 最初のナビゲーションが初期画面
- route / slug は URL から heuristic に導出
- root Component は `Container` (Custom fallback 無し)、children なしのプレースホルダ
  (Day 4 で DOM snapshot を使って中身を埋める)
- requiresAuth は HAR の 401/403 レスポンスから推定… する余裕が無いので今日は False 固定
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from ..ir_schema import Component, Screen


_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """URL path → slug。空なら 'home'。"""
    s = _SLUGIFY_RE.sub("-", text.lower()).strip("-")
    return s or "home"


def _derive_route(url: str) -> str:
    path = urlparse(url).path or "/"
    return path


def _derive_slug(url: str) -> str:
    path = urlparse(url).path or "/"
    segs = [s for s in path.split("/") if s]
    if not segs:
        return "home"
    return _slugify("-".join(segs))


def _placeholder_root() -> Component:
    """Day 4 で中身を入れるまでの空のルート。"""
    return Component(
        id=uuid.uuid4(),
        kind="Container",
        confidence="low",
    )


def extract_screens(events: list[dict[str, Any]]) -> list[Screen]:
    """
    navigation イベントから Screen を作成。
    同一 URL は 1 つに統合(再訪しても Screen は増やさない)。
    """
    seen_urls: set[str] = set()
    screens: list[Screen] = []

    for ev in events:
        if ev.get("type") != "navigation":
            continue
        url = ev.get("url")
        if not isinstance(url, str) or not url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        screens.append(
            Screen(
                id=uuid.uuid4(),
                slug=_derive_slug(url),
                route=_derive_route(url),
                originalUrl=url,
                requiresAuth=False,
                initialDataBindingIds=[],
                root=_placeholder_root(),
                screenshot=None,
                confidence="low",
            )
        )

    return screens
