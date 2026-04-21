#!/usr/bin/env python
"""
Capture bundle (.kage.zip) から最小 fixture ディレクトリを作る。

使い方:
    python tests/fixtures/make_minimal.py \
        /path/to/foo.kage.zip \
        tests/fixtures/foo-minimal

切り出しロジック(再現可能に):
  - recording.webm           → 削除(pipeline は動画を読まない)
  - a11y_snapshots.jsonl     → 最後の 1 行 + tree 配列を先頭 N ノードに切り詰め
  - dom_snapshots.jsonl      → 最後の 1 行 + nodes/layout 配列を先頭 N エントリに切り詰め
                               (最後 = 最もページが展開された状態の snapshot)
  - events.jsonl             → 全件
  - network.har              → 全件
  - screenshots/             → 先頭 3 枚
  - metadata.json            → そのまま

A11y と DOM の snapshot は 1 行でも 100-600 KB に膨らむ。JSON として valid を維持
したまま内部配列を truncate する。

目標サイズ: 500 KB 以下
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


SCREENSHOT_COUNT_LIMIT = 3
A11Y_TREE_NODE_LIMIT = 20  # 1 snapshot あたりの tree ノード上限
DOM_NODE_LIMIT = 100  # 1 snapshot あたりの nodes/layout エントリ上限


def _read_jsonl_lines(src: Path) -> list[str]:
    with src.open(encoding="utf-8") as fr:
        return [line for line in fr if line.strip()]


def _truncate_parallel_arrays(
    d: dict[str, list[object]],
    limit: int,
) -> None:
    """各キーの list をすべて [:limit] に in-place 切り詰め。"""
    for k, v in d.items():
        if isinstance(v, list) and len(v) > limit:
            d[k] = v[:limit]


def truncate_a11y_last(src: Path, dst: Path, tree_node_limit: int) -> bool:
    """a11y_snapshots.jsonl の最後の行だけ抜いて tree を切って書き出す。"""
    lines = _read_jsonl_lines(src)
    if not lines:
        dst.write_text("", encoding="utf-8")
        return False
    try:
        obj = json.loads(lines[-1])
    except json.JSONDecodeError:
        return False
    tree = obj.get("tree")
    if isinstance(tree, list) and len(tree) > tree_node_limit:
        obj["_truncatedFromNodes"] = len(tree)
        obj["tree"] = tree[:tree_node_limit]
    dst.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def truncate_dom_last(src: Path, dst: Path, node_limit: int) -> bool:
    """
    dom_snapshots.jsonl の最後の行を抜いて:
    - documents[0].nodes の各平行配列を node_limit に揃えて切る
    - documents[0].layout の各平行配列を同様に切る
    - strings はそのまま(サイズ寄与が小さい、かつ参照整合のため)
    """
    lines = _read_jsonl_lines(src)
    if not lines:
        dst.write_text("", encoding="utf-8")
        return False
    try:
        obj = json.loads(lines[-1])
    except json.JSONDecodeError:
        return False

    snap = obj.get("snapshot")
    if isinstance(snap, dict):
        documents = snap.get("documents")
        if isinstance(documents, list):
            for doc in documents:
                nodes = doc.get("nodes") if isinstance(doc, dict) else None
                if isinstance(nodes, dict):
                    orig = len(nodes.get("parentIndex", []))
                    _truncate_parallel_arrays(nodes, node_limit)
                    doc["_truncatedFromNodes"] = orig
                layout = doc.get("layout") if isinstance(doc, dict) else None
                if isinstance(layout, dict):
                    _truncate_parallel_arrays(layout, node_limit)
    dst.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def copy_limited_dir(src: Path, dst: Path, limit: int) -> int:
    """dir の先頭 limit 個だけコピー。コピー個数を返す。"""
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in sorted(src.iterdir()):
        if item.is_file():
            shutil.copy2(item, dst / item.name)
            count += 1
            if count >= limit:
                break
    return count


def make_minimal(src_root: Path, out_dir: Path) -> None:
    if out_dir.exists():
        raise SystemExit(f"out_dir already exists: {out_dir}")
    out_dir.mkdir(parents=True)

    # 必須: metadata.json
    shutil.copy2(src_root / "metadata.json", out_dir / "metadata.json")

    # 必須: events + HAR は全件
    shutil.copy2(src_root / "events.jsonl", out_dir / "events.jsonl")
    shutil.copy2(src_root / "network.har", out_dir / "network.har")

    # 切り詰め: 両方とも「最後の 1 行」+ 内部配列切り詰め
    dom_kept = truncate_dom_last(
        src_root / "dom_snapshots.jsonl",
        out_dir / "dom_snapshots.jsonl",
        DOM_NODE_LIMIT,
    )
    a11y_kept = truncate_a11y_last(
        src_root / "a11y_snapshots.jsonl",
        out_dir / "a11y_snapshots.jsonl",
        A11Y_TREE_NODE_LIMIT,
    )

    # 切り詰め: screenshots
    shot_count = copy_limited_dir(
        src_root / "screenshots",
        out_dir / "screenshots",
        SCREENSHOT_COUNT_LIMIT,
    )

    # recording.webm は削除ポリシー:そもそもコピーしない
    total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"minimal fixture ready: {out_dir}", file=sys.stderr)
    print(
        f"  events.jsonl          (full)\n"
        f"  network.har           (full)\n"
        f"  dom_snapshots.jsonl   last line kept (nodes trimmed to {DOM_NODE_LIMIT}): {dom_kept}\n"
        f"  a11y_snapshots.jsonl  last line kept (tree trimmed to {A11Y_TREE_NODE_LIMIT}): {a11y_kept}\n"
        f"  screenshots/          {shot_count} files\n"
        f"  metadata.json         (full)\n"
        f"  TOTAL                 {total:,} bytes ({total / 1024:.1f} KB)",
        file=sys.stderr,
    )
    if total > 500 * 1024:
        print(f"WARNING: fixture exceeds 500KB target ({total / 1024:.1f}KB)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a minimal fixture directory from a capture bundle."
    )
    parser.add_argument("src", type=Path, help="source .kage.zip OR extracted dir")
    parser.add_argument("out", type=Path, help="output fixture directory (must not exist)")
    args = parser.parse_args(argv)

    if args.src.is_file() and args.src.suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="kage-minimal-") as tmp:
            with zipfile.ZipFile(args.src) as zf:
                zf.extractall(tmp)
            make_minimal(Path(tmp), args.out)
    elif args.src.is_dir():
        make_minimal(args.src, args.out)
    else:
        parser.error(f"expected .kage.zip or directory: {args.src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
