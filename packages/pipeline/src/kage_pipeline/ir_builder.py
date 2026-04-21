"""
各 extractor の出力を束ねて IR オブジェクトを組み立てる。

Day 3 時点で入るのは Screen と ApiAction のみ。
Entity / Transition / Component tree / DataBinding / SharedState は Day 4 以降。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .bundle import CaptureBundle, read_jsonl
from .components.api_extractor import extract_api_actions
from .components.screen_extractor import extract_screens
from .integrity import validate_ir_integrity
from .ir_schema import IR, IRSource


_DEFAULT_VIEWPORT_WIDTH = 1440.0  # recorder の default と揃える


class IRBuildError(Exception):
    """IR 組み立て失敗。integrity チェック失敗はここに集約する。"""


def _coerce_iso(value: Any) -> str:
    """metadata.startedAt は ISO8601 前提だが Zod は datetime() を要求。そのまま返す。"""
    if isinstance(value, str):
        return value
    return datetime.now(tz=timezone.utc).isoformat()


def build_ir(bundle: CaptureBundle, project_name: str) -> IR:
    har_raw = json.loads(bundle.har_path.read_text(encoding="utf-8"))
    events = read_jsonl(bundle.events_path)
    dom_snapshots = read_jsonl(bundle.dom_snapshots_path)

    api_actions = extract_api_actions(har_raw)
    screens = extract_screens(
        events,
        dom_snapshots=dom_snapshots,
        viewport_width=_DEFAULT_VIEWPORT_WIDTH,
    )

    metadata = bundle.metadata
    duration_ms = float(metadata.get("durationMs") or 0)
    target_url = metadata.get("targetUrl") or ""

    source = IRSource(
        targetUrl=target_url,
        recordedAt=_coerce_iso(metadata.get("startedAt")),
        durationSeconds=duration_ms / 1000.0,
        captureTool="kage-capture",
    )

    ir = IR(
        version="1.0.0",
        source=source,
        projectName=project_name,
        screens=screens,
        apiActions=api_actions,
        hasAuth=False,
    )

    errors = validate_ir_integrity(ir)
    if errors:
        raise IRBuildError("IR integrity errors:\n  - " + "\n  - ".join(errors))

    return ir
