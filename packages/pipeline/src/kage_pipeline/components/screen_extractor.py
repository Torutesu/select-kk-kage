"""
events.jsonl + dom_snapshots.jsonl → Screen 列。

Day 4 以前は placeholder Container で root を埋めていた。
Day 4 後半からは URL に対応する DOM snapshot を拾って Component tree を生成する。
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from ..ir_schema import Component, Screen
from ..utils.dom_parse import parse_dom_snapshot
from .component_tree import build_component_tree_sync


_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    s = _SLUGIFY_RE.sub("-", text.lower()).strip("-")
    return s or "home"


def _derive_route(url: str) -> str:
    return urlparse(url).path or "/"


def _derive_slug(url: str) -> str:
    path = urlparse(url).path or "/"
    segs = [s for s in path.split("/") if s]
    if not segs:
        return "home"
    return _slugify("-".join(segs))


def _placeholder_root() -> Component:
    return Component(id=uuid.uuid4(), kind="Container", confidence="low")


def _pick_snapshot_for_url(
    snapshots_by_url: dict[str, list[dict[str, Any]]],
    url: str,
) -> dict[str, Any] | None:
    """URL に対応する最も展開された snapshot を返す。同 URL なら最後のものを優先。"""
    if url in snapshots_by_url and snapshots_by_url[url]:
        return snapshots_by_url[url][-1]
    return None


def extract_screens(
    events: list[dict[str, Any]],
    dom_snapshots: list[dict[str, Any]] | None = None,
    *,
    viewport_width: float | None = None,
) -> list[Screen]:
    """
    navigation イベントから Screen を作成し、URL に対応する DOMSnapshot から
    root Component ツリーを生成する。

    dom_snapshots 未指定 or 対応 snapshot 無しのときは placeholder Container。
    """
    # URL -> snapshot 一覧 (順序保持)
    snapshots_by_url: dict[str, list[dict[str, Any]]] = {}
    for snap in dom_snapshots or []:
        url = snap.get("url")
        if not isinstance(url, str) or not url:
            continue
        snapshots_by_url.setdefault(url, []).append(snap)

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

        root: Component
        picked = _pick_snapshot_for_url(snapshots_by_url, url)
        if picked is not None:
            snapshot_obj = picked.get("snapshot")
            if isinstance(snapshot_obj, dict):
                dom_root = parse_dom_snapshot(snapshot_obj)
                if dom_root is not None:
                    root = build_component_tree_sync(
                        dom_root, viewport_width=viewport_width
                    )
                else:
                    root = _placeholder_root()
            else:
                root = _placeholder_root()
        else:
            root = _placeholder_root()

        screens.append(
            Screen(
                id=uuid.uuid4(),
                slug=_derive_slug(url),
                route=_derive_route(url),
                originalUrl=url,
                requiresAuth=False,
                initialDataBindingIds=[],
                root=root,
                screenshot=None,
                confidence="high" if picked else "low",
            )
        )

    return screens
