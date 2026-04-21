"""
entity_inferer の後処理ロジック検証(LLM はモック)。

AnthropicClient.call_structured を monkeypatch して固定 JSON を返し、
- 命名衝突の suffix 付け
- Relation target 不在時の String ダウングレード
- field 順序安定化 (id → unique → default → timestamp)
- apiActions.entityIds が正しく埋まる
を確認する。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from kage_pipeline.components.entity_inferer import (
    EntityFieldProposal,
    EntityProposal,
    ProposeEntitiesOutput,
    infer_entities,
)
from kage_pipeline.ir_schema import ApiAction, ApiActionObserved


def _api(
    name: str,
    method: str,
    url_pattern: str,
    sample: object | None = None,
) -> ApiAction:
    return ApiAction(
        id=uuid.uuid4(),
        name=name,
        kind="query" if method == "GET" else "mutation",
        observed=ApiActionObserved(
            method=method,  # type: ignore[arg-type]
            urlPattern=url_pattern,
            sampleResponse=sample,
        ),
        entityIds=[],
        confidence="medium",
    )


class _FakeClient:
    """AnthropicClient 互換の最小モック。"""

    def __init__(self, proposals: list[EntityProposal]) -> None:
        self._proposals = proposals
        self.calls: list[dict[str, Any]] = []

    async def call_structured(self, **kwargs: Any) -> ProposeEntitiesOutput:
        self.calls.append(kwargs)
        return ProposeEntitiesOutput(proposals=self._proposals)


@pytest.mark.asyncio
async def test_empty_api_actions_yields_empty_entities() -> None:
    entities, updated = await infer_entities(
        api_actions=[],
        screens=[],
        has_auth=False,
        llm_client=None,
    )
    assert entities == []
    assert updated == []


@pytest.mark.asyncio
async def test_llm_client_none_skips_llm() -> None:
    actions = [_api("u.list", "GET", "/users", [{"id": 1}])]
    entities, updated = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=None,
    )
    assert entities == []
    assert updated == actions  # 変更なし


@pytest.mark.asyncio
async def test_basic_user_entity_with_field_ordering() -> None:
    """id → unique → default → timestamp の順で fields が並ぶ。"""
    sample = {
        "id": 1,
        "createdAt": "2026-01-01T00:00:00Z",
        "name": "Alice",
        "email": "a@b.c",
    }
    actions = [_api("u.list", "GET", "/api/users", [sample])]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="User",
            confidence="high",
            fields=[
                # LLM から来た順序を (timestamp, name, email, id) のように乱す
                EntityFieldProposal(name="createdAt", type="DateTime", isCreatedAt=True),
                EntityFieldProposal(name="name", type="String"),
                EntityFieldProposal(name="email", type="String", unique=True),
                EntityFieldProposal(name="id", type="Int", isId=True),
            ],
        )
    ]
    client = _FakeClient(proposals)
    entities, updated = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=client,  # type: ignore[arg-type]
    )
    assert len(entities) == 1
    e = entities[0]
    assert e.name == "User"
    assert [f.name for f in e.fields] == ["id", "email", "name", "createdAt"]
    # action.entityIds が埋まる
    assert updated[0].entityIds == [str(e.id)]


@pytest.mark.asyncio
async def test_relation_target_missing_downgrades_to_string() -> None:
    """Relation が指す entity が proposal に無ければ String にダウングレード。"""
    actions = [_api("p.list", "GET", "/api/projects", [{"id": 1, "ownerId": 42}])]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="Project",
            confidence="medium",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(
                    name="ownerId",
                    type="Relation",
                    relationTargetName="User",  # 無い
                ),
            ],
        )
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=client,  # type: ignore[arg-type]
    )
    assert len(entities) == 1
    owner = next(f for f in entities[0].fields if f.name == "ownerId")
    assert owner.type == "String"
    assert owner.relationTargetEntityId is None


@pytest.mark.asyncio
async def test_relation_target_exists_resolves_to_entity_id() -> None:
    """ターゲット Entity が存在するなら Relation 維持、entity id が入る。"""
    actions = [
        _api("u.list", "GET", "/api/users", [{"id": 1, "email": "a@b.c"}]),
        _api("p.list", "GET", "/api/projects", [{"id": 1, "ownerId": 1}]),
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="User",
            confidence="high",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(name="email", type="String", unique=True),
            ],
        ),
        EntityProposal(
            clusterId="cluster_1",
            name="Project",
            confidence="high",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(
                    name="ownerId", type="Relation", relationTargetName="User"
                ),
            ],
        ),
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=True,
        llm_client=client,  # type: ignore[arg-type]
    )
    by_name = {e.name: e for e in entities}
    user = by_name["User"]
    project = by_name["Project"]
    owner = next(f for f in project.fields if f.name == "ownerId")
    assert owner.type == "Relation"
    assert str(owner.relationTargetEntityId) == str(user.id)


@pytest.mark.asyncio
async def test_name_conflict_resolution_suffixes_second() -> None:
    """LLM が同じ name を 2 つ返したら、後続クラスタに suffix を付ける。"""
    actions = [
        _api("a.list", "GET", "/ones", [{"id": 1, "label": "x"}]),
        _api("b.list", "GET", "/twos", [{"id": 2, "title": "y"}]),
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="Widget",
            confidence="medium",
            fields=[EntityFieldProposal(name="id", type="Int", isId=True)],
        ),
        EntityProposal(
            clusterId="cluster_1",
            name="Widget",  # 衝突
            confidence="medium",
            fields=[EntityFieldProposal(name="id", type="Int", isId=True)],
        ),
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=client,  # type: ignore[arg-type]
    )
    names = [e.name for e in entities]
    assert names == ["Widget", "Widget_cluster_1"]


@pytest.mark.asyncio
async def test_questions_propagated_to_entity() -> None:
    actions = [_api("u.list", "GET", "/users", [{"id": 1, "status": "active"}])]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="User",
            confidence="low",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(name="status", type="String"),
            ],
            questions=[
                "status の取り得る値は?",
                "これ本当に User table で OK ですか?",
            ],
        )
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=client,  # type: ignore[arg-type]
    )
    assert len(entities[0].questions) == 2
    assert "status" in entities[0].questions[0]


@pytest.mark.asyncio
async def test_pending_relation_downgrades_to_int_with_auto_question() -> None:
    """
    hasAuth=True, userId フィールドあり, User cluster なし。
    LLM は __pending_User__ を返す convention に従う。
    → 後処理で Int にダウングレード、auto question が追加される。
    """
    actions = [
        _api(
            "projects.list",
            "GET",
            "/api/projects",
            [{"id": 1, "title": "p", "ownerId": 42}],
        )
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="Project",
            confidence="medium",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(name="title", type="String"),
                EntityFieldProposal(
                    name="ownerId",
                    type="Relation",
                    relationTargetName="__pending_User__",
                ),
            ],
            questions=[],
        )
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=True,
        llm_client=client,  # type: ignore[arg-type]
    )
    assert len(entities) == 1
    proj = entities[0]
    owner = next(f for f in proj.fields if f.name == "ownerId")
    # Q2=A: 常に Int に落とす
    assert owner.type == "Int"
    assert owner.relationTargetEntityId is None
    # 自動 question が追加されている
    assert any("ownerId" in q and "User" in q for q in proj.questions)


@pytest.mark.asyncio
async def test_pending_relation_with_existing_target_entity_resolves_normally() -> None:
    """
    hasAuth=True, User cluster もあり、userId フィールドあり。
    LLM が relationTargetName="User"(__pending_ 無し)を返せば通常 Relation 化。
    """
    actions = [
        _api("u.list", "GET", "/api/users", [{"id": 1, "email": "a@b.c"}]),
        _api("p.list", "GET", "/api/projects", [{"id": 1, "ownerId": 1}]),
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="User",
            confidence="high",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(name="email", type="String", unique=True),
            ],
        ),
        EntityProposal(
            clusterId="cluster_1",
            name="Project",
            confidence="high",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(
                    name="ownerId", type="Relation", relationTargetName="User"
                ),
            ],
        ),
    ]
    client = _FakeClient(proposals)
    entities, _ = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=True,
        llm_client=client,  # type: ignore[arg-type]
    )
    by_name = {e.name: e for e in entities}
    user = by_name["User"]
    project = by_name["Project"]
    owner = next(f for f in project.fields if f.name == "ownerId")
    # 通常 Relation として解決
    assert owner.type == "Relation"
    assert str(owner.relationTargetEntityId) == str(user.id)
    # 自動 question は付かない
    assert not any("relation" in q.lower() and "pending" in q.lower() for q in project.questions)


@pytest.mark.asyncio
async def test_pending_relation_passthrough_does_not_leak_into_entity_ids() -> None:
    """
    __pending_ で downgrade した ownerId は Int なので、Entity の
    relationTargetEntityId は None、apiAction.entityIds にも付かない。
    (付くと integrity error になる)
    """
    from kage_pipeline.integrity import validate_ir_integrity
    from kage_pipeline.ir_schema import IR, IRSource

    actions = [
        _api("p.list", "GET", "/api/projects", [{"id": 1, "ownerId": 42}])
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="Project",
            confidence="medium",
            fields=[
                EntityFieldProposal(name="id", type="Int", isId=True),
                EntityFieldProposal(
                    name="ownerId",
                    type="Relation",
                    relationTargetName="__pending_User__",
                ),
            ],
        )
    ]
    client = _FakeClient(proposals)
    entities, updated = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=True,
        llm_client=client,  # type: ignore[arg-type]
    )

    # IR を組み立てて integrity を通す(dangling ref が残っていないこと)
    ir = IR(
        version="1.0.0",
        source=IRSource(
            targetUrl="https://x",
            recordedAt="2026-04-21T00:00:00Z",
            durationSeconds=1.0,
            captureTool="kage-capture",
        ),
        projectName="t",
        entities=entities,
        apiActions=updated,
        hasAuth=True,
    )
    assert validate_ir_integrity(ir) == []


@pytest.mark.asyncio
async def test_llm_returns_fewer_proposals_than_clusters_is_ok() -> None:
    """LLM が一部クラスタを返し忘れても、entity_inferer は crash しない。"""
    actions = [
        _api("a.list", "GET", "/widgets", [{"id": 1}]),
        _api("b.list", "GET", "/gizmos", [{"id": 1}]),
    ]
    proposals = [
        EntityProposal(
            clusterId="cluster_0",
            name="Widget",
            confidence="medium",
            fields=[EntityFieldProposal(name="id", type="Int", isId=True)],
        )
    ]
    client = _FakeClient(proposals)
    entities, updated = await infer_entities(
        api_actions=actions,
        screens=[],
        has_auth=False,
        llm_client=client,  # type: ignore[arg-type]
    )
    assert len(entities) == 1
    # cluster_1 (gizmos) の action は entityIds が空のまま
    action_entity_counts = [len(a.entityIds) for a in updated]
    assert sorted(action_entity_counts) == [0, 1]
