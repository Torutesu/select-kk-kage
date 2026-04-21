"""
API response の "envelope" (data/result/items/pagination) を剥がして
純粋なデータ部分だけ返す deterministic な正規化。

クラスタリングの前段。envelope の違い(data vs result vs items)で
同じ Entity を取り出す ApiAction がバラバラに見えるのを防ぐ。

ルール:
  1. 単一 key で key が envelope 名に該当 → その value を unwrap
     (data / result / items / records / rows / list / content)
  2. 複数 key で、そのうちどれかが meta 系 (meta / pagination / page /
     total / totalCount / links / _links / nextCursor / hasMore) なら、
     meta 系を落として残りを unwrap
  3. 単一 key で key が複数形 "xxxS" なら単数化した entity 名とみなして unwrap
     (例: {"users": [...]} → [...])
  4. 成功 envelope {"success": true, "data": {...}} は data を unwrap
  5. 判定不能なら元のまま返す

副作用として「envelope の元 key 名」を hint として返す。
クラスタリング時の命名推定に使える。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ENVELOPE_KEYS: set[str] = {
    "data",
    "result",
    "results",
    "items",
    "records",
    "rows",
    "list",
    "content",
    "payload",
}

META_KEYS: set[str] = {
    "meta",
    "pagination",
    "page",
    "pageSize",
    "per_page",
    "perPage",
    "total",
    "totalCount",
    "total_count",
    "count",
    "links",
    "_links",
    "nextCursor",
    "next_cursor",
    "prevCursor",
    "prev_cursor",
    "hasMore",
    "has_more",
    "hasNext",
    "cursor",
    "success",
    "ok",
    "error",
    "status",
    "code",
    "message",
}


@dataclass
class NormalizedResponse:
    """正規化後の値 + 由来のヒント。"""

    value: Any
    hint_key: str | None = None  # envelope を剥がしたときの元 key 名
    was_wrapped: bool = False


def normalize_response(body: Any) -> NormalizedResponse:
    """
    Envelope 剥がしをトップレベルのみ 1 回適用する(再帰ではない)。
    観測された shape の違いを吸収するのが目的。
    """
    if not isinstance(body, dict):
        return NormalizedResponse(value=body)

    keys = list(body.keys())
    if not keys:
        return NormalizedResponse(value=body)

    # Case 1 & 3 & 4: 単一 key
    if len(keys) == 1:
        only = keys[0]
        value = body[only]
        if only in ENVELOPE_KEYS:
            return NormalizedResponse(value=value, hint_key=only, was_wrapped=True)
        if _looks_like_plural(only):
            return NormalizedResponse(
                value=value, hint_key=_singularize(only), was_wrapped=True
            )
        return NormalizedResponse(value=body)

    # Case 2: 複数 key、どれかが meta 系 → meta を落として残りを unwrap
    data_keys = [k for k in keys if k not in META_KEYS]
    meta_keys = [k for k in keys if k in META_KEYS]
    # 成功 envelope {"success": true, "data": {...}} もここで吸収
    if meta_keys and len(data_keys) == 1:
        dk = data_keys[0]
        value = body[dk]
        hint: str | None = dk
        if dk in ENVELOPE_KEYS:
            hint = dk
        elif _looks_like_plural(dk):
            hint = _singularize(dk)
        return NormalizedResponse(value=value, hint_key=hint, was_wrapped=True)

    # 判定不能なら元のまま
    return NormalizedResponse(value=body)


def collect_field_types(value: Any) -> dict[str, str]:
    """
    正規化後の value からフィールド名 → 観測型のマップを作る。
    配列なら最初の要素を使う。dict 以外は {} を返す。

    観測型は crude: "string" / "int" / "float" / "bool" / "null" / "array" /
    "object" / "datetime-like" / "uuid-like"。後段で LLM が精度を上げる。
    """
    sample = _pick_sample(value)
    if not isinstance(sample, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in sample.items():
        out[k] = _crude_type(v)
    return out


def _pick_sample(value: Any) -> Any:
    if isinstance(value, list) and value:
        # 先頭 dict を優先、無ければ先頭値
        for item in value:
            if isinstance(item, dict):
                return item
        return value[0]
    return value


_UUID_RE_LEN = 36  # "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"


def _crude_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, str):
        # datetime-like: ISO8601 風 or RFC3339 風
        if _looks_like_datetime(v):
            return "datetime-like"
        if len(v) == _UUID_RE_LEN and v.count("-") == 4:
            return "uuid-like"
        return "string"
    return "string"


def _looks_like_datetime(s: str) -> bool:
    # ざっくり: "YYYY-MM-DD" で始まり T か space を含む
    if len(s) < 10:
        return False
    if s[4] != "-" or s[7] != "-":
        return False
    return s[0:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit()


def _looks_like_plural(k: str) -> bool:
    """「es」「s」で終わり、かつ長さ 2 以上、かつ全部小文字 or camelCase。"""
    if len(k) < 3:
        return False
    if k.endswith("ies") and len(k) > 3:
        return True
    if k.endswith("es") and len(k) > 3:
        return True
    return k.endswith("s")


def _singularize(k: str) -> str:
    # 単純な逆変換(精密さより再現性)
    if k.endswith("ies") and len(k) > 3:
        return k[:-3] + "y"
    if k.endswith("ses") or k.endswith("xes") or k.endswith("zes"):
        return k[:-2]
    if k.endswith("s") and len(k) > 1:
        return k[:-1]
    return k
