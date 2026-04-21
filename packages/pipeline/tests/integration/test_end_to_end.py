"""End-to-end smoke test: bundle → build_ir → integrity-clean IR JSON."""

from __future__ import annotations

import json
from pathlib import Path

from kage_pipeline.bundle import load_bundle
from kage_pipeline.integrity import validate_ir_integrity
from kage_pipeline.ir_builder import build_ir


def test_end_to_end(hn_minimal_dir: Path, tmp_path: Path) -> None:
    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")
    assert ir.version == "1.0.0"
    assert ir.projectName == "hn-smoke"
    assert ir.source.captureTool == "kage-capture"
    # HN smoke なら navigation が1件以上あるはず → Screen が 1+ 個
    assert len(ir.screens) >= 1
    # HN は JSON API を持たない → apiActions はおそらく 0
    # integrity error は 0 件であること
    assert validate_ir_integrity(ir) == []

    # JSON 書き出しラウンドトリップ:出力された JSON が再 load 可能
    out = tmp_path / "ir.json"
    out.write_text(
        json.dumps(
            ir.model_dump(by_alias=True, mode="json", exclude_none=True),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["version"] == "1.0.0"
    assert loaded["projectName"] == "hn-smoke"


def test_cli_entry(hn_minimal_dir: Path, tmp_path: Path) -> None:
    from kage_pipeline.__main__ import main

    out = tmp_path / "ir.json"
    rc = main([str(hn_minimal_dir), "--out", str(out), "--project-name", "hn-smoke"])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == "1.0.0"
    assert data["projectName"] == "hn-smoke"
    assert len(data["screens"]) >= 1
