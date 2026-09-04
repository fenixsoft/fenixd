// Fenix Dashboard v3 API 封装 — 复用 v1 后端（/api/*，同源直连，开发期经 umi proxy）

export type DaemonHealth = string;

export interface ProjectSummary {
  name: string;
  path: string;
  daemon: DaemonHealth;
  spec_count: number;
  status_counts: Record<string, number>;
  task_done: number;
  task_total: number;
  problems: number;
  active_runs: number;
  scenario_count: number;
  updated: number;
  description?: string;
  exists?: boolean;
  discovered?: boolean;
  error?: string;
}

export interface OverviewTotals {
  spec_count: number;
  task_done: number;
  task_total: number;
  problems: number;
  active_runs: number;
  spec_updated_today: number;
  spec_updated_week: number;
  active_runs_by_type: Record<string, number>;
  status_counts: Record<string, number>;
}

export interface TokenUsageItem {
  project: string;
  spec: string;
  tokens: number;
  updated: string;
}

export interface OverviewData {
  projects: ProjectSummary[];
  totals: OverviewTotals;
  token_usage: { recent: TokenUsageItem[] };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) msg = body.error;
    } catch {
      // 非 JSON 错误体，保留 HTTP 状态码信息
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function getOverview(): Promise<OverviewData> {
  return request<OverviewData>('/api/overview');
}

export function startProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}/start`, { method: 'POST' });
}

export function stopProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}/stop`, { method: 'POST' });
}

export function deleteProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

// ── 运维记录（/api/admin-activities，与 v1 运维记录页同源） ──

export interface ActivityItem {
  escalation_id?: string;
  project?: string;
  spec?: string;
  severity?: string;
  signal_type?: string;
  summary?: string;
  actions_taken?: string;
  result?: string;
  recommended_action?: string;
  created?: string;
  handled?: boolean;
  handled_by?: string;
  handled_at?: string;
  resolve_note?: string;
  status?: string;
  admin_run_id?: string;
  // fix-admin-disposition-empty-shell：失败处置自解释——error 携带 CLI 失败原因
  error?: string;
}

export interface ProjectActivities {
  name: string;
  activities: ActivityItem[];
}

export interface AdminActivitiesData {
  projects?: ProjectActivities[];
  project?: string;
  activities?: ActivityItem[];
}

export async function getAdminActivities(project?: string, spec?: string): Promise<AdminActivitiesData> {
  const q = new URLSearchParams();
  if (project) q.set('project', project);
  if (spec) q.set('spec', spec);
  const qs = q.toString();
  return request<AdminActivitiesData>(`/api/admin-activities${qs ? `?${qs}` : ''}`);
}

// ── 人工升级告警（/api/alerts，与 v1 横幅同源） ──

export interface AlertItem {
  id: string;
  project?: string;
  spec?: string;
  severity?: string;
  created?: string;
  description?: string;
  evidence?: string;
  action_taken?: string;
  recommended_action?: string;
  handled?: boolean;
  handled_by?: string;
  handled_at?: string;
  resolve_note?: string;
}

export interface AlertsData {
  alerts: AlertItem[];
  total_unhandled?: number;
  resolved?: AlertItem[];
  error?: string;
}

export async function getAlerts(): Promise<AlertsData> {
  return request<AlertsData>('/api/alerts');
}

export function markAlertHandled(project: string | undefined, id: string) {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request(`/api/alerts/${encodeURIComponent(id)}/handled${q}`, { method: 'POST' });
}

export function clearAllAlerts() {
  return request('/api/alerts/clear', { method: 'POST' });
}

// ── 项目 SPEC 列表（/api/specs，与 v1 项目视图同源） ──

export interface SpecSummary {
  name: string;
  status: string | null;
  mode?: 'fast-track' | 'full' | null;
  /** add-spec-archive：是否已归档（活跃目录 openspec/changes/<name>/ 不存在即 true） */
  archived?: boolean;
  priority: number | null;
  created: string | null;
  updated: string | null;
  error: string | null;
  task_done: number;
  task_total: number;
  /** run 层实时进度（fix-implementer-task-progress D3）：不依赖 tasks.md 编号 */
  run_progress?: { done: number; total: number; current?: string[] } | null;
  verify_done: number;
  verify_total: number;
  verify_error: string | null;
  scenario_count: number;
  total_duration: number;
  latest_run: string | null;
  latest_run_status: string | null;
}

