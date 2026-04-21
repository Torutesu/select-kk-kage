"""
URL を「論理画面キー」に正規化する。

ルール (Week 1 Day 5 時点):
  - scheme は無視
  - host は維持(サブドメイン違いは別画面扱い)
  - path は維持
  - query string は捨てる
    (例: /search?q=foo は /search と同じ論理画面)
  - fragment (#section) は捨てる
  - path 末尾のスラッシュは剥がす("/foo/" と "/foo" は同じ)

Transition 推論と Screen dedupe の両方がこの関数を参照する。
"""

from __future__ import annotations

from urllib.parse import urlparse


def url_key(url: str) -> str:
    """正規化キー。比較のみに使う(表示用は originalUrl を使う)。"""
    if not url:
        return ""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return f"{host}{path}"
