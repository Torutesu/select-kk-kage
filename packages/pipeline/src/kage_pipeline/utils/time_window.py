"""
時系列イベント操作のユーティリティ。

events.jsonl のレコードは dict で、各要素に int 'timestamp' (ms since recording start)
を持つ想定。
"""

from __future__ import annotations

from typing import Any


def before(events: list[dict[str, Any]], t: float) -> list[dict[str, Any]]:
    """timestamp < t のイベントを返す(順序は保持)。"""
    return [e for e in events if _ts(e) < t]


def after(events: list[dict[str, Any]], t: float) -> list[dict[str, Any]]:
    return [e for e in events if _ts(e) >= t]


def within(
    events: list[dict[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    """start <= timestamp <= end のイベント。"""
    return [e for e in events if start <= _ts(e) <= end]


def closest_before(
    events: list[dict[str, Any]],
    t: float,
    *,
    types: set[str] | None = None,
    max_gap_ms: float = float("inf"),
) -> dict[str, Any] | None:
    """
    時刻 t より前で最も t に近いイベントを返す(types 指定があればそれに限定)。
    gap が max_gap_ms を超えるものは返さない。
    """
    best: dict[str, Any] | None = None
    best_gap = max_gap_ms
    for e in events:
        ts = _ts(e)
        if ts >= t:
            continue
        if types is not None and e.get("type") not in types:
            continue
        gap = t - ts
        if gap <= best_gap:
            best_gap = gap
            best = e
    return best


def closest_after(
    events: list[dict[str, Any]],
    t: float,
    *,
    types: set[str] | None = None,
    max_gap_ms: float = float("inf"),
) -> dict[str, Any] | None:
    """時刻 t 以降で最も近いイベント。"""
    best: dict[str, Any] | None = None
    best_gap = max_gap_ms
    for e in events:
        ts = _ts(e)
        if ts < t:
            continue
        if types is not None and e.get("type") not in types:
            continue
        gap = ts - t
        if gap <= best_gap:
            best_gap = gap
            best = e
    return best


def _ts(event: dict[str, Any]) -> float:
    v = event.get("timestamp")
    if isinstance(v, int | float):
        return float(v)
    return 0.0
