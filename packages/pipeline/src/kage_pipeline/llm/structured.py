"""
pydantic BaseModel → Anthropic tool-use JSON schema 変換。

Anthropic 0.96.0 では response_format ではなく tool-use で structured output を
強制するのが推奨。tool_choice={"type":"tool","name":<tool_name>} で 1 tool に固定し、
input_schema に pydantic の model_json_schema() を渡す。

戻ってきた response.content の tool_use block の input を pydantic で再バリデートすると、
型付けされた BaseModel として扱える。
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def pydantic_to_anthropic_tool(
    model_cls: type[BaseModel],
    *,
    tool_name: str,
    description: str,
) -> dict[str, Any]:
    """
    pydantic BaseModel クラスを Anthropic Messages API の tool 定義に変換。

    Anthropic の input_schema は JSON Schema draft 2020-12 に近いが、
    一部メタデータ ($defs, $ref) は pydantic 標準で通るので基本そのまま渡す。
    """
    schema = model_cls.model_json_schema()
    return {
        "name": tool_name,
        "description": description,
        "input_schema": schema,
    }


def parse_tool_use_output(
    tool_input: dict[str, Any],
    model_cls: type[T],
) -> T:
    """
    Anthropic tool_use block の input (dict) を pydantic BaseModel で検証して返す。
    ValidationError はそのまま上位に伝播(caller がリトライ判断する)。
    """
    try:
        return model_cls.model_validate(tool_input)
    except ValidationError:
        raise
