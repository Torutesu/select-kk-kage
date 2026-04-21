#!/usr/bin/env python
"""
Capture bundle (.kage.zip) から最小 fixture ディレクトリを作る。

使い方:
    python tests/fixtures/make_minimal.py \
        /path/to/foo.kage.zip \
        tests/fixtures/foo-minimal

切り出しロジック(再現可能に):
  - recording.webm           → 削除(pipeline は動画を読まない)
  - a11y_snapshots.jsonl     → 先頭 1 行 + 各行の tree 配列を先頭 N ノードに切り詰め
  - dom_snapshots.jsonl      → 先頭 1 行(DOMSnapshot 本体は触らない、元々小さい)
  - events.jsonl             → 全件
  - network.har              → 全件
  - screenshots/             → 先頭 3 枚
  - metadata.json            → そのまま

A11y の tree は 1 snapshot でも数百KB に膨らむので、node 上限を強制する。
JSON として valid を維持したまま tree を truncate する方針。

目標サイズ: 500KB 以下
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


SNAPSHOT_LINE_LIMIT = 1
SCREENSHOT_COUNT_LIMIT = 3
A11Y_TREE_NODE_LIMIT = 20  # 1 snapshot あたりの tree ノード上限


def truncate_jsonl(src: Path, dst: Path, limit: int) -> int:
    """JSONL の先頭 limit 行だけ dst に書く。書いた行数を返す。"""
    written = 0
    with src.open(encoding="utf-8") as fr, dst.open("w", encoding="utf-8") as fw:
        for line in fr:
            fw.write(line)
            written += 1
            if written >= limit:
                break
    return written


def truncate_a11y_jsonl(src: Path, dst: Path, line_limit: int, tree_node_limit: int) -> int:
    """
    a11y_snapshots.jsonl を先頭 line_limit 行まで + 各行の tree 配列を tree_node_limit に切る。
    JSON 不正行は無視。
    """
    written = 0
    with src.open(encoding="utf-8") as fr, dst.open("w", encoding="utf-8") as fw:
        for line in fr:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            tree = obj.get("tree")
            if isinstance(tree, list) and len(tree) > tree_node_limit:
                obj["tree"] = tree[:tree_node_limit]
                obj["_truncatedFromNodes"] = len(tree)
            fw.write(json.dumps(obj, ensure_ascii=False) + "\n")
            written += 1
            if written >= line_limit:
                break
    return written


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

    # 切り詰め: dom (行数だけ) / a11y (行数 + tree ノード数)
    dom_lines = truncate_jsonl(
        src_root / "dom_snapshots.jsonl",
        out_dir / "dom_snapshots.jsonl",
        SNAPSHOT_LINE_LIMIT,
    )
    a11y_lines = truncate_a11y_jsonl(
        src_root / "a11y_snapshots.jsonl",
        out_dir / "a11y_snapshots.jsonl",
        SNAPSHOT_LINE_LIMIT,
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
        f"  dom_snapshots.jsonl   {dom_lines} lines\n"
        f"  a11y_snapshots.jsonl  {a11y_lines} lines\n"
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
