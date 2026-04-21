"""
ApiAction 群 → Entity 候補クラスタ。

アルゴリズム (deterministic):
  1. 各 ApiAction について observed.sampleResponse を response_normalizer で正規化
     → フィールド名集合を抽出
  2. URL pattern から resource 名を取り出す
     (/users/:id → "user", /api/projects → "project" 等、末尾非 :id を単数化)
  3. 同じ resource 名を持つ action は無条件で同クラスタ
     (CRUD 一式を束ねる)
  4. resource 名が未知 or 異なる action 同士は、フィールド名集合の Jaccard 類似度が
     閾値以上なら同クラスタ
  5. 1 つもフィールドが取れない action は「shapeless cluster」として独立クラスタ
     に分ける(LLM が Custom 判定しやすいよう)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .response_normalizer import collect_field_types, normalize_response


if TYPE_CHECKING:
    from ...ir_schema import ApiAction


# ── Tuning ───────────────────────────────────────────────────
JACCARD_THRESHOLD = 0.8
MIN_FIELDS_FOR_JACCARD = 2  # 1 field 同士の比較は不安定なので hint_key / URL 依存
RESOURCE_SEGMENT_MIN_LEN = 2


@dataclass
class EntityCluster:
    """LLM に渡す前の raw クラスタ。"""

    id: str  # cluster_0, cluster_1, ... (順序依存、prompt の index になる)
    actions: list["ApiAction"] = field(default_factory=list)
    hint_names: list[str] = field(default_factory=list)
    # フィールド名 → 観測された型集合 (1 クラスタに複数 action の観測が混ざる)
    field_types: dict[str, set[str]] = field(default_factory=dict)
    sample_record: dict[str, Any] | None = None  # LLM に渡す代表サンプル


# ── Resource 名推定 ──────────────────────────────────────────
_URL_PATTERN_SEG_RE = re.compile(r"[^/]+")
_SINGULAR_SUFFIX_RE = re.compile(r"(ies|es|s)$", re.IGNORECASE)


def _singularize(word: str) -> str:
    if not word:
        return word
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def resource_name_from_pattern(pattern: str) -> str | None:
    """
    URL pattern から resource 単数名を推定。

    /api/v1/users/:id          → "user"
    /users/:id/comments        → "comment"
    /v2/projects               → "project"
    /health                    → "health" (動詞的でも最終セグメント)
    /                          → None
    """
    if not pattern:
        return None
    segments = [s for s in pattern.split("/") if s]
    # 先頭の api, v1, v2 などを落とす
    noise = {"api", "v1", "v2", "v3", "v4", "rest", "graphql"}
    filtered = [s for s in segments if s not in noise]
    # :id セグメントを除外して最後の resource セグメント
    resources = [s for s in filtered if not s.startswith(":")]
    if not resources:
        return None
    last = resources[-1]
    if len(last) < RESOURCE_SEGMENT_MIN_LEN:
        return None
    return _singularize(last).lower()


# ── Clustering ──────────────────────────────────────────────
def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    if not union:
        return 0.0
    return len(inter) / len(union)


def _collect_action_signature(action: "ApiAction") -> tuple[dict[str, str], Any, str | None]:
    """action の response から field_types と sample と hint_name を取る。"""
    resp = action.observed.sampleResponse
    normalized = normalize_response(resp) if resp is not None else None
    sample_value = normalized.value if normalized is not None else None
    types = collect_field_types(sample_value) if sample_value is not None else {}
    hint = None
    if normalized is not None and normalized.hint_key:
        hint = normalized.hint_key
    return types, _pick_record(sample_value), hint


def _pick_record(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def cluster_api_actions(
    api_actions: list["ApiAction"],
    *,
    jaccard_threshold: float = JACCARD_THRESHOLD,
) -> list[EntityCluster]:
    """
    ApiAction 群をクラスタ化。返り値のクラスタは決定論的な順序。
    """
    if not api_actions:
        return []

    # 各 action の signature を事前計算
    sigs: list[tuple[dict[str, str], dict[str, Any] | None, str | None, str | None]] = []
    # (field_types, sample_record, envelope_hint, resource_hint)
    for a in api_actions:
        types, record, envelope_hint = _collect_action_signature(a)
        resource_hint = resource_name_from_pattern(a.observed.urlPattern)
        sigs.append((types, record, envelope_hint, resource_hint))

    # Union-Find 簡易実装
    parent = list(range(len(api_actions)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    # 1) Same resource hint (URL-derived) → 同クラスタ
    by_resource: dict[str, list[int]] = {}
    for i, (_types, _rec, _env, resource) in enumerate(sigs):
        if resource:
            by_resource.setdefault(resource, []).append(i)
    for indices in by_resource.values():
        if len(indices) >= 2:
            base = indices[0]
            for j in indices[1:]:
                union(base, j)

    # 2) Jaccard 類似度 >= 閾値 → 同クラスタ
    for i in range(len(api_actions)):
        ftypes_i = sigs[i][0]
        if len(ftypes_i) < MIN_FIELDS_FOR_JACCARD:
            continue
        fi = set(ftypes_i.keys())
        for j in range(i + 1, len(api_actions)):
            ftypes_j = sigs[j][0]
            if len(ftypes_j) < MIN_FIELDS_FOR_JACCARD:
                continue
            fj = set(ftypes_j.keys())
            if _jaccard(fi, fj) >= jaccard_threshold:
                union(i, j)

    # 3) Group by root
    groups: dict[int, list[int]] = {}
    for i in range(len(api_actions)):
        r = find(i)
        groups.setdefault(r, []).append(i)

    # 決定論的順序: 最小 index でソート
    ordered = sorted(groups.values(), key=lambda g: min(g))

    clusters: list[EntityCluster] = []
    for idx, group in enumerate(ordered):
        cluster = EntityCluster(id=f"cluster_{idx}")
        for i in group:
            action = api_actions[i]
            cluster.actions.append(action)
            ftypes, rec, env_hint, resource = sigs[i]
            if resource and resource not in cluster.hint_names:
                cluster.hint_names.append(resource)
            if env_hint and env_hint not in cluster.hint_names:
                cluster.hint_names.append(env_hint)
            if rec is not None and cluster.sample_record is None:
                cluster.sample_record = rec
            for fname, ftype in ftypes.items():
                cluster.field_types.setdefault(fname, set()).add(ftype)
        clusters.append(cluster)

    return clusters
