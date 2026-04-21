"""
Python mirror of @kage/ir (src/schema.ts v1.0.0).

TS 側の Zod スキーマと同じ shape を満たす pydantic モデル。
TS を変えたらここも必ず追従する(packages/ir/README.md 参照)。

Pipeline 側は生成者(IR を作る)なので、厳密な型で validate しつつ JSON 出力する。
Editor / generator 側で再度 TS Zod で parse して整合性を担保する二重チェック構造。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────
# Primitives
# ─────────────────────────────────────────────────────────────

Confidence = Literal["high", "medium", "low"]


class StrictModel(BaseModel):
    """全モデルの基底。extra=forbid で誤field をすぐ検出する。"""

    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


class BoundingBox(StrictModel):
    x: float
    y: float
    width: float
    height: float


class DesignTokens(StrictModel):
    colors: dict[str, str] = Field(default_factory=dict)
    fontFamilies: list[str] = Field(default_factory=list)
    fontSizes: list[float] = Field(default_factory=list)
    spacing: list[float] = Field(default_factory=list)
    borderRadius: list[float] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Component Tree
# ─────────────────────────────────────────────────────────────

ComponentKind = Literal[
    # Layout
    "Container", "Card", "Stack", "Grid", "Separator", "ScrollArea",
    # Navigation
    "Sidebar", "Navbar", "Tabs", "Breadcrumb", "Pagination",
    # Data Display
    "Table", "DataTable", "List", "Badge", "Avatar", "Skeleton",
    # Form
    "Form", "Input", "Textarea", "Select", "Checkbox", "Radio", "Switch", "Slider",
    # Feedback
    "Toast", "Alert", "Dialog", "Drawer", "Popover", "Tooltip",
    # Action
    "Button", "DropdownMenu", "ContextMenu", "Command",
    # Text
    "Heading", "Paragraph", "Link", "Label",
    # Media
    "Image", "Video", "Icon",
    # Escape hatch
    "Custom",
]


class CustomFallback(StrictModel):
    tagName: str
    className: str | None = None
    role: str | None = None


class Component(StrictModel):
    id: UUID
    kind: ComponentKind
    customFallback: CustomFallback | None = None
    variant: str | None = None
    text: str | None = None
    src: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    children: list[Component] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    dataBindingIds: list[str] = Field(default_factory=list)
    actionIds: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"
    evidence: list[str] | None = None


# ─────────────────────────────────────────────────────────────
# Screen
# ─────────────────────────────────────────────────────────────


class Screen(StrictModel):
    id: UUID
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    route: str
    originalUrl: str
    requiresAuth: bool
    initialDataBindingIds: list[str] = Field(default_factory=list)
    root: Component
    screenshot: str | None = None
    confidence: Confidence


# ─────────────────────────────────────────────────────────────
# Screen Graph (transitions)
# ─────────────────────────────────────────────────────────────


class TriggerClick(StrictModel):
    type: Literal["click"]
    componentId: UUID


class TriggerSubmit(StrictModel):
    type: Literal["submit"]
    componentId: UUID


class TriggerApiSuccess(StrictModel):
    type: Literal["api_success"]
    actionId: UUID


class TriggerApiError(StrictModel):
    type: Literal["api_error"]
    actionId: UUID


class TriggerTimeout(StrictModel):
    type: Literal["timeout"]
    ms: float


class TriggerNavDirect(StrictModel):
    type: Literal["nav_direct"]
    note: str | None = None


Trigger = (
    TriggerClick
    | TriggerSubmit
    | TriggerApiSuccess
    | TriggerApiError
    | TriggerTimeout
    | TriggerNavDirect
)


class Transition(StrictModel):
    id: UUID
    from_: UUID = Field(alias="from")
    to: UUID
    trigger: Trigger = Field(discriminator="type")
    actionIds: list[str] = Field(default_factory=list)
    updatesSharedStateIds: list[str] = Field(default_factory=list)
    confidence: Confidence

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SharedState(StrictModel):
    id: UUID
    name: str
    type: str
    initialValue: str
    persistence: Literal["memory", "localStorage", "url", "cookie"]
    confidence: Confidence
    evidence: list[str] | None = None


# ─────────────────────────────────────────────────────────────
# Backend Inference
# ─────────────────────────────────────────────────────────────

EntityFieldType = Literal[
    "String", "Int", "BigInt", "Float", "Decimal", "Boolean", "DateTime",
    "Json", "Bytes", "Enum", "Relation",
]


class EntityField(StrictModel):
    name: str
    type: EntityFieldType
    relationTargetEntityId: UUID | None = None
    enumValues: list[str] | None = None
    optional: bool = False
    unique: bool = False
    isId: bool = False
    isCreatedAt: bool = False
    isUpdatedAt: bool = False
    evidence: list[str] = Field(default_factory=list)


class Entity(StrictModel):
    id: UUID
    name: str
    fields: list[EntityField] = Field(default_factory=list)
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ApiActionObserved(StrictModel):
    method: HttpMethod
    urlPattern: str
    requestSchema: Any | None = None
    responseSchema: Any | None = None
    sampleRequest: Any | None = None
    sampleResponse: Any | None = None


class ApiAction(StrictModel):
    id: UUID
    name: str
    kind: Literal["query", "mutation"]
    observed: ApiActionObserved
    entityIds: list[str] = Field(default_factory=list)
    confidence: Confidence


class DataBinding(StrictModel):
    id: UUID
    apiActionId: UUID
    variableName: str
    queryKey: list[str | float] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Root IR
# ─────────────────────────────────────────────────────────────


class IRSource(StrictModel):
    targetUrl: str
    recordedAt: str
    durationSeconds: float
    captureTool: Literal["kage-capture"]


class OpenQuestion(StrictModel):
    id: UUID
    question: str
    relatedIds: list[str] = Field(default_factory=list)
    severity: Literal["blocker", "warning", "info"]


class IR(StrictModel):
    version: Literal["1.0.0"] = "1.0.0"
    source: IRSource
    projectName: str = Field(pattern=r"^[a-z0-9-]+$")
    designTokens: DesignTokens = Field(default_factory=DesignTokens)
    screens: list[Screen] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    sharedStates: list[SharedState] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    apiActions: list[ApiAction] = Field(default_factory=list)
    dataBindings: list[DataBinding] = Field(default_factory=list)
    hasAuth: bool = False
    openQuestions: list[OpenQuestion] = Field(default_factory=list)


# Forward-ref resolution (pydantic v2 auto-handles via `from __future__`)
Component.model_rebuild()
