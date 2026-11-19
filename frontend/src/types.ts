export type NodeStatus =
  | "IDLE"
  | "RUNNING"
  | "WAITING_APPROVAL"
  | "PASSED"
  | "FAILED_RETRYING"
  | "FAILED"
  | "DISABLED";

export interface FlowNode {
  id: string;
  display_name: string;
  role_type: string;
  cursor_mode: "plan" | "ask" | "agent" | string;
  model: string;
  provider?: string;
  system_prompt: string;
  behavior_data: Record<string, unknown>;
  enabled_skills: string[];
  require_approval_before: boolean;
  approve_every_entry: boolean;
  max_retries: number;
  timeout_s: number;
  position: { x: number; y: number };
  enabled?: boolean;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  condition: "always" | "on_pass" | "on_fail" | "on_scale_issue" | string;
  source_handle?: string;
  target_handle?: string;
}

export interface Flow {
  id: string;
  name: string;
  entry: string;
  interrupt_before: string[];
  nodes: FlowNode[];
  edges: FlowEdge[];
  is_template?: boolean;
  updated_at?: string;
}

export interface FileChange {
  path: string;
  added: number;
  removed: number;
}

export interface Session {
  id: number;
  feature_id: string;
  agent_id: string;
  chat_id: string;
  files?: FileChange[];
  status: string;
  created_at: string;
  archived_at: string | null;
}

export interface Turn {
  id: number;
  agent_id: string;
  chat_id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface Artifact {
  name: string;
  content: string;
  updated_at: string;
}

export interface Feature {
  id: string;
  name: string;
  prd: string;
  workspace_path: string;
  project_path: string;
  branch: string;
  use_worktree: boolean;
  flow_id: string;
  status: string;
  thread_id: string;
  error: string;
  created_at: string;
  updated_at: string;
  sessions?: Session[];
  artifacts?: Artifact[];
}

export interface SkillFile {
  path: string;
  dest: string;
  content: string;
  customized: boolean;
  present_in_workspace: boolean;
}

export interface Skill {
  id: string;
  name: string;
  summary: string;
  version: string;
  enabled: boolean;
  synced: boolean;
  files: SkillFile[];
}

export interface JedocEvent {
  id?: string;
  type: string;
  node_id?: string;
  status?: string;
  chat_id?: string;
  action?: string;
  started_at?: number;
  text?: string;
  kind?: string;
  name?: string;
  level?: string;
  detail?: string;
  error?: string;
  elapsed_s?: number;
  duration_s?: number;
  configured_duration_s?: number;
  severity?: string;
  table?: string;
  check?: string;
  content?: string;
  files?: FileChange[];
  events?: JedocEvent[];
  feature?: Feature;
  sessions?: Session[];
  artifacts?: Artifact[];
}

export interface GitProject {
  path: string;
  name: string;
  branch: string;
}

export interface GitWorktree {
  path: string;
  branch: string;
  head: string;
}

export interface GitRepo {
  path: string;
  name: string;
  branch: string;
  dirty: boolean;
  branches: string[];
  worktrees: GitWorktree[];
}

export interface ProviderAccount {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  has_api_key: boolean;
  api_key_hint: string;
  endpoint: string;
  models: string[];
  authenticated?: boolean;
  auth_detail?: string;
  installed?: boolean;
  models_error?: string;
}

export interface AgentInfo {
  installed: boolean;
  execution_mode: string;
  authenticated: boolean;
  detail: string;
  path?: string | null;
}

export interface Telemetry {
  status: string;
  chatId: string;
  action: string;
  files: FileChange[];
  startedAt?: number;
}

export interface AuditCard {
  severity: string;
  table: string;
  check: string;
  detail: string;
}

export interface QaProgress {
  elapsed_s: number;
  duration_s: number;
  configured_duration_s?: number;
  action: string;
}
