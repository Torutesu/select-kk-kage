"""
LLM のトークン使用量・コストを runs/<id>/llm.log.jsonl に append する。

コスト上限を超過したら RuntimeError を投げる(暴走防止)。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


# USD / 1M tokens。Anthropic 公式料金(2026-04 時点、haiku-4.5/sonnet-4.6/opus-4.7)。
PRICING_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
}


def normalize_model(model: str) -> str:
    """SDK が返すバージョン付きモデル名 (e.g. claude-haiku-4-5-20251001) を正規化。"""
    for k in PRICING_PER_MTOK:
        if model.startswith(k):
            return k
    return model


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    norm = normalize_model(model)
    rate = PRICING_PER_MTOK.get(norm)
    if not rate:
        return 0.0  # 未登録モデルは 0 として扱う(破綻させない)
    return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000


class CostLimitExceeded(RuntimeError):
    """1 bundle あたりの累積コストが上限を超えたとき。"""


class CostLogger:
    """
    プロセス内 (= 1 pipeline 実行) に 1 インスタンス。
    スレッドセーフ(asyncio からは 1 イベントループでしか動かさない前提)。
    """

    def __init__(self, log_path: Path, *, limit_usd: float = 1.0) -> None:
        self._log_path = log_path
        self._limit_usd = limit_usd
        self._total_usd = 0.0
        self._lock = threading.Lock()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def total_usd(self) -> float:
        return self._total_usd

    @property
    def limit_usd(self) -> float:
        return self._limit_usd

    def record(
        self,
        *,
        model: str,
        task: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """1 コールを記録。戻り値はそのコールのコスト (USD)。上限超過で CostLimitExceeded。"""
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        with self._lock:
            self._total_usd += cost
            entry = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "model": model,
                "task": task,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
                "cumulative_usd": round(self._total_usd, 6),
            }
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if self._total_usd > self._limit_usd:
                raise CostLimitExceeded(
                    f"LLM cost limit exceeded: ${self._total_usd:.4f} > ${self._limit_usd:.4f} "
                    f"(set KAGE_LLM_COST_LIMIT_USD to raise)"
                )
        return cost
