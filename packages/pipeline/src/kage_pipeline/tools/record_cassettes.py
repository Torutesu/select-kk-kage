"""
Record VCR cassettes for tests/llm/.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... uv run python -m kage_pipeline.tools.record_cassettes

What it does:
    - Loads .env for ANTHROPIC_API_KEY
    - Runs pytest tests/llm/ with VCR record_mode=once
    - Cassettes that already exist are kept (no re-record)
    - New/missing cassettes are recorded into tests/llm/cassettes/
    - Reports which cassettes were created and prompts the user to commit them

Rationale:
    Devs rarely have API key. CI doesn't either. We keep tests offline-safe
    by shipping cassettes in git. This tool is the one place that actually
    hits the API.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
CASSETTES_DIR = PACKAGE_ROOT / "tests" / "llm" / "cassettes"


def _fail(msg: str, code: int = 1) -> int:
    print(f"\033[31merror:\033[0m {msg}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PACKAGE_ROOT / ".env", override=False)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _fail(
            "ANTHROPIC_API_KEY is not set.\n"
            "Put it in packages/pipeline/.env (see .env.example) or export it."
        )

    CASSETTES_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in CASSETTES_DIR.iterdir() if p.is_file()}

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(PACKAGE_ROOT / "tests" / "llm"),
        "-v",
        "-o",
        "addopts=",  # disable any default addopts that might change behavior
        "--record-mode=once",
    ]
    print(f"[record_cassettes] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(PACKAGE_ROOT))
    if proc.returncode != 0:
        return _fail(
            f"pytest exited with {proc.returncode}. "
            "New cassettes (if any) still on disk; please review before commit.",
            code=proc.returncode,
        )

    after = {p.name for p in CASSETTES_DIR.iterdir() if p.is_file()}
    new = sorted(after - existing)
    if not new:
        print("[record_cassettes] no new cassettes created.")
        return 0

    print(f"[record_cassettes] recorded {len(new)} new cassette(s):")
    for name in new:
        print(f"  - tests/llm/cassettes/{name}")
    print(
        "\nNext steps:\n"
        "  git add packages/pipeline/tests/llm/cassettes/\n"
        "  git commit -m 'test(pipeline): record LLM cassettes'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
