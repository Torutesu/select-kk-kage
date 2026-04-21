"""entity_clusterer のユニットテスト。"""

from __future__ import annotations

import uuid

from kage_pipeline.components.utils.entity_clusterer import (
    cluster_api_actions,
    resource_name_from_pattern,
)
from kage_pipeline.ir_schema import ApiAction, ApiActionObserved


def _api(
    name: str,
    method: str,
    url_pattern: str,
    sample_response: object | None = None,
) -> ApiAction:
    return ApiAction(
        id=uuid.uuid4(),
        name=name,
        kind="query" if method == "GET" else "mutation",
        observed=ApiActionObserved(
            method=method,  # type: ignore[arg-type]
            urlPattern=url_pattern,
            sampleResponse=sample_response,
        ),
        entityIds=[],
        confidence="medium",
    )


# ── resource_name_from_pattern ─────────────────────────────────
def test_resource_name_plural_to_singular() -> None:
    assert resource_name_from_pattern("/users") == "user"
    assert resource_name_from_pattern("/companies") == "company"
    assert resource_name_from_pattern("/statuses") == "status"


def test_resource_name_skips_api_prefix() -> None:
    assert resource_name_from_pattern("/api/v1/projects") == "project"


def test_resource_name_ignores_id_segment() -> None:
    assert resource_name_from_pattern("/api/users/:id") == "user"


def test_resource_name_nested() -> None:
    assert resource_name_from_pattern("/api/users/:id/comments") == "comment"


def test_resource_name_root_returns_none() -> None:
    assert resource_name_from_pattern("/") is None


def test_resource_name_too_short_returns_none() -> None:
    # 単一文字のセグメントは resource とみなさない
    assert resource_name_from_pattern("/a") is None


# ── cluster_api_actions ────────────────────────────────────────
def test_empty_input_yields_empty_clusters() -> None:
    assert cluster_api_actions([]) == []


def test_crud_set_groups_by_resource() -> None:
    """同一 resource の GET/POST/PUT/DELETE を束ねる。"""
    actions = [
        _api("users.list", "GET", "/api/users", [{"id": 1, "email": "a@b.c"}]),
        _api("users.get", "GET", "/api/users/:id", {"id": 1, "email": "a@b.c"}),
        _api("users.create", "POST", "/api/users", {"id": 2, "email": "x@y.z"}),
        _api("users.delete", "DELETE", "/api/users/:id", {"success": True}),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 1
    c = clusters[0]
    assert len(c.actions) == 4
    assert "user" in c.hint_names


def test_different_resources_yield_separate_clusters() -> None:
    actions = [
        _api("users.list", "GET", "/users", [{"id": 1, "email": "a@b.c"}]),
        _api("projects.list", "GET", "/projects", [{"id": 10, "title": "p"}]),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 2
    # 決定論的順序(最小 index)
    assert "user" in clusters[0].hint_names
    assert "project" in clusters[1].hint_names


def test_jaccard_groups_unknown_resources() -> None:
    """resource が推定できなくてもフィールド類似で束ねる。"""
    # /health と /status はどちらも resource 名が違うが、返す shape は同一 fields
    actions = [
        _api(
            "health.get", "GET", "/health",
            {"id": 1, "email": "a@b.c", "name": "x", "createdAt": "2026-01-01T00:00:00Z"},
        ),
        _api(
            "status.get", "GET", "/status",
            {"id": 2, "email": "y@z.c", "name": "y", "createdAt": "2026-01-02T00:00:00Z"},
        ),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 1
    assert clusters[0].field_types.keys() == {"id", "email", "name", "createdAt"}


def test_jaccard_below_threshold_separates() -> None:
    actions = [
        _api(
            "a.get", "GET", "/a",
            {"id": 1, "field1": "x", "field2": "y"},
        ),
        _api(
            "b.get", "GET", "/b",
            {"id": 2, "other1": "x", "other2": "y", "other3": "z"},
        ),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 2  # Jaccard < 0.8


def test_envelope_is_unwrapped_before_clustering() -> None:
    """pagination wrapper が違っても中身が同じなら 1 クラスタ。"""
    actions = [
        _api(
            "a.list", "GET", "/a",
            {"items": [{"id": 1, "email": "a@b.c"}], "total": 1},
        ),
        _api(
            "b.list", "GET", "/b",
            {"data": [{"id": 2, "email": "x@y.z"}]},
        ),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 1


def test_shapeless_actions_each_independent() -> None:
    """sampleResponse が無い action は別クラスタ、かつフィールド類似だけでは束ねない。"""
    actions = [
        _api("a.create", "POST", "/api/a"),  # no sampleResponse
        _api("b.create", "POST", "/api/b"),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 2


def test_field_types_accumulate_across_actions_in_cluster() -> None:
    """同じクラスタの複数 action で field の型が異なる場合、両方記録する。"""
    actions = [
        _api("u.list", "GET", "/users", [{"id": 1, "email": "a@b.c"}]),
        _api("u.get", "GET", "/users/:id", {"id": "uuid-like", "email": "a@b.c"}),
    ]
    clusters = cluster_api_actions(actions)
    assert len(clusters) == 1
    # id は int と string(uuid-like 風)の両方を観測
    assert clusters[0].field_types["id"] == {"int", "string"}


def test_cluster_ids_are_deterministic() -> None:
    actions = [
        _api("a.list", "GET", "/a", [{"x": 1}]),
        _api("b.list", "GET", "/b", [{"y": 1}]),
    ]
    cs = cluster_api_actions(actions)
    assert [c.id for c in cs] == ["cluster_0", "cluster_1"]


def test_sample_record_captured_when_available() -> None:
    actions = [
        _api("u.list", "GET", "/users", [{"id": 1, "email": "foo@bar.com"}]),
    ]
    cs = cluster_api_actions(actions)
    assert cs[0].sample_record == {"id": 1, "email": "foo@bar.com"}
