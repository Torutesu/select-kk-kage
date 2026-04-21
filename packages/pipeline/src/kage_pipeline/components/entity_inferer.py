"""
Entity 推論: apiActions → entities + apiAction.entityIds を埋める。

ステップ:
  1. response_normalizer + entity_clusterer でクラスタ化 (deterministic)
  2. Sonnet (tool-use) に cluster 群を渡して EntityProposal を生成
  3. 後処理:
     - 同名衝突を suffix で解決
     - Relation target 不在のフィールドは String にダウングレード
     - fields の順序安定化 (id → ユニーク → 一般 → timestamps)
     - entityIds を元の ApiAction に書き戻し

LLM を呼ばないルートも用意する:
  - api_actions が空
  - llm_client が None
  - クラスタが 0 件
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..ir_schema import (
    ApiAction,
    ApiActionObserved,
    Confidence,
    Entity,
    EntityField,
    EntityFieldType,
    Screen,
)
from ..llm.prompts import render
from .utils.entity_clusterer import EntityCluster, cluster_api_actions


if TYPE_CHECKING:
    from ..llm.client import AnthropicClient


# ─────────────────────────────────────────────────────────────
# LLM output schema (pydantic)
# ─────────────────────────────────────────────────────────────


class EntityFieldProposal(BaseModel):
    """LLM が返す 1 field 分の提案。IR の EntityField とほぼ同形だが LLM が書きやすい緩さ。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: EntityFieldType
    relationTargetName: str | None = Field(
        default=None,
        description=(
            "Relation type のとき、ターゲット Entity の name を書く(id ではなく name)。"
            "Relation 以外のときは None。"
        ),
    )
    enumValues: list[str] | None = None
    optional: bool = False
    unique: bool = False
    isId: bool = False
    isCreatedAt: bool = False
    isUpdatedAt: bool = False
    evidence: list[str] = Field(default_factory=list)


class EntityProposal(BaseModel):
    """LLM が返す 1 entity 分の提案。"""

    model_config = ConfigDict(extra="forbid")

    clusterId: str = Field(description="元クラスタの id (cluster_0 等)")
    name: str = Field(description="PascalCase 単数形")
    fields: list[EntityFieldProposal]
    confidence: Confidence = "medium"
    questions: list[str] = Field(default_factory=list)


class ProposeEntitiesOutput(BaseModel):
    """tool の output root。"""

    model_config = ConfigDict(extra="forbid")

    proposals: list[EntityProposal]


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


async def infer_entities(
    api_actions: list[ApiAction],
    screens: list[Screen],
    has_auth: bool,
    llm_client: "AnthropicClient | None" = None,
) -> tuple[list[Entity], list[ApiAction]]:
    """
    api_actions から entities[] を推論し、各 action の entityIds[] を埋める。

    LLM を使うので llm_client 必須 … と思いきや、
    - api_actions が空
    - クラスタが 0 件
    - llm_client が None
    のいずれかなら、LLM を呼ばずに空のリストを返す(+ 元の api_actions をそのまま戻す)。
    """
    if not api_actions:
        return [], api_actions

    clusters = cluster_api_actions(api_actions)
    if not clusters:
        return [], api_actions

    if llm_client is None:
        # LLM 不使用モード: Entity 生成はスキップ、apiActions も変更しない
        return [], api_actions

    proposals = await _request_proposals(
        clusters=clusters,
        screens=screens,
        has_auth=has_auth,
        llm_client=llm_client,
    )

    entities, updated_actions = _postprocess(
        clusters=clusters,
        proposals=proposals,
        api_actions=api_actions,
    )
    return entities, updated_actions


# ─────────────────────────────────────────────────────────────
# Prompt rendering + LLM call
# ─────────────────────────────────────────────────────────────


def _cluster_template_context(cluster: EntityCluster) -> dict[str, Any]:
    """Jinja2 に渡す cluster の dict 表現。"""
    return {
        "id": cluster.id,
        "actions": [
            {
                "method": a.observed.method,
                "url_pattern": a.observed.urlPattern,
                "name": a.name,
            }
            for a in cluster.actions
        ],
        "hint_names": cluster.hint_names,
        "field_types": {k: sorted(list(v)) for k, v in cluster.field_types.items()},
        "sample_record_json": json.dumps(
            cluster.sample_record or {}, ensure_ascii=False, indent=2
        ),
    }


