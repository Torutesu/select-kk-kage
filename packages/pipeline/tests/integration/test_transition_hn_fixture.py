"""
hn-minimal fixture で transition 推論の e2e。

HN smoke では / → /newest の遷移が必ず 1 件は抽出される。
trigger はフル bundle 上では click+component にマッチするが、fixture の node 数
truncation により component match 失敗で nav_direct に落ちるケースもある。
どちらでもテストは通す(どちらも期待される正常ルート)。
"""

from __future__ import annotations

from pathlib import Path

from kage_pipeline.bundle import load_bundle
from kage_pipeline.integrity import validate_ir_integrity
from kage_pipeline.ir_builder import build_ir


def test_hn_transition_present(hn_minimal_dir: Path) -> None:
    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")

    # / → /newest の遷移が 1 件以上ある
    assert len(ir.transitions) >= 1

    # 最初の遷移は home→newest
    home = next(s for s in ir.screens if s.slug == "home")
    newest = next(s for s in ir.screens if s.slug == "newest")
    t = ir.transitions[0]
    assert str(t.from_) == str(home.id)
    assert str(t.to) == str(newest.id)

    # trigger は click か nav_direct のいずれか(どちらも正常ルート)
    assert t.trigger.type in ("click", "nav_direct")

    # integrity は clean
    assert validate_ir_integrity(ir) == []


def test_hn_no_login_so_no_current_user(hn_minimal_dir: Path) -> None:
    """HN は login フローを含まないので currentUser は生成されない。"""
    bundle = load_bundle(hn_minimal_dir)
    ir = build_ir(bundle, project_name="hn-smoke")
    names = {s.name for s in ir.sharedStates}
    assert "currentUser" not in names
    assert ir.hasAuth is False
