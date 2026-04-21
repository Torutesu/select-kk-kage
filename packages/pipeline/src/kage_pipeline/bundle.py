"""
Capture bundle (.kage.zip) の展開とバリデーション。

bundle 内の想定構成(packages/capture/src/recorder.ts 参照):
    recording.webm
    network.har
    dom_snapshots.jsonl
    a11y_snapshots.jsonl
    events.jsonl
    screenshots/*.png
    metadata.json

pipeline は展開後のディレクトリ(CaptureBundle)を入力として動く。
動画そのものはこの段階では読まない(将来 Vision LLM + av で使用)。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "network.har",
    "dom_snapshots.jsonl",
    "a11y_snapshots.jsonl",
    "events.jsonl",
    "metadata.json",
)

OPTIONAL_FILES = (
    "recording.webm",
)


class BundleError(Exception):
    """Bundle の展開・構造検査で失敗したときに投げる。"""


@dataclass
class CaptureBundle:
    """展開済み capture bundle を表す値オブジェクト。"""

    root: Path
    metadata: dict[str, Any]
    missing: list[str] = field(default_factory=list)  # 欠けている「許容」ファイル

    @property
    def har_path(self) -> Path:
        return self.root / "network.har"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def dom_snapshots_path(self) -> Path:
        return self.root / "dom_snapshots.jsonl"

    @property
    def a11y_snapshots_path(self) -> Path:
        return self.root / "a11y_snapshots.jsonl"

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def video_path(self) -> Path | None:
        p = self.root / "recording.webm"
        return p if p.exists() else None


def load_bundle(zip_or_dir: Path, extract_to: Path | None = None) -> CaptureBundle:
    """
    .kage.zip または展開済みディレクトリを受け取って CaptureBundle を返す。

    - zip の場合は extract_to (未指定なら tempdir) に展開
    - dir の場合はそのまま使う
    - REQUIRED_FILES が揃っていなければ BundleError
    - screenshots/ が無くても空配列扱いで通す(headless + no interaction で空になる)
    """
    if zip_or_dir.is_file() and zip_or_dir.suffix == ".zip":
        target = extract_to or Path(tempfile.mkdtemp(prefix="kage-bundle-"))
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_or_dir) as zf:
            _safe_extract(zf, target)
        root = target
    elif zip_or_dir.is_dir():
        root = zip_or_dir
    else:
        raise BundleError(f"expected .kage.zip or directory, got: {zip_or_dir}")

    return _validate_root(root)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """zip slip 対策。members がすべて dest 配下に収まることを確認してから extract する。"""
    dest_abs = dest.resolve()
    for name in zf.namelist():
        target = (dest_abs / name).resolve()
        if not str(target).startswith(str(dest_abs)):
            raise BundleError(f"unsafe path in zip: {name}")
    zf.extractall(dest)


def _validate_root(root: Path) -> CaptureBundle:
    if not root.exists() or not root.is_dir():
        raise BundleError(f"bundle root not a directory: {root}")

    missing_required = [f for f in REQUIRED_FILES if not (root / f).is_file()]
    if missing_required:
        raise BundleError(f"bundle missing required files: {missing_required}")

    screenshots_dir = root / "screenshots"
    if screenshots_dir.exists() and not screenshots_dir.is_dir():
        raise BundleError("screenshots must be a directory")

    missing_optional = [f for f in OPTIONAL_FILES if not (root / f).is_file()]

    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    for key in ("targetUrl", "startedAt", "durationMs", "captureTool"):
        if key not in metadata:
            raise BundleError(f"metadata.json missing key: {key}")
    if metadata["captureTool"] != "kage-capture":
        raise BundleError(f"unexpected captureTool: {metadata['captureTool']!r}")

    return CaptureBundle(root=root, metadata=metadata, missing=missing_optional)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL を読み込む。空行は無視。型は dict[str, Any]。"""
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise BundleError(f"{path.name}: expected object per line, got {type(obj).__name__}")
            out.append(obj)
    return out


def cleanup_tempdir(bundle: CaptureBundle) -> None:
    """tempdir に展開したものを片付けるユーティリティ。呼び出し側任意。"""
    if bundle.root.exists():
        shutil.rmtree(bundle.root, ignore_errors=True)
