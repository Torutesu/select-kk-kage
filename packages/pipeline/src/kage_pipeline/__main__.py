"""
CLI entry: uv run python -m kage_pipeline <bundle.kage.zip> [--out ir.json] [--project-name slug]

Day 3 時点で動くのは bundle 展開 + HAR → ApiAction + events → Screen の最小パスのみ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rich.console import Console

from .bundle import BundleError, cleanup_tempdir, load_bundle
from .ir_builder import IRBuildError, build_ir


_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _default_project_name(bundle_path: Path) -> str:
    """<name>-<ts>.kage.zip → <name> or stem そのまま (slug 制約を満たす範囲)。"""
    stem = bundle_path.name
    if stem.endswith(".kage.zip"):
        stem = stem[: -len(".kage.zip")]
    else:
        stem = bundle_path.stem
    # 末尾のタイムスタンプ (-YYYY-MM-DDThh-mm-ss-...) を剥がす
    stem = re.sub(r"-\d{4}-\d{2}-\d{2}t.*$", "", stem, flags=re.IGNORECASE)
    stem = stem.lower()
    # slug 制約へ寄せる
    stem = re.sub(r"[^a-z0-9-]+", "-", stem).strip("-")
    return stem or "kage-project"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kage-pipeline")
    parser.add_argument("bundle", type=Path, help="capture bundle (.kage.zip) or extracted dir")
    parser.add_argument("--out", type=Path, default=Path("ir.json"), help="output IR JSON path")
    parser.add_argument(
        "--project-name",
        type=str,
        default=None,
        help="project slug (lowercase alphanumeric + hyphens). default: derived from bundle name.",
    )
    parser.add_argument(
        "--keep-extracted",
        action="store_true",
        help="zip 展開先の tempdir を残す(デバッグ用)",
    )
    args = parser.parse_args(argv)

    console = Console(stderr=True)

    project_name = args.project_name or _default_project_name(args.bundle)
    if not _SLUG_RE.match(project_name):
        console.print(
            f"[red]invalid --project-name: {project_name!r} (must match {_SLUG_RE.pattern})[/red]"
        )
        return 2

    try:
        bundle = load_bundle(args.bundle)
    except BundleError as e:
        console.print(f"[red]bundle error:[/red] {e}")
        return 1

    console.print(f"[cyan]bundle loaded:[/cyan] {bundle.root}")
    if bundle.missing:
        console.print(f"[yellow]optional files missing:[/yellow] {bundle.missing}")

    try:
        ir = build_ir(bundle, project_name=project_name)
    except IRBuildError as e:
        console.print(f"[red]{e}[/red]")
        if args.bundle.is_file() and not args.keep_extracted:
            cleanup_tempdir(bundle)
        return 1

    # Zod の `.optional()` は undefined のみ受理(null 不可)なので None は落とす。
    args.out.write_text(
        json.dumps(
            ir.model_dump(by_alias=True, mode="json", exclude_none=True),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    console.print(
        f"[green]✓ IR written:[/green] {args.out}  "
        f"(screens={len(ir.screens)}, apiActions={len(ir.apiActions)})"
    )

    if args.bundle.is_file() and not args.keep_extracted:
        cleanup_tempdir(bundle)

    return 0


if __name__ == "__main__":
    sys.exit(main())
