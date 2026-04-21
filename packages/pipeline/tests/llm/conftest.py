"""VCR configuration shared by tests/llm/*."""

from __future__ import annotations

from pathlib import Path

import pytest


CASSETTES_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture(scope="module")
def vcr_config() -> dict:
    return {
        # once: cassette 無ければ記録、あれば再生のみ(API を叩かない)
        "record_mode": "once",
        "match_on": ("method", "scheme", "host", "port", "path", "query", "body"),
        # API key を cassette に書かない
        "filter_headers": [
            ("x-api-key", "FILTERED"),
            ("authorization", "FILTERED"),
            ("anthropic-version", "FILTERED"),
        ],
        "filter_post_data_parameters": [],
        "cassette_library_dir": str(CASSETTES_DIR),
    }


def require_cassette_or_skip(cassette_name: str) -> None:
    """cassette ファイルが無ければ分かりやすいメッセージで skip。"""
    path = CASSETTES_DIR / cassette_name
    if not path.exists():
        pytest.skip(
            f"LLM cassette missing: {path.relative_to(CASSETTES_DIR.parent.parent)}\n"
            "To record it, run:\n"
            "    ANTHROPIC_API_KEY=sk-ant-... uv run python -m kage_pipeline.tools.record_cassettes\n"
            "Then commit the cassette under packages/pipeline/tests/llm/cassettes/."
        )
