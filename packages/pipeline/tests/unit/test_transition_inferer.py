"""
transition_inferer のユニットテスト。

合成 events + 合成 screens + 合成 api_actions を投入して、trigger 分類・
component_id マッチ・shared state 推論を個別に検証する。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from kage_pipeline.components.transition_inferer import infer_transitions
from kage_pipeline.ir_schema import (
    ApiAction,
    ApiActionObserved,
    BoundingBox,
    Component,
    Screen,
)


# ───────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────


def _component(
    kind: str = "Button",
    *,
    bbox: tuple[float, float, float, float] | None = None,
    text: str | None = None,
    children: list[Component] | None = None,
) -> Component:
    return Component(
        id=uuid.uuid4(),
        kind=kind,  # type: ignore[arg-type]
        bbox=BoundingBox(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        if bbox
        else None,
        text=text,
        children=list(children or []),
        confidence="high",
    )


def _screen(url: str, *, root_children: list[Component] | None = None) -> Screen:
    root = Component(
        id=uuid.uuid4(),
        kind="Container",
        confidence="high",
        children=list(root_children or []),
    )
    return Screen(
        id=uuid.uuid4(),
        slug=url.strip("/").replace("/", "-") or "home",
        route=url,
        originalUrl=f"https://app.test{url}",
        requiresAuth=False,
        initialDataBindingIds=[],
        root=root,
        confidence="high",
    )


def _nav(ts: float, url: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "navigation",
        "timestamp": ts,
        "url": f"https://app.test{url}",
    }


def _click(
    ts: float,
    *,
    bbox: tuple[float, float, float, float] = (0, 0, 10, 10),
    selector: str = "button",
    text: str = "",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "click",
        "timestamp": ts,
        "selector": selector,
        "target": {
            "tagName": "BUTTON",
            "text": text,
            "bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3]},
        },
    }


def _submit(
    ts: float, *, bbox: tuple[float, float, float, float] = (0, 0, 200, 40)
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "submit",
        "timestamp": ts,
        "selector": "form",
        "target": {
            "tagName": "FORM",
            "bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3]},
        },
    }


def _req(ts: float, url: str, method: str = "POST") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "request",
        "timestamp": ts,
        "url": url,
        "method": method,
    }


def _resp(ts: float, url: str, status: int = 200) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "response",
        "timestamp": ts,
        "url": url,
        "status": status,
    }


def _api(name: str, method: str, url_pattern: str) -> ApiAction:
    return ApiAction(
        id=uuid.uuid4(),
        name=name,
        kind="query" if method == "GET" else "mutation",
        observed=ApiActionObserved(
            method=method,  # type: ignore[arg-type]
            urlPattern=url_pattern,
        ),
        entityIds=[],
        confidence="medium",
    )


# ───────────────────────────────────────────────────────────
# Cases
# ───────────────────────────────────────────────────────────


def test_click_plus_navigation_basic() -> None:
    """基本: click → navigation、component が bbox マッチして Trigger.click。"""
    btn = _component("Button", bbox=(100, 200, 80, 40), text="Go")
    s1 = _screen("/", root_children=[btn])
    s2 = _screen("/dashboard")
    events = [
        _nav(0, "/"),
        _click(1000, bbox=(100, 200, 80, 40), text="Go"),
        _nav(1050, "/dashboard"),
    ]
    transitions, shared = infer_transitions(events, [s1, s2], api_actions=[])

    assert len(transitions) == 1
    t = transitions[0]
    assert str(t.from_) == str(s1.id)
    assert str(t.to) == str(s2.id)
    assert t.trigger.type == "click"
    assert str(t.trigger.componentId) == str(btn.id)
    assert t.confidence == "high"  # gap < 100 ms
    assert shared == []


def test_submit_plus_navigation() -> None:
    form = _component("Form", bbox=(0, 0, 400, 200))
    s1 = _screen("/login", root_children=[form])
    s2 = _screen("/dashboard")
    events = [
        _nav(0, "/login"),
        _submit(2000, bbox=(0, 0, 400, 200)),
        _nav(2300, "/dashboard"),
    ]
    transitions, _ = infer_transitions(events, [s1, s2], api_actions=[])
    assert len(transitions) == 1
    t = transitions[0]
    assert t.trigger.type == "submit"
    assert str(t.trigger.componentId) == str(form.id)
    assert t.confidence == "medium"  # 300 ms


def test_click_plus_api_success_plus_navigation() -> None:
    btn = _component("Button", bbox=(10, 10, 50, 30), text="Login")
    s1 = _screen("/login", root_children=[btn])
    s2 = _screen("/home")
    login_url = "https://app.test/api/auth/login"
    login_api = _api("auth.create", "POST", "/api/auth/login")
    events = [
        _nav(0, "/login"),
        _click(1000, bbox=(10, 10, 50, 30), text="Login"),
        _req(1010, login_url, method="POST"),
        _resp(1200, login_url, status=200),
        _nav(1300, "/home"),
    ]
    transitions, shared = infer_transitions(events, [s1, s2], [login_api])
    assert len(transitions) == 1
    t = transitions[0]
    assert t.trigger.type == "api_success"
    assert str(t.trigger.actionId) == str(login_api.id)
    assert str(login_api.id) in t.actionIds
    # login chain: currentUser SharedState が生成され、updatesSharedStateIds に入る
    assert len(shared) == 1
    assert shared[0].name == "currentUser"
    assert str(shared[0].id) in t.updatesSharedStateIds


def test_direct_navigation_without_user_event() -> None:
    """ユーザ action なしでの遷移(back button / URL 直接入力) → nav_direct。"""
    s1 = _screen("/a")
    s2 = _screen("/b")
    events = [
        _nav(0, "/a"),
        _nav(5000, "/b"),
    ]
    transitions, _ = infer_transitions(events, [s1, s2], api_actions=[])
    assert len(transitions) == 1
    assert transitions[0].trigger.type == "nav_direct"
    assert transitions[0].confidence == "low"


def test_time_delta_beyond_threshold_is_nav_direct() -> None:
    """click と次 navigation の間隔が 500ms を超えたら因果なしと判断。"""
    btn = _component("Button", bbox=(0, 0, 10, 10))
    s1 = _screen("/a", root_children=[btn])
    s2 = _screen("/b")
    events = [
        _nav(0, "/a"),
        _click(1000, bbox=(0, 0, 10, 10)),
        _nav(2000, "/b"),  # 1000 ms 経過 → 関係なし
    ]
    transitions, _ = infer_transitions(events, [s1, s2], api_actions=[])
    assert len(transitions) == 1
    assert transitions[0].trigger.type == "nav_direct"


def test_component_match_failure_falls_back_to_nav_direct() -> None:
    """bbox が一致する Component がなければ nav_direct にフォールバック。"""
    s1 = _screen("/a")  # root だけで子なし
    s2 = _screen("/b")
    events = [
        _nav(0, "/a"),
        _click(500, bbox=(999, 999, 10, 10)),  # 何とも重ならない
        _nav(520, "/b"),
    ]
    transitions, _ = infer_transitions(events, [s1, s2], api_actions=[])
    assert len(transitions) == 1
    assert transitions[0].trigger.type == "nav_direct"
    # note に match failed の痕跡
    assert transitions[0].trigger.note == "component match failed"


def test_hash_only_change_does_not_create_transition() -> None:
    """/page と /page#section は同じ Screen key、transition にしない。"""
    # extract_screens 相当の dedupe は呼び出し側の責任。ここでは screens が 1 件の想定。
    s = _screen("/page")
    # 同じ screen.id を再利用するように events だけ #fragment を変える
    evs = [
        _nav(0, "https://app.test/page"),
        _nav(200, "https://app.test/page#section"),
        _click(500, bbox=(0, 0, 10, 10)),
    ]
    # Screen が 1 件しかなければ segment が 1 つだけ → transition 0 件
    transitions, _ = infer_transitions(evs, [s], api_actions=[])
    assert transitions == []


