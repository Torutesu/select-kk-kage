/**
 * KAGE IR (Intermediate Representation) Schema
 *
 * すべてのパッケージ(pipeline / editor / generator / validator)はこれに依存する。
 * Week 1 Day 3 以降、破壊的変更は全体レビュー必須。
 *
 * 設計原則:
 * - 「LLMが推測した内容」と「確定した事実」を `confidence` で区別する
 * - 人間が editor で編集する可能性のある箇所は `editable: true` として扱う
 * - 生成物を逆算で再現できる情報量を持つ
 */

import { z } from "zod";

// ─────────────────────────────────────────────────────────────
// Primitives
// ─────────────────────────────────────────────────────────────

export const ConfidenceSchema = z.enum(["high", "medium", "low"]);
export type Confidence = z.infer<typeof ConfidenceSchema>;

/** 1ピクセル単位の矩形 */
export const BoundingBoxSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number(),
});
export type BoundingBox = z.infer<typeof BoundingBoxSchema>;

/** デザイントークン(色・タイポ・間隔) */
export const DesignTokensSchema = z.object({
  colors: z.record(z.string(), z.string()).default({}), // e.g. { primary: "#0A0A0A" }
  fontFamilies: z.array(z.string()).default([]),
  fontSizes: z.array(z.number()).default([]),
  spacing: z.array(z.number()).default([]),
  borderRadius: z.array(z.number()).default([]),
});
export type DesignTokens = z.infer<typeof DesignTokensSchema>;

// ─────────────────────────────────────────────────────────────
// Component Tree
// ─────────────────────────────────────────────────────────────

/**
 * shadcn/ui のコンポーネント名に揃える。
 * マッチしない場合は `Custom` として、原DOMを保持する。
 */
export const ComponentKindSchema = z.enum([
  // Layout
  "Container", "Card", "Stack", "Grid", "Separator", "ScrollArea",
  // Navigation
  "Sidebar", "Navbar", "Tabs", "Breadcrumb", "Pagination",
  // Data Display
  "Table", "DataTable", "List", "Badge", "Avatar", "Skeleton",
  // Form
  "Form", "Input", "Textarea", "Select", "Checkbox", "Radio", "Switch", "Slider",
  // Feedback
  "Toast", "Alert", "Dialog", "Drawer", "Popover", "Tooltip",
  // Action
  "Button", "DropdownMenu", "ContextMenu", "Command",
  // Text
  "Heading", "Paragraph", "Link", "Label",
  // Media
  "Image", "Video", "Icon",
  // Escape hatch
  "Custom",
]);
export type ComponentKind = z.infer<typeof ComponentKindSchema>;

/**
 * 1つの UI コンポーネント。
 * 再帰構造なので型を先に宣言 → z.lazy で参照。
 */
export type Component = {
  id: string; // uuid
  kind: ComponentKind;
  /** Custom のときの元DOM情報(タグ名、クラスなど) */
  customFallback?: {
    tagName: string;
    className?: string;
    role?: string;
  };
  /** shadcn/ui のバリアント。例: Button の variant="outline" */
  variant?: string;
  /** 表示テキスト(ボタンラベル、ヘッディング内容等) */
  text?: string;
  /** 画像/動画の URL やアイコン名 */
  src?: string;
  /** プロップス。生成時に JSX の属性になる */
  props: Record<string, z.ZodTypeAny extends never ? never : unknown>;
  /** 子要素 */
  children: Component[];
  /** 画面上の位置(レイアウト推論用、必須ではない) */
  bbox?: BoundingBox;
  /** このコンポーネントにバインドされた data(後述の DataBinding の id) */
  dataBindingIds: string[];
  /** 発火するイベント(後述の ActionRef の id) */
  actionIds: string[];
  /** LLM推測かDOMから確定か */
  confidence: Confidence;
  /** 推論の根拠(デバッグ用、editor で表示) */
  evidence?: string[];
};

export const ComponentSchema: z.ZodType<Component> = z.lazy(() =>
  z.object({
    id: z.string().uuid(),
    kind: ComponentKindSchema,
    customFallback: z
      .object({
        tagName: z.string(),
        className: z.string().optional(),
        role: z.string().optional(),
      })
      .optional(),
    variant: z.string().optional(),
    text: z.string().optional(),
    src: z.string().optional(),
    props: z.record(z.string(), z.unknown()),
    children: z.array(ComponentSchema),
    bbox: BoundingBoxSchema.optional(),
    dataBindingIds: z.array(z.string()),
    actionIds: z.array(z.string()),
    confidence: ConfidenceSchema,
    evidence: z.array(z.string()).optional(),
  })
);

// ─────────────────────────────────────────────────────────────
// Screen
// ─────────────────────────────────────────────────────────────

