"""
HAR → ApiAction リスト。

Day 3 時点の方針:
- deterministic のみ (LLM は使わない)
- URL / method / レスポンス例を観測ベースで記録
- urlPattern は heuristic:
    * 数値セグメントを `:id` に置換
    * UUID-like セグメントを `:id` に置換
    * それ以外はそのまま残す
- kind は method ベース:
    * GET → query
    * POST/PUT/PATCH/DELETE → mutation
- 自アプリの API と判断する基準(ざっくり):
    * content-type: application/json (Accept / Response)
    * もしくは URL 上の拡張子が無い
    * 3rd-party analytics (google-analytics, sentry, segment, doubleclick, etc.) は除外
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..ir_schema import ApiAction, ApiActionObserved, HttpMethod


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_DIGITS_RE = re.compile(r"^\d+$")
_HEX_ID_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)

# 3rd-party ドメイン(主要アナリティクス/広告/エラートラッキング)。完全一致ではなく suffix 判定。
_THIRD_PARTY_SUFFIXES = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "sentry.io",
    "ingest.sentry.io",
    "segment.io",
    "mixpanel.com",
    "amplitude.com",
    "posthog.com",
    "datadoghq.com",
    "intercom.io",
    "hotjar.com",
    "fullstory.com",
    "facebook.com",
    "fbcdn.net",
)

_STATIC_EXT_RE = re.compile(
    r"\.(js|mjs|css|png|jpg|jpeg|gif|svg|webp|woff2?|ttf|ico|map|mp4|webm|avif|txt)(\?|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HarEntry:
    method: HttpMethod
    url: str
    status: int
    request_body: Any | None
    response_body: Any | None
    response_mime: str | None


def parse_har(har: dict[str, Any]) -> list[HarEntry]:
    """HAR v1.2 の `log.entries` をフラット化。"""
    out: list[HarEntry] = []
    for e in har.get("log", {}).get("entries", []) or []:
        req = e.get("request", {})
        resp = e.get("response", {})
        method = (req.get("method") or "GET").upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        url = req.get("url", "")
        status = int(resp.get("status") or 0)
        response_mime = (resp.get("content") or {}).get("mimeType")
        response_text = (resp.get("content") or {}).get("text")
        response_body: Any | None = None
        if response_mime and "json" in response_mime.lower():
            response_body = _try_json(response_text)

        request_text = (req.get("postData") or {}).get("text")
        request_mime = (req.get("postData") or {}).get("mimeType", "") or ""
        request_body: Any | None = None
        if "json" in request_mime.lower():
            request_body = _try_json(request_text)

        out.append(
            HarEntry(
                method=method,  # type: ignore[arg-type]
                url=url,
                status=status,
                request_body=request_body,
                response_body=response_body,
                response_mime=response_mime,
            )
        )
    return out


def _try_json(text: str | None) -> Any | None:
    if not text:
        return None
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _is_third_party(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in _THIRD_PARTY_SUFFIXES)


def _is_static_asset(url: str) -> bool:
    return bool(_STATIC_EXT_RE.search(url))


def _normalize_segment(seg: str) -> str:
    if not seg:
        return seg
    if _UUID_RE.match(seg):
        return ":id"
    if _DIGITS_RE.match(seg):
        return ":id"
    if _HEX_ID_RE.match(seg):
        return ":id"
    return seg


def derive_url_pattern(url: str) -> str:
    """
    /users/42/projects/abc-def-123 → /users/:id/projects/:id
    クエリは落とす。
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s != ""]
    normalized = [_normalize_segment(s) for s in segments]
    return "/" + "/".join(normalized) if normalized else "/"


def derive_action_name(method: HttpMethod, pattern: str) -> str:
    """
    heuristic: 最後の非:id セグメントを名詞として採用。
    method + pattern → 例:
        GET  /api/users        → users.list
        GET  /api/users/:id    → users.get
        POST /api/users        → users.create
        PUT  /api/users/:id    → users.update
        PATCH /api/users/:id   → users.update
        DELETE /api/users/:id  → users.delete
    """
    segs = [s for s in pattern.split("/") if s and s != ":id"]
    resource = segs[-1] if segs else "root"
    # api prefix は除外
    if resource == "api" and len(segs) >= 2:
        resource = segs[-2]
    has_id = ":id" in pattern

    op: str
    if method == "GET":
        op = "get" if has_id else "list"
    elif method == "POST":
        op = "create"
    elif method in ("PUT", "PATCH"):
        op = "update"
    else:  # DELETE (HttpMethod は Literal で網羅済み)
        op = "delete"

    return f"{resource}.{op}"


def _kind_of(method: HttpMethod) -> str:
    return "query" if method == "GET" else "mutation"


def extract_api_actions(har: dict[str, Any]) -> list[ApiAction]:
    """
    HAR 全体 → ApiAction リスト。

    同じ (method, urlPattern) にマージし、最初のサンプルだけ残す。
    """
    entries = parse_har(har)
    grouped: dict[tuple[HttpMethod, str], ApiAction] = {}

    for e in entries:
        parsed = urlparse(e.url)
        host = parsed.hostname or ""
        if _is_third_party(host):
            continue
        if _is_static_asset(e.url):
            continue
        # JSON でもなく POST でもない GET の場合、ドキュメント取得の可能性大なのでスキップ
        is_json_resp = (e.response_mime or "").lower().find("json") >= 0
        if e.method == "GET" and not is_json_resp and not parsed.path.startswith("/api"):
            continue

        pattern = derive_url_pattern(e.url)
        key = (e.method, pattern)
        if key in grouped:
            continue

        grouped[key] = ApiAction(
            id=uuid.uuid4(),
            name=derive_action_name(e.method, pattern),
            kind=_kind_of(e.method),  # type: ignore[arg-type]
            observed=ApiActionObserved(
                method=e.method,
                urlPattern=pattern,
                sampleRequest=e.request_body,
                sampleResponse=e.response_body,
            ),
            entityIds=[],
            confidence="low",
        )

    return list(grouped.values())
