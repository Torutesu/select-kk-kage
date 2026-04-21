"""
Anthropic SDK wrapper.

責務:
  - API key lazy load (.env + 環境変数)
  - tenacity で指数バックオフ retry
  - CostLogger への記録
  - asyncio.Semaphore で並列度制御

ここで初めて `anthropic` を import する。import 自体は API key 不要。
インスタンス化時(= client を実際に作るとき)に初めて key が要求される。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .cost_logger import CostLogger
from .structured import parse_tool_use_output, pydantic_to_anthropic_tool


T = TypeVar("T", bound=BaseModel)

ModelAlias = Literal["haiku", "sonnet", "opus"]

# Alias → 具体 model ID (2026-04 時点の最新 4.x)
MODEL_IDS: dict[ModelAlias, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}


class MissingApiKeyError(RuntimeError):
    """ANTHROPIC_API_KEY が未設定のときのエラー。"""


@dataclass
class LlmSettings:
    max_concurrent: int = 5
    cost_limit_usd: float = 1.0
    retry_attempts: int = 3
    retry_min_wait_s: float = 1.0
    retry_max_wait_s: float = 30.0

    @classmethod
    def from_env(cls) -> "LlmSettings":
        """環境変数から設定を読む。dotenv は caller 側で load されてる想定。"""
        return cls(
            max_concurrent=int(os.environ.get("KAGE_LLM_MAX_CONCURRENT", "5")),
            cost_limit_usd=float(os.environ.get("KAGE_LLM_COST_LIMIT_USD", "1.00")),
        )


@dataclass
class AnthropicClient:
    """非同期 Anthropic wrapper。lazy init + 並列制御 + cost log + retry。"""

    cost_logger: CostLogger
    settings: LlmSettings = field(default_factory=LlmSettings)
    _sdk_client: Any = field(default=None, init=False, repr=False)
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)

    def _ensure_client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it in .env or shell environment. "
                "For offline tests use VCR cassettes (tests/llm/cassettes/)."
            )
        # Deferred import so just importing this module never needs the API key.
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        self._sdk_client = AsyncAnthropic(api_key=api_key)
        return self._sdk_client

    def _ensure_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent)
        return self._semaphore

    async def call_structured(
        self,
        *,
        model: ModelAlias,
        task: str,
        user_prompt: str,
        output_model: type[T],
        tool_name: str,
        tool_description: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> T:
        """
        Messages API を tool-use 強制モードで叩き、pydantic 型で返す。
        retry + cost log + semaphore 込み。
        """
        from anthropic import APIConnectionError, APIStatusError, APITimeoutError  # noqa: PLC0415

        client = self._ensure_client()
        semaphore = self._ensure_semaphore()
        model_id = MODEL_IDS[model]
        tool = pydantic_to_anthropic_tool(
            output_model, tool_name=tool_name, description=tool_description
        )

        async def _once() -> T:
            async with semaphore:
                kwargs: dict[str, Any] = {
                    "model": model_id,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "tools": [tool],
                    "tool_choice": {"type": "tool", "name": tool_name},
                    "messages": [{"role": "user", "content": user_prompt}],
                }
                if system:
                    kwargs["system"] = system
                resp = await client.messages.create(**kwargs)
                usage = resp.usage
                self.cost_logger.record(
                    model=resp.model,
                    task=task,
                    input_tokens=getattr(usage, "input_tokens", 0),
                    output_tokens=getattr(usage, "output_tokens", 0),
                )
                for block in resp.content:
                    if getattr(block, "type", None) == "tool_use":
                        return parse_tool_use_output(block.input, output_model)
                raise RuntimeError(
                    f"no tool_use block returned for task={task}. "
                    f"stop_reason={resp.stop_reason}"
                )

        retry_exc_types: tuple[type[BaseException], ...] = (
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
        )
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.settings.retry_attempts),
            wait=wait_exponential(
                min=self.settings.retry_min_wait_s,
                max=self.settings.retry_max_wait_s,
            ),
            retry=retry_if_exception_type(retry_exc_types),
            reraise=True,
        ):
            with attempt:
                return await _once()
        raise RuntimeError("unreachable: AsyncRetrying did not yield")
