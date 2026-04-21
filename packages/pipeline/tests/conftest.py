"""Shared pytest fixtures for pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def hn_minimal_dir() -> Path:
    d = FIXTURES_DIR / "hn-minimal"
    if not d.is_dir():
        pytest.skip(f"fixture missing: {d}")
    return d


@pytest.fixture(scope="session")
def hn_minimal_har(hn_minimal_dir: Path) -> dict[str, Any]:
    return json.loads((hn_minimal_dir / "network.har").read_text(encoding="utf-8"))