def test_query_only_change_does_not_create_transition() -> None:
    """/search と /search?q=foo は同じ Screen key、transition にしない。"""
    s = _screen("/search")
    evs = [
        _nav(0, "https://app.test/search"),
        _nav(300, "https://app.test/search?q=foo"),
    ]
    transitions, _ = infer_transitions(evs, [s], api_actions=[])
    assert transitions == []


def test_login_chain_sets_current_user_and_has_auth() -> None:
    """POST /sessions 成功後に別画面へ遷移すると currentUser SharedState が出る。"""
    btn = _component("Button", bbox=(10, 10, 50, 30), text="Login")
    s1 = _screen("/login", root_children=[btn])
    s2 = _screen("/dashboard")
    url = "https://app.test/sessions"
    api = _api("sessions.create", "POST", "/sessions")
    events = [
        _nav(0, "/login"),
        _click(500, bbox=(10, 10, 50, 30), text="Login"),
        _req(510, url, method="POST"),
        _resp(700, url, status=201),
        _nav(750, "/dashboard"),
    ]
    transitions, shared = infer_transitions(events, [s1, s2], [api])
    assert len(transitions) == 1
    assert len(shared) == 1
    ss = shared[0]
    assert ss.name == "currentUser"
    assert ss.persistence == "memory"
    assert str(ss.id) in transitions[0].updatesSharedStateIds
    # login 系 POST の ApiAction は actionIds に含まれる
    assert str(api.id) in transitions[0].actionIds


@pytest.mark.parametrize(
    "gap,expected",
    [
        (50, "high"),
        (200, "medium"),
        (499, "medium"),
    ],
)
def test_confidence_boundaries(gap: float, expected: str) -> None:
    btn = _component("Button", bbox=(0, 0, 10, 10))
    s1 = _screen("/a", root_children=[btn])
    s2 = _screen("/b")
    events = [
        _nav(0, "/a"),
        _click(1000, bbox=(0, 0, 10, 10)),
        _nav(1000 + gap, "/b"),
    ]
    transitions, _ = infer_transitions(events, [s1, s2], api_actions=[])
    assert transitions[0].confidence == expected