async def _request_proposals(
    *,
    clusters: list[EntityCluster],
    screens: list[Screen],
    has_auth: bool,
    llm_client: "AnthropicClient",
) -> list[EntityProposal]:
    user_prompt = render(
        "entity_infer_v1.md.j2",
        has_auth=has_auth,
        screen_slugs=[s.slug for s in screens],
        clusters=[_cluster_template_context(c) for c in clusters],
    )
    result = await llm_client.call_structured(
        model="sonnet",
        task="entity_infer_v1",
        user_prompt=user_prompt,
        output_model=ProposeEntitiesOutput,
        tool_name="propose_entities",
        tool_description=(
            "Propose one EntityProposal per input cluster (match by clusterId). "
            "Follow the rules from the system prompt; prefer safety over ambition."
        ),
        temperature=0.0,
        max_tokens=8192,
    )
    return result.proposals


# ─────────────────────────────────────────────────────────────
# Post-processing
# ─────────────────────────────────────────────────────────────


_FIELD_ORDER_BUCKETS: dict[str, int] = {
    # 小さいほど先。同じバケット内は LLM の返した順序を保つ。
    "id": 0,
    "unique": 1,
    "default": 2,
    "timestamp": 3,
}


def _field_bucket(f: EntityField) -> int:
    if f.isId:
        return _FIELD_ORDER_BUCKETS["id"]
    if f.isCreatedAt or f.isUpdatedAt:
        return _FIELD_ORDER_BUCKETS["timestamp"]
    if f.unique:
        return _FIELD_ORDER_BUCKETS["unique"]
    return _FIELD_ORDER_BUCKETS["default"]


def _resolve_name_conflicts(proposals: list[EntityProposal]) -> dict[str, str]:
    """
    同名が複数 proposal に現れたら cluster id を suffix にして衝突回避する。
    返り値: clusterId → 最終採用 name。
    """
    name_count: dict[str, int] = {}
    first_cluster: dict[str, str] = {}
    for p in proposals:
        name_count[p.name] = name_count.get(p.name, 0) + 1
        first_cluster.setdefault(p.name, p.clusterId)

    out: dict[str, str] = {}
    for p in proposals:
        if name_count[p.name] == 1:
            out[p.clusterId] = p.name
        else:
            # 先頭の cluster はそのまま、以降は suffix 付け
            if first_cluster[p.name] == p.clusterId:
                out[p.clusterId] = p.name
            else:
                out[p.clusterId] = f"{p.name}_{p.clusterId}"
    return out


_PENDING_PREFIX = "__pending_"
_PENDING_SUFFIX = "__"


def _parse_pending_target(name: str | None) -> str | None:
    """`__pending_User__` → `User` を取り出す。そうでなければ None。"""
    if not name:
        return None
    if not (name.startswith(_PENDING_PREFIX) and name.endswith(_PENDING_SUFFIX)):
        return None
    inner = name[len(_PENDING_PREFIX) : -len(_PENDING_SUFFIX)]
    return inner or None


def _build_entity(
    proposal: EntityProposal,
    final_name: str,
    name_to_entity_id: dict[str, str],
) -> tuple[Entity, list[str]]:
    """
    LLM の EntityProposal を IR Entity に変換する。
    第 2 戻り値は「後から proposal.questions に auto-append する日本語 question」の list。
    (Relation pending / target 不在 の downgrade 時に自動的に質問を残す)
    """
    fields: list[EntityField] = []
    auto_questions: list[str] = []

    for f in proposal.fields:
        ftype: EntityFieldType = f.type
        rel_target: str | None = None

        if f.type == "Relation":
            target_name = f.relationTargetName
            pending_target = _parse_pending_target(target_name)

            if pending_target:
                # Q2=A: __pending_<Name>__ は常に Int にダウングレード
                ftype = "Int"
                auto_questions.append(
                    f"`{f.name}` は `{pending_target}` テーブルへの relation ですか?"
                    f"対応する cluster が観測されなかったので Int に保留中"
                )
            elif target_name and target_name in name_to_entity_id:
                rel_target = name_to_entity_id[target_name]
            else:
                # target 指定はあるが未知 → 旧動作 (String)
                ftype = "String"
                if target_name:
                    auto_questions.append(
                        f"`{f.name}` の relation target `{target_name}` が "
                        f"他 cluster で見つからなかったので String に落としました"
                    )

        fields.append(
            EntityField(
                name=f.name,
                type=ftype,
                relationTargetEntityId=uuid.UUID(rel_target) if rel_target else None,
                enumValues=f.enumValues,
                optional=f.optional,
                unique=f.unique,
                isId=f.isId,
                isCreatedAt=f.isCreatedAt,
                isUpdatedAt=f.isUpdatedAt,
                evidence=list(f.evidence),
            )
        )

    # 安定 field 順序
    ordered = sorted(
        enumerate(fields),
        key=lambda pair: (_field_bucket(pair[1]), pair[0]),
    )
    fields = [f for _, f in ordered]

    entity = Entity(
        id=uuid.uuid4(),
        name=final_name,
        fields=fields,
        confidence=proposal.confidence,
        evidence=[],
        questions=list(proposal.questions),
    )
    return entity, auto_questions