export async function getSpecs(project: string): Promise<{ project: string; specs: SpecSummary[] }> {
  return request(`/api/specs?project=${encodeURIComponent(project)}`);
}

// SPEC 行内操作（与 v1 右键菜单/文档弹窗同源端点）

export function setSpecPriority(project: string, spec: string, priority: number) {
  return request(
    `/api/spec-priority?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ priority }) },
  );
}

export function deleteSpec(project: string, spec: string) {
  return request(
    `/api/spec-delete?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

export function clearSpecError(project: string, spec: string) {
  return request(
    `/api/spec-error-clear?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

export function invokeSpecAdmin(project: string, spec: string, prompt?: string) {
  return request(
    `/api/spec-admin-invoke?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prompt ? { prompt } : {}),
    },
  );
}

export function freezeSpec(project: string, spec: string) {
  return request(
    `/api/spec-freeze?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

export function unfreezeSpec(project: string, spec: string) {
  return request(
    `/api/spec-unfreeze?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

export function archiveSpec(project: string, spec: string) {
  return request<{ ok: boolean; from: string; to: string }>(
    `/api/spec-archive?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

/** add-run-cancel：发起 run 取消请求（POST /api/run-cancel） */
export function cancelRun(project: string, runId: string, reason?: string) {
  return request<{ requested: boolean; project: string; run_id: string; created?: string }>(
    `/api/run-cancel?project=${encodeURIComponent(project)}&run_id=${encodeURIComponent(runId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || '' }),
    },
  );
}

export async function getSpecDoc(
  project: string,
  spec: string,
  doc: 'proposal' | 'design' | 'tasks' | 'verification' | 'scenarios',
): Promise<{ found: boolean; content: string }> {
  return request(
    `/api/spec-doc?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}&doc=${doc}`,
  );
}

// ── SPEC 详情（/api/specs/<spec>?project=，聚合 verdict/verify/tasks/timeline/scenarios/bugs/screenshots/token_usage） ──

export interface SpecDetail {
  name: string;
  project: string;
  status: string | null;
  mode?: 'fast-track' | 'full' | null;
  priority: number | null;
  created: string | null;
  updated: string | null;
  error: string | null;
  branch?: string | null;
  depends_on?: string | null;
  // 验证结论 — 对应后端 data.py parse_verdict() 返回结构
  verdict?: {
    exists: boolean;
    status: string;
    status_detail: string;
    conclusion: string;
    summary?: {
      passed: string | null;
      failed: string | null;
      errors: string | null;
      product_bugs: string | null;
      env_issues: string | null;
    };
  };
  // 验证进度 — 后端字段名 verify_progress（parse_verify_progress() 返回结构）
  verify_progress?: {
    exists: boolean;
    done: number;
    total: number;
    current?: string;
    step?: string | null;
    error?: string | null;
  };
  // run 层实时进度 — run_task_progress() 返回结构（不依赖 tasks.md 编号）
  run_progress?: { done: number; total: number; current?: string[] } | null;
  // 任务清单 — parse_tasks() 返回的分组数组（非 {groups} 包装）
  tasks?: Array<{
    title: string;
    done: number;
    total: number;
    tasks: Array<{
      id: string;
      desc: string;
      done: boolean;
    }>;
  }>;
  // tasks.md 空解析显式提示（task-track R3）— 存在但未解析出任务分组时非空
  tasks_note?: string | null;
  // 时间轴 — 状态节点字段为 from/to，运行节点为 agent_type（get_spec_timeline 返回结构）
  timeline?: Array<{
    kind: 'state' | 'run';
    time: string;
    from?: string;
    to?: string;
    reason?: string;
    run_id?: string;
    agent_type?: string;
    status?: string;
    duration_seconds?: number;
    spec?: string;
    // 运行节点：ClaudeCode 最后一条总结（result 事件的 result 字段，兜底 assistant 文本）
    summary?: string;
    // 运行节点：实际驱动的 LLM（provider_marker 的 model@provider，failover 取最后一个）
    llm?: string;
    // 运行节点：spec 当前实现重试轮次（仅最新 run 节点携带，>0 时出现；_timeline_with_retry）
    retry_count?: number;
    retry_max?: number;
  }>;
  // 场景结果 — report.json 的 scenarios 平铺数组（parse_report）
  scenarios?: Array<{
    scenario_id: string;
    description?: string;
    status: 'pass' | 'warning' | 'fail' | 'error';
    step_results?: Array<{
      success: boolean;
      action?: string;
      description?: string;
      detail?: string;
      error?: string;
    }>;
    assertion_results?: Array<{
      pass?: boolean;
      type?: string;
      label?: string;
      message?: string;
      detail?: string;
      error?: string;
      actual?: string | number;
      // 引擎按类型输出的字段（core/verify_engine/assertions.py 口径），见 detail.tsx assertionDetail
      selector?: string;
      expected?: string | number;
      text?: string;
      attribute?: string;
      mode?: string;
      errors?: string[];
      filtered_network?: string[];
      matched?: string[];
      parent?: string;
      child?: string;
      relation?: string;
      actual_count?: number;
      compare_selector?: string;
      z_index_self?: number;
      z_index_compare?: number;
      operator?: string;
    }>;
    screenshots?: string[];
  }>;
  // report.json 元信息（损坏时 error 非空）
  report?: {
    exists?: boolean;
    error?: string | null;
    timestamp?: string | null;
    summary?: {
      total?: number;
      passed?: number;
      warnings?: number;
      failed?: number;
      errors?: number;
      blocked_env?: number;
    };
  };
  // Bug 列表
  bugs?: Array<{
    id: string;
    severity: 'critical' | 'major' | 'minor' | 'info';
    source?: string;
    description: string;
    scenario?: string;
    assertion?: string;
    evidence?: string;
    screenshots?: string[];
  }>;
  // 失败截图 — list_screenshots() 返回 {file,size,mtime} 对象数组（非纯文件名）
  screenshots?: Array<{
    file: string;
    size?: number;
    mtime?: string;
  }>;
  // Token 用量 — cost_usd 仅网关真实回传时存在（金额展示不伪造）；
  // cache 分项为 null 表示该 spec 未记录过分项数据（历史条目），前端不显示缓存括号
  token_usage?: {
    tokens_in: number;
    tokens_out: number;
    cache_creation_input_tokens?: number | null;
    cache_read_input_tokens?: number | null;
    cost_usd?: number | null;
    cost_available?: boolean;
  };
}

export async function getSpecDetail(project: string, spec: string): Promise<SpecDetail> {
  return request<SpecDetail>(
    `/api/specs/${encodeURIComponent(spec)}?project=${encodeURIComponent(project)}`,
  );
}

// ── 运行流（/api/runs/<run_id> 系列端点，与 v1 run watch 同源） ──

export interface RunEvent {
  type: string;
  run_id: string;
  agent?: string;
  status?: string;
  content?: string;
  timestamp?: string;
  thinking?: boolean;
  reset?: boolean;
  events?: RunEvent[];
  total_events?: number;
}

export interface RunDetail {
  run_id: string;
  status: string;
  error?: string;
  events: RunEvent[];
  total_events: number;
}

export async function getRunTail(runId: string, project: string, tail: number = 300): Promise<RunDetail> {
  return request<RunDetail>(
    `/api/runs/${encodeURIComponent(runId)}?project=${encodeURIComponent(project)}&tail=${tail}`,
  );
}

export async function registerRunWatch(runId: string, project: string, cid: string): Promise<void> {
  await request(
    `/api/runs/${encodeURIComponent(runId)}/watch?project=${encodeURIComponent(project)}&cid=${encodeURIComponent(cid)}`,
    { method: 'POST' },
  );
}

export async function unregisterRunWatch(runId: string, project: string, cid: string): Promise<void> {
  await request(
    `/api/runs/${encodeURIComponent(runId)}/watch?project=${encodeURIComponent(project)}&cid=${encodeURIComponent(cid)}`,
    { method: 'DELETE' },
  );
}

// ── SPEC 状态元数据（中文标签 + 语义色，与 v1 STATUS_META 对齐） ──

export type StatusTone = 'muted' | 'info' | 'warning' | 'critical' | 'good' | 'aqua';

export const STATUS_META: Record<string, { label: string; tone: StatusTone }> = {
  drafted: { label: '草稿', tone: 'muted' },
  ready: { label: '就绪', tone: 'info' },
  implementing: { label: '实现中', tone: 'warning' },
  implemented: { label: '已实现', tone: 'aqua' },
  testing: { label: '验证中', tone: 'info' },
  verified: { label: '已验证', tone: 'good' },
  'bug-found': { label: '有Bug', tone: 'critical' },
  blocked: { label: '阻塞', tone: 'critical' },
  done: { label: '完成', tone: 'good' },
  pushed: { label: '已推送', tone: 'good' },
};

export function statusMeta(status: string): { label: string; tone: StatusTone } {
  return STATUS_META[status] || { label: status || '未知', tone: 'muted' };
}

// ── 配置管理（/api/config，复用 v1 后端） ──

export interface LlmProvider {
  name: string;
  baseurl: string;
  apikey: string;
  // 与后端 YAML 字段一致：默认模型为 model，env 为运行时注入子进程的环境变量
  model?: string;
  env?: Record<string, string>;
}

export interface LlmConfig {
  providers?: LlmProvider[];
}

// 后端 normalize_agent_models 规范化视图：provider 链统一为对象数组，
// model 为解析后值（元素自带 > 角色级 > provider 默认），无法解析时为 null
export interface AgentModelChainElement {
  provider: string;
  model?: string | null;
}

export interface AgentModelAssignment {
  model?: string | null;
  provider: string | AgentModelChainElement | AgentModelChainElement[];
}

export interface AgentsModels {
  [role: string]: AgentModelAssignment;
}

export interface AgentsConfig {
  models?: AgentsModels;
  max_concurrent?: number;
  max_turns?: number;
  run_timeout_seconds?: number;
  daily_run_limit?: number;
  token_budget_millions?: number;
  impl_run_budget?: number;
}

export interface GatesConfig {
  approve_mode?: 'manual' | 'auto';
}

export interface VerifyConfig {
  /** static 验证契约的服务范围：main=主树（方案 1，默认）| worktree=验证 worktree（方案 2） */
  static_scope?: 'main' | 'worktree';
}

export interface SelfReviewConfig {
  /** 每日自省总开关（add-daily-self-review，缺省 false） */
  enabled?: boolean;
  /** 每晚执行时间 HH:MM（缺省 02:00） */
  run_at?: string;
  /** 是否把既有 todo.md 全文注入自省 prompt（缺省 false） */
  read_todo?: boolean;
}

export interface ConfigData {
  llm: LlmConfig;
  agents: AgentsConfig;
  gates: GatesConfig;
  /** 验证契约：详见 .fenix/verify.yaml 与 core/verify_contract.py */
  verify?: VerifyConfig;
  /** add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50） */
  archive?: { auto_threshold: number };
  /** add-daily-self-review：每日自省（admin.self_review 三键） */
  self_review?: SelfReviewConfig;
  scope: 'user' | 'project';
  raw_exists: boolean;
  sources: Record<string, string>;
  error?: string;
  project?: string;
  description?: string;
  saved?: boolean;
  path?: string;
}

export async function getConfig(project?: string): Promise<ConfigData> {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<ConfigData>(`/api/config${q}`);
}

export async function saveConfig(
  project: string | undefined,
  payload: Partial<ConfigData>,
): Promise<ConfigData> {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<ConfigData>(`/api/config${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function regenerateProjectDescription(project: string): Promise<{ ok: boolean; description?: string; error?: string }> {
  return request<{ ok: boolean; description?: string; error?: string }>(
    `/api/project/describe?project=${encodeURIComponent(project)}`,
    { method: 'POST' },
  );
}

// ── agent 提示词（add-agent-prompt-files 任务 3.2）─────────────────────

export interface AgentPrompt {
  type: string;
  file: string;
  content: string;
}

export interface ProjectPromptsMeta {
  name: string;
  path: string;
  /** 自引用项目（.fenix 解析为框架根）：项目级即通用层，编辑禁用 */
  self_referencing: boolean;
  extras: Record<string, string>;
}

export interface PromptsData {
  agents: AgentPrompt[];
  project?: ProjectPromptsMeta;
}

export async function getPrompts(project?: string): Promise<PromptsData> {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<PromptsData>(`/api/prompts${q}`);
}

export async function saveProjectPrompt(
  project: string,
  agentType: string,
  content: string,
): Promise<{ ok: boolean; agent_type: string; path: string }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request(`/api/prompts${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_type: agentType, content }),
  });
}

// ── 帮助中心（/api/help/*，读取框架仓库 docs/help/）──

export interface HelpDocMeta {
  name: string;
  title: string;
}

export interface HelpDocItem extends HelpDocMeta {
  content: string;
}

export async function getHelpDocs(): Promise<{ docs: HelpDocMeta[] }> {
  return request<{ docs: HelpDocMeta[] }>('/api/help/docs');
}

export async function getHelpDoc(name: string): Promise<HelpDocItem> {
  const q = `?name=${encodeURIComponent(name)}`;
  return request<HelpDocItem>(`/api/help/doc${q}`);
}
