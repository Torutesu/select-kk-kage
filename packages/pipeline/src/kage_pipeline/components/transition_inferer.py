"""
events + HAR/events-derived requests → IR transitions[] (deterministic).

アルゴリズム概要:
  1. events を時系列ソート
  2. navigation 境界で segment 化。各 segment は Screen と 1:1 対応
     (screen は path ベース dedupe 済みなので、同じ path の navigation は
      同一 screen への「戻り/リロード」扱いで transition にしない)
  3. segment[i] の最後の user 行動 (click/submit) と segment[i+1] の navigation の
     time delta を測る。500ms 以内なら因果関係あり。
  4. Trigger 分類:
        click → (500ms 以内) → 2xx XHR response → "api_success"
        click → navigation のみ                 → "click"
        submit → navigation のみ                → "submit"
        ユーザ行動なしに直接 navigation         → "nav_direct"
  5. click の場合、Screen.root 以下で component を bbox/text/selector マッチ
  6. login 系 URL の POST 2xx を検出したら currentUser SharedState を追加
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..ir_schema import (
    ApiAction,
    Confidence,
    Screen,
    SharedState,
    Transition,
    TriggerApiSuccess,
    TriggerClick,
    TriggerNavDirect,
    TriggerSubmit,
)
from ..utils.component_match import match_component
from ..utils.time_window import _ts, within
from ..utils.url_key import url_key


USER_EVENT_TYPES: set[str] = {"click", "submit"}
# segment[i] 最終 user event と segment[i+1] navigation の間隔上限
CAUSAL_GAP_MS = 500.0
# click → api response の関連付け上限
API_RELATE_GAP_MS = 500.0
# キャプチャ側で click CustomEvent が navigation 完了より後にノードへ届く(exposeFunction
# chain の非同期遅延)ケースがあるため、次 segment 先頭 ~200ms に落ちてきた user event も
# 前の遷移の trigger 候補として拾う。
POST_NAV_LATE_USER_EVENT_WINDOW_MS = 200.0


# login 系 URL heuristic (path で判定。POST + 2xx と組み合わせて初めて判定成立)
_LOGIN_PATH_RE = re.compile(r"/(login|signin|sign-in|auth/login|sessions)\b", re.IGNORECASE)


@dataclass
class _Segment:
    """1 navigation 〜 次の navigation までの滞在セグメント。"""

    screen: Screen
    start_ts: float
    end_ts: float
    nav_url: str
    events: list[dict[str, Any]] = field(default_factory=list)


def _split_segments(
    events: list[dict[str, Any]], screens: list[Screen]
) -> list[_Segment]:
    """navigation 境界で segment 化。Screen は url_key で引き当てる。"""
    screens_by_key: dict[str, Screen] = {}
    for s in screens:
        k = url_key(s.originalUrl)
        screens_by_key.setdefault(k, s)

    sorted_events = sorted(events, key=_ts)

    segments: list[_Segment] = []
    current: _Segment | None = None
    max_ts = sorted_events[-1]["timestamp"] if sorted_events else 0.0

    for ev in sorted_events:
        if ev.get("type") == "navigation":
            if current is not None:
                current.end_ts = _ts(ev)
                segments.append(current)
            url = ev.get("url")
            if not isinstance(url, str) or not url:
                current = None
                continue
            screen = screens_by_key.get(url_key(url))
            if screen is None:
                current = None
                continue
            current = _Segment(
                screen=screen,
                start_ts=_ts(ev),
                end_ts=_ts(ev),
                nav_url=url,
                events=[],
            )
            continue
        if current is not None:
            current.events.append(ev)

    if current is not None:
        current.end_ts = float(max_ts)
        segments.append(current)

    return segments


def _last_user_event(segment: _Segment) -> dict[str, Any] | None:
    for ev in reversed(segment.events):
        if ev.get("type") in USER_EVENT_TYPES:
            return ev
    return None


def _late_user_event(
    next_segment: _Segment, window_ms: float
) -> dict[str, Any] | None:
    """
    次 segment 先頭 window_ms の範囲に現れた user event を返す。
    実機では click イベントが navigation 完了後に Node へ届くことがあり、
    こうした "遅延到着" を前の遷移の trigger 候補として救うためのウィンドウ。
    """
    limit = next_segment.start_ts + window_ms
    for ev in next_segment.events:
        ts = _ts(ev)
        if ts > limit:
            break
        if ev.get("type") in USER_EVENT_TYPES:
            return ev
    return None


def _find_api_action_for_url(
    api_actions: list[ApiAction], url: str, method: str
) -> ApiAction | None:
    """api_extractor と同じ heuristic で urlPattern を逆算し、一致するものを返す。"""
    from .api_extractor import derive_url_pattern

    pattern = derive_url_pattern(url)
    method_u = method.upper()
    for a in api_actions:
        if a.observed.urlPattern == pattern and a.observed.method == method_u:
            return a
    return None


def _find_success_api_between(
    events: list[dict[str, Any]],
    *,
    start_ts: float,
    end_ts: float,
) -> dict[str, Any] | None:
    """start〜end の間に 2xx response があれば、それと対になる request を探して返す。"""
    for resp in within(events, start_ts, end_ts):
        if resp.get("type") != "response":
            continue
        status = resp.get("status")
        if not isinstance(status, int) or not (200 <= status < 300):
            continue
        url = resp.get("url")
        if not isinstance(url, str):
            continue
        # 同じ URL の直前 request を探す(方法を復元するため)
        for req in reversed(within(events, 0.0, _ts(resp))):
            if req.get("type") == "request" and req.get("url") == url:
                return {"request": req, "response": resp}
        return {"request": None, "response": resp}
    return None


def _classify_gap_confidence(delta_ms: float) -> Confidence:
    if delta_ms < 100:
        return "high"
    if delta_ms < CAUSAL_GAP_MS:
        return "medium"
    return "low"


def _is_login_api(
    api_actions: list[ApiAction], action_id: str
) -> bool:
    for a in api_actions:
        if str(a.id) != action_id:
            continue
        path = a.observed.urlPattern
        return bool(_LOGIN_PATH_RE.search(path)) and a.observed.method == "POST"
    return False


def _find_login_action_id(
    events: list[dict[str, Any]],
    api_actions: list[ApiAction],
    *,
    start_ts: float,
    end_ts: float,
) -> ApiAction | None:
    """segment 間で POST login + 2xx が観測されたら該当 ApiAction を返す。"""
    for resp in within(events, start_ts, end_ts):
        if resp.get("type") != "response":
            continue
        status = resp.get("status")
        if not isinstance(status, int) or not (200 <= status < 300):
            continue
        url = resp.get("url")
        if not isinstance(url, str):
            continue
        if not _LOGIN_PATH_RE.search(urlparse(url).path or ""):
            continue
        # POST で来ていた request を events から探す
        for req in reversed(within(events, 0.0, _ts(resp))):
            if (
                req.get("type") == "request"
                and req.get("url") == url
                and (req.get("method") or "").upper() == "POST"
            ):
                api = _find_api_action_for_url(api_actions, url, "POST")
                if api is not None:
                    return api
    return None


def infer_transitions(
    events: list[dict[str, Any]],
    screens: list[Screen],
    api_actions: list[ApiAction],
) -> tuple[list[Transition], list[SharedState]]:
    """
    events + screens + api_actions から transitions[] と(最小限の)sharedStates を推論。

    LLM は使わない(Day 5.1 は deterministic only)。
    """
    segments = _split_segments(events, screens)
    if len(segments) < 2:
        return [], []

    transitions: list[Transition] = []
    shared_states: list[SharedState] = []
    current_user_ss: SharedState | None = None

    def ensure_current_user() -> SharedState:
        nonlocal current_user_ss
        if current_user_ss is None:
            current_user_ss = SharedState(
                id=uuid.uuid4(),
                name="currentUser",
                type="User | null",
                initialValue="null",
                persistence="memory",
                confidence="medium",
                evidence=["inferred from successful POST to login-like URL"],
            )
            shared_states.append(current_user_ss)
        return current_user_ss

    for i in range(len(segments) - 1):
        cur = segments[i]
        nxt = segments[i + 1]

        # 同じ論理画面への再 navigation は transition にしない
        if cur.screen.id == nxt.screen.id:
            continue

        last_user = _last_user_event(cur)
        nav_ts = nxt.start_ts
        # 次 segment 先頭 ~200ms に来た user event を "遅延到着" として救う
        late_user = _late_user_event(nxt, POST_NAV_LATE_USER_EVENT_WINDOW_MS)
        if late_user is not None and (
            last_user is None or _ts(late_user) >= _ts(last_user)
        ):
            last_user = late_user
        gap_ms = nav_ts - (_ts(last_user) if last_user else nav_ts)
        gap_ms = abs(gap_ms)  # 遅延到着のケースは負になるので絶対値で扱う

        trigger: Any = TriggerNavDirect(type="nav_direct")
        action_ids: list[str] = []
        update_shared_state_ids: list[str] = []
        confidence: Confidence = "low"

        if last_user is not None and gap_ms <= CAUSAL_GAP_MS:
            user_type = last_user.get("type")
            comp = match_component(cur.screen.root, last_user)
            component_id = comp.id if comp is not None else None

            # api_success 判定: click の後 500ms 以内に 2xx レスポンスが来ていたか
            api_pair = _find_success_api_between(
                cur.events,
                start_ts=_ts(last_user),
                end_ts=_ts(last_user) + API_RELATE_GAP_MS,
            )
            matched_api: ApiAction | None = None
            if api_pair is not None:
                resp = api_pair["response"]
                req = api_pair["request"] or {}
                url_val = resp.get("url") if isinstance(resp, dict) else None
                method_val = req.get("method") if isinstance(req, dict) else None
                if isinstance(url_val, str) and isinstance(method_val, str):
                    matched_api = _find_api_action_for_url(
                        api_actions, url_val, method_val
                    )

            if matched_api is not None:
                trigger = TriggerApiSuccess(type="api_success", actionId=matched_api.id)
                action_ids = [str(matched_api.id)]
                confidence = _classify_gap_confidence(gap_ms)
            elif user_type == "click" and component_id is not None:
                trigger = TriggerClick(type="click", componentId=component_id)
                confidence = _classify_gap_confidence(gap_ms)
            elif user_type == "submit" and component_id is not None:
                trigger = TriggerSubmit(type="submit", componentId=component_id)
                confidence = _classify_gap_confidence(gap_ms)
            else:
                # マッチ失敗: click/submit でも component_id が取れなければ nav_direct へ落とす
                trigger = TriggerNavDirect(type="nav_direct", note="component match failed")
                confidence = "low"

        # login 系 API が segment[i] 終端〜segment[i+1] 開始までに観測されたか
        login_api = _find_login_action_id(
            cur.events + nxt.events[:1],  # nav 直前に response が入ることが多いので両端見る
            api_actions,
            start_ts=cur.start_ts,
            end_ts=nxt.start_ts + 1.0,
        )
        if login_api is not None:
            cu_ss = ensure_current_user()
            update_shared_state_ids.append(str(cu_ss.id))
            # login API の action_id を transitions[].actionIds に付ける(未追加なら)
            if str(login_api.id) not in action_ids:
                action_ids.append(str(login_api.id))

        transitions.append(
            Transition.model_validate(
                {
                    "id": str(uuid.uuid4()),
                    "from": str(cur.screen.id),
                    "to": str(nxt.screen.id),
                    "trigger": trigger.model_dump(),
                    "actionIds": action_ids,
                    "updatesSharedStateIds": update_shared_state_ids,
                    "confidence": confidence,
                }
            )
        )

    return transitions, shared_states