/** 1つの画面(URL + コンポーネントツリー) */
export const ScreenSchema = z.object({
  id: z.string().uuid(),
  /** ファイル名の元になる slug。例: "dashboard", "settings-profile" */
  slug: z.string().regex(/^[a-z0-9-]+$/),
  /** App Router の route パス。例: "/dashboard", "/users/[id]" */
  route: z.string(),
  /** 元録画での URL */
  originalUrl: z.string().url(),
  /** 認証が必要か(HARで判定、middleware生成に使う) */
  requiresAuth: z.boolean(),
  /** このスクリーンに必要な初期データ(DataBinding の id) */
  initialDataBindingIds: z.array(z.string()),
  /** ルートコンポーネント */
  root: ComponentSchema,
  /** スクリーンショット(base64 or 相対パス、デバッグ用) */
  screenshot: z.string().optional(),
  confidence: ConfidenceSchema,
});
export type Screen = z.infer<typeof ScreenSchema>;

// ─────────────────────────────────────────────────────────────
// Screen Graph (画面遷移)
// ─────────────────────────────────────────────────────────────

/** トリガー: クリック、フォーム送信、API呼び出し後、など */
export const TriggerSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("click"),
    componentId: z.string().uuid(),
  }),
  z.object({
    type: z.literal("submit"),
    componentId: z.string().uuid(),
  }),
  z.object({
    type: z.literal("api_success"),
    actionId: z.string().uuid(),
  }),
  z.object({
    type: z.literal("api_error"),
    actionId: z.string().uuid(),
  }),
  z.object({
    type: z.literal("timeout"),
    ms: z.number(),
  }),
  z.object({
    type: z.literal("nav_direct"),
    note: z.string().optional(),
  }),
]);
export type Trigger = z.infer<typeof TriggerSchema>;

/** 画面遷移の1エッジ */
export const TransitionSchema = z.object({
  id: z.string().uuid(),
  from: z.string().uuid(), // Screen.id
  to: z.string().uuid(), // Screen.id
  trigger: TriggerSchema,
  /** この遷移で実行されるアクション(順番に実行) */
  actionIds: z.array(z.string()),
  /** 遷移後に更新される共有状態(SharedState の id) */
  updatesSharedStateIds: z.array(z.string()),
  confidence: ConfidenceSchema,
});
export type Transition = z.infer<typeof TransitionSchema>;

/** 画面を跨ぐ共有状態(currentUser, selectedWorkspace など) */
export const SharedStateSchema = z.object({
  id: z.string().uuid(),
  name: z.string(), // e.g. "currentUser", "selectedWorkspaceId"
  type: z.string(), // TypeScript型として書ける形。e.g. "User | null", "string"
  initialValue: z.string(), // リテラル表現。e.g. "null", '""'
  /** Zustand / Context / URL param / LocalStorage どれか */
  persistence: z.enum(["memory", "localStorage", "url", "cookie"]),
  confidence: ConfidenceSchema,
  evidence: z.array(z.string()).optional(),
});
export type SharedState = z.infer<typeof SharedStateSchema>;

// ─────────────────────────────────────────────────────────────
// Backend Inference (HAR から推測した DB スキーマ + API)
// ─────────────────────────────────────────────────────────────

/** DB フィールド */
export const EntityFieldSchema = z.object({
  name: z.string(),
  type: z.enum([
    "String",
    "Int",
    "BigInt",
    "Float",
    "Decimal",
    "Boolean",
    "DateTime",
    "Json",
    "Bytes",
    "Enum",
    "Relation",
  ]),
  /** Relation の場合の参照先 Entity.id */
  relationTargetEntityId: z.string().uuid().optional(),
  /** Enum の場合の値 */
  enumValues: z.array(z.string()).optional(),
  optional: z.boolean().default(false),
  unique: z.boolean().default(false),
  isId: z.boolean().default(false),
  isCreatedAt: z.boolean().default(false),
  isUpdatedAt: z.boolean().default(false),
  evidence: z.array(z.string()).default([]),
});
export type EntityField = z.infer<typeof EntityFieldSchema>;

/** DB テーブル相当 */
export const EntitySchema = z.object({
  id: z.string().uuid(),
  name: z.string(), // PascalCase, e.g. "User", "Project"
  fields: z.array(EntityFieldSchema),
  confidence: ConfidenceSchema,
  evidence: z.array(z.string()).default([]),
  /** LLM が「これ確認したい」と出した質問 */
  questions: z.array(z.string()).default([]),
});
export type Entity = z.infer<typeof EntitySchema>;

/** API エンドポイント(tRPC procedure に変換される) */
export const ApiActionSchema = z.object({
  id: z.string().uuid(),
  name: z.string(), // e.g. "users.list", "projects.create"
  kind: z.enum(["query", "mutation"]),
  /** 実通信で観測した情報 */
  observed: z.object({
    method: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]),
    urlPattern: z.string(), // e.g. "/api/users/:id"
    requestSchema: z.unknown().optional(), // JSON Schema
    responseSchema: z.unknown().optional(),
    sampleRequest: z.unknown().optional(),
    sampleResponse: z.unknown().optional(),
  }),
  /** 関連エンティティ */
  entityIds: z.array(z.string()),
  confidence: ConfidenceSchema,
});
export type ApiAction = z.infer<typeof ApiActionSchema>;

