"""
Integration test: hn-minimal fixture に対して LLM を呼ばずに Stage 1+3 だけで
screens[].root.children.* が埋まることを確認する。
"""

from __future__ import annotations

from pathlib import Path

from kage_pipeline.bundle import load_bundle
from kage_pipeline.integrity import validate_ir_integrity
from kage_pipeline.ir_builder import build_ir
from kage_pipeline.ir_schema import Component


def _count_nodes(c: Component) -> int:
    return 1 + sum(_count_nodes(ch) for ch in c.children)


def _collect_kinds(c: Component, out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    out.append(c.kind)
    for ch in c.children:
        _collect_kinds(ch, out)
    return out


def test_hn_component_tree_is_populated(hn_minimal_dir: Path) -> None:
    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")

    # HN の /newest 画面(2 つ目の navigation)は 100 ノード DOM から
    # Stage 1 + pruner でそこそこの kind を引けるはず
    newest = next((s for s in ir.screens if s.slug == "newest"), None)
    assert newest is not None, "expected a screen with slug=newest"

    total = _count_nodes(newest.root)
    assert total > 10, f"component tree too small: {total} nodes"

    kinds = _collect_kinds(newest.root)
    # HN はテーブルレイアウトなので Table/DataTable と Link が必ず混ざる
    assert any(k in ("Table", "DataTable") for k in kinds), kinds
    assert "Link" in kinds, kinds

    # integrity 0 件
    assert validate_ir_integrity(ir) == []
