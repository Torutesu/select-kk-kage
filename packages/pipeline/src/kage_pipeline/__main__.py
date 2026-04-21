"""
CLI entry: uv run python -m kage_pipeline <bundle.kage.zip> [options]

Deterministic の最小パス (bundle 展開 + HAR → ApiAction + events → Screen +
transitions) はデフォルトで動く。

LLM を使う Entity 推論は opt-in:
    uv run python -m kage_pipeline <bundle.zip> --infer-entities
    (ANTHROPIC_API_KEY が必要、コスト上限は KAGE_LLM_COST_LIMIT_USD で制御)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .bundle import BundleError, cleanup_tempdir, load_bundle
from .components.entity_inferer import infer_entities
from .integrity import validate_ir_integrity
from .ir_builder import IRBuildError, build_ir
from .llm.client import AnthropicClient, LlmSettings, MissingApiKeyError
from .llm.cost_logger import CostLogger


_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _default_project_name(bundle_path: Path) -> str:
    stem = bundle_path.name
    if stem.endswith(".kage.zip"):
        stem = stem[: -len(".kage.zip")]
    else:
        stem = bundle_path.stem
    stem = re.sub(r"-\d{4}-\d{2}-\d{2}t.*$", "", stem, flags=re.IGNORECASE)
    stem = stem.lower()
    stem = re.sub(r"[^a-z0-9-]+", "-", stem).strip("-")
    return stem or "kage-project"


def _default_log_dir(project_name: str) -> Path:
    env_override = os.environ.get("KAGE_LOG_DIR")
    if env_override:
        return Path(env_override)
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return Path(".kage-logs") / f"{project_name}-{ts}"


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
    parser.add_argument(
        "--infer-entities",
        action="store_true",
        help="LLM (Sonnet) で apiActions → entities を推論する (ANTHROPIC_API_KEY 要)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="LLM cost log 等の出力先。default: ./.kage-logs/<project>-<ts>/",
    )
    args = parser.parse_args(argv)

    load_dotenv(override=False)

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

    if args.infer_entities:
        log_dir = args.log_dir or _default_log_dir(project_name)
        try:
            entities, updated_actions = asyncio.run(
                _run_entity_inference(ir, log_dir=log_dir, console=console)
            )
            ir = ir.model_copy(
                update={
                    "entities": entities,
                    "apiActions": updated_actions,
                    "hasAuth": ir.hasAuth or any(e.name == "User" for e in entities),
                }
            )
            errors = validate_ir_integrity(ir)
            if errors:
                console.print("[red]IR integrity errors after entity inference:[/red]")
                for err in errors:
                    console.print(f"  - {err}")
                if args.bundle.is_file() and not args.keep_extracted:
                    cleanup_tempdir(bundle)
                return 1
        except MissingApiKeyError as e:
            console.print(f"[red]entity inference: {e}[/red]")
            if args.bundle.is_file() and not args.keep_extracted:
                cleanup_tempdir(bundle)
            return 1

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
        f"(screens={len(ir.screens)}, apiActions={len(ir.apiActions)}, "
        f"transitions={len(ir.transitions)}, entities={len(ir.entities)})"
    )

    if args.bundle.is_file() and not args.keep_extracted:
        cleanup_tempdir(bundle)

    return 0


async def _run_entity_inference(ir, *, log_dir: Path, console: Console):  # type: ignore[no-untyped-def]
    log_dir.mkdir(parents=True, exist_ok=True)
    cost_logger = CostLogger(
        log_dir / "llm.log.jsonl",
        limit_usd=float(os.environ.get("KAGE_LLM_COST_LIMIT_USD", "1.00")),
    )
    client = AnthropicClient(cost_logger=cost_logger, settings=LlmSettings.from_env())
    console.print(
        f"[cyan]inferring entities with sonnet[/cyan] (log: {log_dir / 'llm.log.jsonl'})"
    )
    return await infer_entities(
        api_actions=ir.apiActions,
        screens=ir.screens,
        has_auth=ir.hasAuth,
        llm_client=client,
    )


if __name__ == "__main__":
    sys.exit(main())