def _postprocess(
    *,
    clusters: list[EntityCluster],
    proposals: list[EntityProposal],
    api_actions: list[ApiAction],
) -> tuple[list[Entity], list[ApiAction]]:
    # cluster_id → Proposal (LLM が抜けを返すケースに備えてフィルタ)
    proposals_by_cluster: dict[str, EntityProposal] = {
        p.clusterId: p for p in proposals
    }

    # 1) 名前衝突解決
    resolved_names = _resolve_name_conflicts(
        [proposals_by_cluster[c.id] for c in clusters if c.id in proposals_by_cluster]
    )

    # 2) Pass 1: 先に entity.id を採番(Relation 解決で name→id が必要)
    name_to_entity_id: dict[str, str] = {}
    pre_entities: list[tuple[EntityCluster, EntityProposal, str, str]] = []
    for cluster in clusters:
        p = proposals_by_cluster.get(cluster.id)
        if p is None:
            continue
        final_name = resolved_names.get(cluster.id, p.name)
        entity_id = str(uuid.uuid4())
        name_to_entity_id[final_name] = entity_id
        pre_entities.append((cluster, p, final_name, entity_id))

    # 3) Pass 2: Entity を組み立て(Relation を解決)
    entities: list[Entity] = []
    entity_id_by_cluster: dict[str, str] = {}
    for cluster, p, final_name, entity_id in pre_entities:
        ent, auto_questions = _build_entity(p, final_name, name_to_entity_id)
        # _build_entity が新しい UUID を振るので、ここで差し替える。
        # auto_questions は LLM が書き漏らしても保険として追加。
        ent_with_fixed_id = ent.model_copy(
            update={
                "id": uuid.UUID(entity_id),
                "questions": ent.questions + auto_questions,
            }
        )
        entities.append(ent_with_fixed_id)
        entity_id_by_cluster[cluster.id] = entity_id

    # 4) ApiAction を更新(entityIds を埋める)
    #    同じ action が 2 つのクラスタに所属することは無いが、念のため set で吸収
    updated_actions: list[ApiAction] = []
    action_to_cluster_ids: dict[str, list[str]] = {}
    for cluster in clusters:
        for a in cluster.actions:
            action_to_cluster_ids.setdefault(str(a.id), []).append(cluster.id)

    for a in api_actions:
        cluster_ids = action_to_cluster_ids.get(str(a.id), [])
        entity_ids: list[str] = []
        for cid in cluster_ids:
            eid = entity_id_by_cluster.get(cid)
            if eid and eid not in entity_ids:
                entity_ids.append(eid)
        if entity_ids == list(a.entityIds):
            updated_actions.append(a)
            continue
        updated_actions.append(
            a.model_copy(
                update={
                    "entityIds": entity_ids,
                    # observed はそのままコピー
                    "observed": a.observed.model_copy(),
                }
            )
        )

    return entities, updated_actions


__all__ = [
    "EntityFieldProposal",
    "EntityProposal",
    "ProposeEntitiesOutput",
    "infer_entities",
]


# Silence unused import warning for ApiActionObserved (used for re-export
# opportunities by callers / tests).
_ = ApiActionObserved