/** UI と data の結びつき。例: Table のデータは users.list の結果 */
export const DataBindingSchema = z.object({
  id: z.string().uuid(),
  /** 参照する API action */
  apiActionId: z.string().uuid(),
  /** render のための variable 名。TSコード上で使われる。 */
  variableName: z.string(), // e.g. "users", "currentProject"
  /** クライアントキャッシュキー(TanStack Query の queryKey) */
  queryKey: z.array(z.union([z.string(), z.number()])),
});
export type DataBinding = z.infer<typeof DataBindingSchema>;

// ─────────────────────────────────────────────────────────────
// Root IR
// ─────────────────────────────────────────────────────────────

export const IRSchema = z.object({
  /** スキーマバージョン。破壊的変更のときだけ上げる。 */
  version: z.literal("1.0.0"),
  /** 録画元の情報 */
  source: z.object({
    targetUrl: z.string().url(),
    recordedAt: z.string().datetime(),
    durationSeconds: z.number(),
    captureTool: z.literal("kage-capture"),
  }),
  /** プロジェクト名(生成先ディレクトリ名にもなる) */
  projectName: z.string().regex(/^[a-z0-9-]+$/),
  /** デザイントークン */
  designTokens: DesignTokensSchema,
  /** 画面一覧 */
  screens: z.array(ScreenSchema),
  /** 遷移一覧 */
  transitions: z.array(TransitionSchema),
  /** 共有状態 */
  sharedStates: z.array(SharedStateSchema),
  /** 推測されたバックエンドエンティティ */
  entities: z.array(EntitySchema),
  /** API アクション */
  apiActions: z.array(ApiActionSchema),
  /** データバインディング */
  dataBindings: z.array(DataBindingSchema),
  /** 認証が必要か(middleware生成の大元フラグ) */
  hasAuth: z.boolean(),
  /** LLM から人間への確認事項(editor で赤く表示) */
  openQuestions: z.array(
    z.object({
      id: z.string().uuid(),
      question: z.string(),
      relatedIds: z.array(z.string()),
      severity: z.enum(["blocker", "warning", "info"]),
    })
  ),
});
export type IR = z.infer<typeof IRSchema>;

// ─────────────────────────────────────────────────────────────
// Validation helpers
// ─────────────────────────────────────────────────────────────

/**
 * IR の整合性チェック(スキーマ外の制約)。
 * 例: transition.from が存在する Screen か、dataBinding.apiActionId が ApiAction に存在するか。
 */
export function validateIRIntegrity(ir: IR): string[] {
  const errors: string[] = [];

  const screenIds = new Set(ir.screens.map((s) => s.id));
  const actionIds = new Set(ir.apiActions.map((a) => a.id));
  const entityIds = new Set(ir.entities.map((e) => e.id));
  const dataBindingIds = new Set(ir.dataBindings.map((d) => d.id));
  const sharedStateIds = new Set(ir.sharedStates.map((s) => s.id));

  for (const t of ir.transitions) {
    if (!screenIds.has(t.from)) errors.push(`transition ${t.id}: from ${t.from} not found`);
    if (!screenIds.has(t.to)) errors.push(`transition ${t.id}: to ${t.to} not found`);
    for (const aid of t.actionIds) {
      if (!actionIds.has(aid)) errors.push(`transition ${t.id}: action ${aid} not found`);
    }
    for (const sid of t.updatesSharedStateIds) {
      if (!sharedStateIds.has(sid)) errors.push(`transition ${t.id}: sharedState ${sid} not found`);
    }
  }

  for (const db of ir.dataBindings) {
    if (!actionIds.has(db.apiActionId)) {
      errors.push(`dataBinding ${db.id}: apiAction ${db.apiActionId} not found`);
    }
  }

  for (const s of ir.screens) {
    for (const dbId of s.initialDataBindingIds) {
      if (!dataBindingIds.has(dbId)) {
        errors.push(`screen ${s.id}: initialDataBinding ${dbId} not found`);
      }
    }
  }

  for (const action of ir.apiActions) {
    for (const eid of action.entityIds) {
      if (!entityIds.has(eid)) {
        errors.push(`apiAction ${action.id}: entity ${eid} not found`);
      }
    }
  }

  // Component ツリー内の参照チェック
  const walkComponent = (c: Component, screenId: string): void => {
    for (const dbId of c.dataBindingIds) {
      if (!dataBindingIds.has(dbId)) {
        errors.push(`component ${c.id} in screen ${screenId}: dataBinding ${dbId} not found`);
      }
    }
    for (const aid of c.actionIds) {
      if (!actionIds.has(aid)) {
        errors.push(`component ${c.id} in screen ${screenId}: action ${aid} not found`);
      }
    }
    for (const child of c.children) walkComponent(child, screenId);
  };
  for (const s of ir.screens) walkComponent(s.root, s.id);

  return errors;
}
