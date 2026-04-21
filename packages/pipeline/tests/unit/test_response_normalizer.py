"""response_normalizer のユニットテスト。"""

from __future__ import annotations

import pytest

from kage_pipeline.components.utils.response_normalizer import (
    collect_field_types,
    normalize_response,
)


# ── 単一 key envelope ─────────────────────────────────────────
@pytest.mark.parametrize("key", ["data", "result", "items", "records", "rows", "list"])
def test_single_envelope_key_unwraps(key: str) -> None:
    body = {key: [{"id": 1}]}
    r = normalize_response(body)
    assert r.was_wrapped is True
    assert r.hint_key == key
    assert r.value == [{"id": 1}]


def test_single_plural_key_unwraps() -> None:
    body = {"users": [{"id": 1, "email": "a@b.c"}]}
    r = normalize_response(body)
    assert r.was_wrapped is True
    assert r.hint_key == "user"  # 複数形 → 単数
    assert r.value == [{"id": 1, "email": "a@b.c"}]


def test_single_ies_plural_singularized() -> None:
    body = {"companies": [{"id": 1}]}
    r = normalize_response(body)
    assert r.hint_key == "company"


def test_single_non_envelope_passes_through() -> None:
    body = {"username": "foo", "age": 30}
    r = normalize_response(body)
    assert r.was_wrapped is False
    assert r.value == body


# ── meta envelope ────────────────────────────────────────────
def test_pagination_wrapper_unwraps_items() -> None:
    body = {"items": [{"id": 1}], "total": 100, "page": 1}
    r = normalize_response(body)
    assert r.was_wrapped is True
    assert r.hint_key == "items"
    assert r.value == [{"id": 1}]


def test_success_data_envelope() -> None:
    body = {"success": True, "data": {"id": 42, "name": "x"}}
    r = normalize_response(body)
    assert r.was_wrapped is True
    assert r.hint_key == "data"
    assert r.value == {"id": 42, "name": "x"}


def test_meta_plus_plural_unwraps() -> None:
    body = {"projects": [{"id": 1}], "meta": {"nextCursor": "abc"}}
    r = normalize_response(body)
    assert r.was_wrapped is True
    assert r.hint_key == "project"
    assert r.value == [{"id": 1}]


def test_multiple_data_keys_no_unwrap() -> None:
    # data key が 2 つ以上 → どちらを剥がすか決定不能 → そのまま
    body = {"users": [], "teams": [], "meta": {}}
    r = normalize_response(body)
    assert r.was_wrapped is False
    assert r.value == body


# ── 非 dict ──────────────────────────────────────────────────
def test_list_passes_through() -> None:
    r = normalize_response([{"id": 1}])
    assert r.was_wrapped is False
    assert r.value == [{"id": 1}]


def test_primitive_passes_through() -> None:
    r = normalize_response("hello")
    assert r.was_wrapped is False
    assert r.value == "hello"


def test_empty_dict_passes_through() -> None:
    r = normalize_response({})
    assert r.was_wrapped is False
    assert r.value == {}


# ── collect_field_types ──────────────────────────────────────
def test_collect_field_types_from_array() -> None:
    value = [{"id": 1, "email": "a@b.c", "active": True}]
    t = collect_field_types(value)
    assert t == {"id": "int", "email": "string", "active": "bool"}


def test_collect_field_types_from_object() -> None:
    value = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "createdAt": "2026-04-21T12:00:00Z",
        "score": 3.14,
        "tags": ["a", "b"],
        "owner": {"id": 1},
        "archived": False,
        "deletedAt": None,
    }
    t = collect_field_types(value)
    assert t["id"] == "uuid-like"
    assert t["createdAt"] == "datetime-like"
    assert t["score"] == "float"
    assert t["tags"] == "array"
    assert t["owner"] == "object"
    assert t["archived"] == "bool"
    assert t["deletedAt"] == "null"


def test_collect_field_types_empty_array_returns_empty_map() -> None:
    assert collect_field_types([]) == {}


def test_collect_field_types_on_primitive_returns_empty() -> None:
    assert collect_field_types("hello") == {}
    assert collect_field_types(42) == {}
