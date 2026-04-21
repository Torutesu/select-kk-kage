"""
Python 産 IR が TS 側 Zod (`@kage/ir`) で parse 通るかの相互検証テスト。

pnpm / tsx が無い環境 (CI minimal 等) では skip。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kage_pipeline.bundle import load_bundle
from kage_pipeline.ir_builder import build_ir


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_python_ir_passes_ts_zod_parse(hn_minimal_dir: Path, tmp_path: Path) -> None:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("pnpm not available; skipping TS cross-check")

    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")
    out = tmp_path / "ir.json"
    out.write_text(
        json.dumps(
            ir.model_dump(by_alias=True, mode="json", exclude_none=True),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # @kage/capture で tsx が使える(@kage/ir には tsx が未導入)。
    script = f"""
import {{ IRSchema, validateIRIntegrity }} from '@kage/ir';
import fs from 'node:fs';
const raw = JSON.parse(fs.readFileSync({json.dumps(str(out))}, 'utf8'));
const r = IRSchema.safeParse(raw);
if (!r.success) {{
  console.error('zod:', JSON.stringify(r.error.issues));
  process.exit(1);
}}
const issues = validateIRIntegrity(r.data);
if (issues.length) {{
  console.error('integrity:', JSON.stringify(issues));
  process.exit(2);
}}
console.log('ok');
"""
    result = subprocess.run(
        [pnpm, "--filter", "@kage/capture", "exec", "tsx", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, (
        f"TS Zod cross-check failed:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
