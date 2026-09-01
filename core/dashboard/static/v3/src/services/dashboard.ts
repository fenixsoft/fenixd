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

export async function getAdminActivities(project?: string): Promise<AdminActivitiesData> {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<AdminActivitiesData>(`/api/admin-activities${q}`);
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
  priority: number | null;
  created: string | null;
  updated: string | null;
  error: string | null;
  task_done: number;
  task_total: number;
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

export function invokeSpecAdmin(project: string, spec: string) {
  return request(
    `/api/spec-admin-invoke?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

export async function getSpecDoc(
  project: string,
  spec: string,
  doc: 'proposal' | 'design' | 'tasks',
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
  priority: number | null;
  created: string | null;
  updated: string | null;
  error: string | null;
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
  // 验证进度
  verify?: {
    done: number;
    total: number;
    error?: string;
  };
  // 任务清单
  tasks?: {
    groups: Array<{
      name: string;
      tasks: Array<{
        description: string;
        done: boolean;
      }>;
    }>;
  };
  // 时间轴
  timeline?: Array<{
    kind: 'state' | 'run';
    time: string;
    state?: string;
    reason?: string;
    run_id?: string;
    agent?: string;
    status?: string;
    duration_seconds?: number;
    spec?: string;
  }>;
  // 场景结果
  scenarios?: {
    report_status?: 'ok' | 'corrupted' | 'missing';
    summary?: {
      passed: number;
      warning: number;
      failed: number;
      error: number;
    };
    items?: Array<{
      scenario_id: string;
      description?: string;
      status: 'passed' | 'warning' | 'failed' | 'error';
      assertions?: Array<{
        passed: boolean;
        message?: string;
      }>;
      steps?: Array<{
        name: string;
        status: 'passed' | 'failed';
        error?: string;
      }>;
    }>;
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
    screenshot?: string;
  }>;
  // 失败截图
  screenshots?: string[];
  // Token 用量
  token_usage?: {
    tokens_in: number;
    tokens_out: number;
    cost?: number | null;
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
  default_model?: string;
}

export interface LlmConfig {
  providers?: LlmProvider[];
}

export interface AgentsModels {
  [role: string]: { provider: string; model: string };
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

export interface ConfigData {
  llm: LlmConfig;
  agents: AgentsConfig;
  gates: GatesConfig;
  scope: 'user' | 'project';
  raw_exists: boolean;
  sources: Record<string, string>;
  error?: string;
  project?: string;
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
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
