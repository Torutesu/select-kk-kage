"""HAR → ApiAction の deterministic logic."""

from __future__ import annotations

from typing import Any

import pytest

from kage_pipeline.components.api_extractor import (
    derive_action_name,
    derive_url_pattern,
    extract_api_actions,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/api/users/42", "/api/users/:id"),
        ("https://x.com/api/users/550e8400-e29b-41d4-a716-446655440000",
         "/api/users/:id"),
        ("https://x.com/api/users/42/posts/99", "/api/users/:id/posts/:id"),
        ("https://x.com/", "/"),
        ("https://x.com/dashboard", "/dashboard"),
        ("https://x.com/api/items?q=hello", "/api/items"),
    ],
)
def test_derive_url_pattern(url: str, expected: str) -> None:
    assert derive_url_pattern(url) == expected


@pytest.mark.parametrize(
    "method,pattern,expected",
    [
        ("GET", "/api/users", "users.list"),
        ("GET", "/api/users/:id", "users.get"),
        ("POST", "/api/users", "users.create"),
        ("PUT", "/api/users/:id", "users.update"),
        ("PATCH", "/api/users/:id", "users.update"),
        ("DELETE", "/api/users/:id", "users.delete"),
        # /api/ prefix で resource が "api" になる場合は 1 つ前を採用
        ("GET", "/api", "api.list"),
        ("GET", "/api/:id", "api.get"),
    ],
)
def test_derive_action_name(method: str, pattern: str, expected: str) -> None:
    assert derive_action_name(method, pattern) == expected  # type: ignore[arg-type]


def test_extract_from_hn_har(hn_minimal_har: dict[str, Any]) -> None:
    actions = extract_api_actions(hn_minimal_har)
    # HN は JSON API を持たないので ApiAction は 0 件になる想定(静的ドキュメントはフィルタ)
    for a in actions:
        assert a.observed.urlPattern.startswith("/")
        assert a.name
    # 静的/サードパーティ除外が効いていること:google-analytics が含まれないこと
    for a in actions:
        assert "google-analytics" not in a.observed.urlPattern


def test_extract_from_synthetic_har() -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {"method": "GET", "url": "https://api.app.com/v1/users"},
                    "response": {
                        "status": 200,
                        "content": {"mimeType": "application/json", "text": '[{"id":1}]'},
                    },
                },
                {
                    "request": {
                        "method": "POST",
                        "url": "https://api.app.com/v1/users",
                        "postData": {"mimeType": "application/json", "text": '{"name":"x"}'},
                    },
                    "response": {
                        "status": 201,
                        "content": {"mimeType": "application/json", "text": '{"id":2}'},
                    },
                },
                {
                    "request": {"method": "GET", "url": "https://api.app.com/v1/users/42"},
                    "response": {
                        "status": 200,
                        "content": {"mimeType": "application/json", "text": '{"id":42}'},
                    },
                },
                # 除外対象: 静的 asset
                {
                    "request": {"method": "GET", "url": "https://cdn.app.com/bundle.js"},
                    "response": {"status": 200, "content": {"mimeType": "text/javascript"}},
                },
                # 除外対象: 3rd-party
                {
                    "request": {
                        "method": "POST",
                        "url": "https://www.google-analytics.com/collect",
                    },
                    "response": {"status": 204, "content": {"mimeType": "text/plain"}},
                },
            ]
        }
    }
    actions = extract_api_actions(har)
    names = sorted(a.name for a in actions)
    assert names == ["users.create", "users.get", "users.list"]
    # GET /v1/users と GET /v1/users/42 は別アクション(pattern が違う)
    patterns = sorted(a.observed.urlPattern for a in actions)
    assert patterns == ["/v1/users", "/v1/users", "/v1/users/:id"]
