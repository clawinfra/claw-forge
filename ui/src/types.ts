/**
 * TypeScript types for claw-forge Kanban UI.
 * These mirror the backend SQLAlchemy models and WebSocket event payloads.
 */

// ── Feature / Task status ─────────────────────────────────────────────────────

export type FeatureStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "blocked";

/** Maps backend Task to a Kanban-friendly Feature representation. */
export interface Feature {
  id: string;
  name: string;
  category: string;
  status: FeatureStatus;
  priority: number;
  /** List of task IDs this feature depends on */
  depends_on: string[];
  /** Agent session ID when in progress */
  session_id?: string;
  /** 0–100 progress percentage */
  progress?: number;
  /** Cost incurred for this feature in USD */
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  error_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  /** Description (optional) */
  description?: string;
  /** Steps list (optional) */
  steps?: string[];
}

// ── Provider / Pool ───────────────────────────────────────────────────────────

export type ProviderHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ProviderStatus {
  name: string;
  type: string;
  health: ProviderHealth;
  /** Requests per minute (recent 60s window) */
  rpm: number;
  max_rpm: number;
  /** Circuit breaker state: closed | open | half_open */
  circuit_state: "closed" | "open" | "half_open";
  /** Accumulated cost in USD */
  total_cost_usd: number;
  /** Average latency in ms */
  avg_latency_ms: number;
  enabled: boolean;
  /** Model identifier (e.g. "claude-sonnet-4-20250514") */
  model?: string;
  /** Routing priority (lower = higher priority) */
  priority?: number;
  /** Map of logical alias → model ID (from config model_map) */
  model_map?: Record<string, string>;
  /** Ordered list of active tier aliases (cheapest → most capable) */
  active_tiers?: string[];
}

// ── Project summary ───────────────────────────────────────────────────────────

export interface ProjectSummary {
  name: string;
  total_features: number;
  passing: number;
  failing: number;
  pending: number;
  in_progress: number;
  blocked: number;
  active_agents: number;
  total_cost_usd: number;
}

// ── WebSocket event payloads ──────────────────────────────────────────────────

export interface FeatureUpdateEvent {
  type: "feature_update";
  feature: Feature;
}

export interface PoolUpdateEvent {
  type: "pool_update";
  providers: ProviderStatus[];
}

export interface AgentStartedEvent {
  type: "agent_started";
  session_id: string;
  feature_id: string | number;
}

export interface AgentCompletedEvent {
  type: "agent_completed";
  session_id: string;
  feature_id: string | number;
  passed: boolean;
}

export interface CostUpdateEvent {
  type: "cost_update";
  total_cost: number;
  session_cost: number;
}

export interface RegressionStartedEvent {
  type: "regression_started";
  run_number: number;
}

export interface RegressionResultEvent {
  type: "regression_result";
  passed: boolean;
  total: number;
  failed: number;
  failed_tests: string[];
  duration_ms: number;
  run_number: number;
  implicated_feature_ids: number[];
  output: string;
}

export interface AgentLogEvent {
  type: "agent_log";
  task_id: string;
  task_name: string;
  role: "assistant" | "tool_use" | "tool_result" | "result" | "error";
  content: string;
  level: "info" | "warning" | "error";
  model?: string;
}

export type WsEvent =
  | FeatureUpdateEvent
  | PoolUpdateEvent
  | AgentStartedEvent
  | AgentCompletedEvent
  | CostUpdateEvent
  | RegressionStartedEvent
  | RegressionResultEvent
  | AgentLogEvent;

// ── Kanban columns ────────────────────────────────────────────────────────────

export interface KanbanColumn {
  id: FeatureStatus | "in_progress";
  label: string;
  statuses: FeatureStatus[];
  colorClass: string;
  headerClass: string;
  darkColorClass: string;
  darkHeaderClass: string;
}

export const KANBAN_COLUMNS: KanbanColumn[] = [
  {
    id: "pending",
    label: "Pending",
    statuses: ["pending", "queued"],
    colorClass: "bg-slate-50 border-slate-200",
    headerClass: "bg-slate-100 text-slate-700",
    darkColorClass: "dark:bg-slate-800/50 dark:border-slate-700",
    darkHeaderClass: "dark:bg-slate-700 dark:text-slate-200",
  },
  {
    id: "in_progress",
    label: "In Progress",
    statuses: ["running"],
    colorClass: "bg-blue-50 border-blue-200",
    headerClass: "bg-blue-100 text-blue-700",
    darkColorClass: "dark:bg-blue-950/30 dark:border-blue-800",
    darkHeaderClass: "dark:bg-blue-900/50 dark:text-blue-200",
  },
  {
    id: "completed",
    label: "Passing",
    statuses: ["completed"],
    colorClass: "bg-emerald-50 border-emerald-200",
    headerClass: "bg-emerald-100 text-emerald-700",
    darkColorClass: "dark:bg-emerald-950/30 dark:border-emerald-800",
    darkHeaderClass: "dark:bg-emerald-900/50 dark:text-emerald-200",
  },
  {
    id: "failed",
    label: "Failed",
    statuses: ["failed"],
    colorClass: "bg-red-50 border-red-200",
    headerClass: "bg-red-100 text-red-700",
    darkColorClass: "dark:bg-red-950/30 dark:border-red-800",
    darkHeaderClass: "dark:bg-red-900/50 dark:text-red-200",
  },
  {
    id: "blocked",
    label: "Blocked",
    statuses: ["blocked"],
    colorClass: "bg-amber-50 border-amber-200",
    headerClass: "bg-amber-100 text-amber-700",
    darkColorClass: "dark:bg-amber-950/30 dark:border-amber-800",
    darkHeaderClass: "dark:bg-amber-900/50 dark:text-amber-200",
  },
];

// ── Provider toggle ───────────────────────────────────────────────────────────

export interface ToggleProviderRequest {
  enabled: boolean;
}

// ── Activity Log ──────────────────────────────────────────────────────────────

export interface ActivityLogEntry {
  id: number;
  timestamp: Date;
  type: WsEvent["type"];
  message: string;
  /** Short task label (only for agent_log events) */
  taskName?: string;
  /** Agent role: assistant, tool_use, tool_result, result, error */
  role?: string;
  /** Log level: info, warning, error */
  level?: "info" | "warning" | "error";
  /** Sequential index of the agent (1-based, slot-reusing) */
  agentIndex?: number;
  /** LLM model identifier used by this agent */
  model?: string;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

export interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info" | "warning";
}

// ── Filter state ──────────────────────────────────────────────────────────────

export interface FilterState {
  search: string;
  category: string;
  statuses: Set<FeatureStatus>;
}

// ── App view mode ─────────────────────────────────────────────────────────────

export type ViewMode = "kanban" | "graph";

// ── Command palette ───────────────────────────────────────────────────────────

export interface CommandArg {
  name: string;
  label: string;
  type: "string" | "number";
  optional: boolean;
}

export interface Command {
  id: string;
  label: string;
  icon: string;
  description: string;
  category: "setup" | "build" | "quality" | "save" | "monitoring" | "fix";
  shortcut?: string;
  args: CommandArg[];
}

export interface Execution {
  execution_id: string;
  command_id: string;
  command_label: string;
  status: "running" | "done" | "failed";
  output: string[];
  exit_code?: number;
  duration_ms?: number;
  started_at: number;
}
