// Fenix Dashboard v3 API 封装 — 复用 v1 后端（/api/*，同源直连，开发期经 umi proxy）

export type DaemonHealth = string;

export interface ProjectSummary {
  name: string;
  path: string;
  daemon: DaemonHealth;
  hosting: string;
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

/** 优雅重启项目 daemon：写 .fenix/restart_request，supervisor 排水后拉起 */
export function restartProjectDaemon(name: string) {
  return request<{ ok: boolean; error?: string }>(
    `/api/projects/${encodeURIComponent(name)}/restart`, { method: 'POST' });
}

/** 安装 supervisor 托管：停止裸 daemon → 经 supervisor 启动 */
export function installHosting(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}/install-hosting`, { method: 'POST' });
}

/** 同步用户级设置：把用户级 config.yaml 中 page 页签对应的受管键覆盖写入项目级。
 *  page 白名单：llm/agents/parallel/token/verify/approval/misc/system */
export function syncConfigFromUser(project: string, page: string): Promise<ConfigData> {
  return request<ConfigData>(`/api/config/sync-from-user?project=${encodeURIComponent(project)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page }),
  });
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
  /** add-spec-archive：是否已归档（活跃目录 spec/changes/<name>/ 不存在即 true） */
  archived?: boolean;
  priority: number | null;
  created: string | null;
  updated: string | null;
  error: string | null;
  /** add-spec-scheduling-controls D6：定时拾取时间（ISO8601 UTC 或 null，未到期前不被 daemon 拾取） */
  start_after?: string | null;
  /** add-spec-scheduling-controls D6：冻结定时解冻目标时间（ISO8601 UTC 或 null，null=永久冻结） */
  frozen_until?: string | null;
  /**
   * 冻结态（后端单点判定：结构化 frozen 字段优先，回退「用户指令冻结：」文本前缀）。
   * 自动冻结（内容完整性闸门 / 预算闸门 / env 阻塞）不带文本前缀，只认 error
   * 会漏判——前端 MUST 用该字段判定冻结，不得自行 startsWith。
   */
  frozen?: boolean;
  /** add-task-progress-verify-phase：任务进度列阶段——"verify" 仅当 status==testing，其余 "impl"（判定单点在后端） */
  progress_phase?: 'verify' | 'impl';
  /** add-task-progress-verify-phase：verify 阶段当前步骤文案（验证引擎 current，非空才渲染） */
  verify_current?: string;
  task_done: number;
  task_total: number;
  /** run 层实时进度（fix-implementer-task-progress D3）：不依赖 tasks.md 编号 */
  run_progress?: { done: number; total: number; current?: string[] } | null;
  /**
   * 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate，
   * 而派发路由实测不含该工具族 → 实现期间恒 0/N。本字段以「产物是否仍在写」
   * 提供不依赖任务工具的存活线索，前端据此在进度单元显示「进行中」。
   */
  run_activity?: { active: boolean; last_event_seconds_ago: number | null } | null;
  verify_done: number;
  verify_total: number;
  verify_error: string | null;
  /** verification-phase-progress：出题进度（testing 且执行未开始时后端统计场景文件已落盘数；其余 null） */
  generation?: { done: number; total: number } | null;
  scenario_count: number;
  total_duration: number;
  latest_run: string | null;
  latest_run_status: string | null;
  /** add-spec-review-gate D10：最近方案评审 run ID（reviewing 态必有值，评审相关 blocked 亦可回看） */
  reviewer_run?: string | null;
  /** add-spec-status-modal-budget D3：实现尝试预算已用次数（_impl_run_budget_used，缺省 0） */
  budget_used?: number;
  /** add-spec-status-modal-budget D3：per-spec 覆盖值（正整数或 null=跟随全局） */
  budget_override?: number | null;
  /** add-spec-status-modal-budget D3：有效预算（覆盖 > 全局 > 缺省，与闸门同源解析，前端不重复实现） */
  budget_effective?: number;
  /** open-impl-budget-ceiling：有效上限（agents.impl_run_budget_max，前端输入框 max 与此同源） */
  budget_max?: number;
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

// ── SPEC 人工晋升 drafted → ready（add-draft-promotion-gate D4） ──

export interface PromoteResult {
  ok: boolean;
  found: boolean;
  violations?: string[];
  reason?: string;
  error?: string;
}

/** 人工晋升 drafted SPEC（软化+lint+transition ready） */
export function promoteSpec(project: string, spec: string) {
  return request<PromoteResult>(
    `/api/spec-promote?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

// ── SPEC 重新评审（add-spec-review-gate D8） ──

export interface ReReviewResult {
  ok: boolean;
  project?: string;
  spec?: string;
  error?: string;
}

/** 重新评审 blocked SPEC（评审相关 blocked → reviewing，开放条件后端校验） */
export function reReviewSpec(project: string, spec: string) {
  return request<ReReviewResult>(
    `/api/spec-re-review?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

// ── SPEC 审批推送（add-spec-approve-push-modal） ──

export interface ApprovePushResult {
  ok: boolean;
  project?: string;
  spec?: string;
  created?: string;
  error?: string;
}

/** 审批推送 done SPEC（写文件信号，daemon 主循环拾取后执行 approve_push） */
export function approveSpecPush(project: string, spec: string) {
  return request<ApprovePushResult>(
    `/api/spec-approve-push?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

// ── SPEC 任务缺口人工回炉（fix-impl-tasks-completion-gate P1′/D8） ──

export interface TaskReflowResult {
  ok: boolean;
  spec?: string;
  status?: string;
  gap_tasks?: string[];
  reason?: string;
  error?: string;
}

/** 把 task-gap 拦截滞留 verified 的 SPEC 复位为 ready（daemon 重新派发实现者） */
export function reflowSpec(project: string, spec: string) {
  return request<TaskReflowResult>(
    `/api/spec-task-reflow?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

// ── SPEC 定时拾取 / 冻结管理（add-spec-scheduling-controls D5/D6） ──

export interface StartAfterResult {
  ok: boolean;
  project: string;
  spec: string;
  start_after: string | null;
  error?: string;
}

/** 设置/清除 SPEC 定时拾取时间（value=ISO8601 UTC 或 null 清除） */
export function setSpecStartAfter(project: string, spec: string, value: string | null) {
  return request<StartAfterResult>(
    `/api/spec-start-after?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    },
  );
}

export interface FreezeConfigResult {
  ok: boolean;
  project: string;
  spec: string;
  mode: 'permanent' | 'scheduled' | 'unfreeze';
  frozen_until: string | null;
  unfrozen?: boolean;
  error?: string;
}

/**
 * 冻结管理配置：permanent=永久冻结（清定时解冻）；
 * scheduled=设置定时解冻时间（until=ISO8601 UTC，已过去立即解冻）；
 * unfreeze=立即解冻。仅对冻结 spec 生效。
 */
export function setSpecFreezeConfig(
  project: string,
  spec: string,
  mode: 'permanent' | 'scheduled' | 'unfreeze',
  until?: string | null,
) {
  return request<FreezeConfigResult>(
    `/api/spec-freeze-config?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, until: until ?? null }),
    },
  );
}

export function archiveSpec(project: string, spec: string) {
  return request<{ ok: boolean; from: string; to: string }>(
    `/api/spec-archive?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

// ── per-spec 实现尝试预算覆盖（add-spec-status-modal-budget D3） ──

export interface SpecBudgetResult {
  ok: boolean;
  project: string;
  spec: string;
  budget: number | null;
  error?: string;
}

/** 设置/清除 SPEC 的实现尝试预算覆盖（budget=正整数写入，上限 agents.impl_run_budget_max；null 清除，恢复跟随全局） */
export function setSpecBudget(project: string, spec: string, budget: number | null) {
  return request<SpecBudgetResult>(
    `/api/spec-budget?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ budget }),
    },
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
  // add-spec-detail-duration：累计耗时（秒），与列表页耗时列同源同口径
  total_duration?: number;
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
  // verification-phase-progress：出题进度（生成阶段 verify_progress 为空态时有值）
  generation?: { done: number; total: number } | null;
  // run 层实时进度 — run_task_progress() 返回结构（不依赖 tasks.md 编号）
  run_progress?: { done: number; total: number; current?: string[] } | null;
  // 存活心跳 — run_activity() 返回结构（不依赖任务工具，产物是否仍在写）
  run_activity?: { active: boolean; last_event_seconds_ago: number | null } | null;
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
  // 时间轴 — 状态节点字段为 from/to，运行节点为 agent_type，admin 运维节点
  // 为 record_kind/severity/handled/result，验证执行节点为 total/passed 等
  // （get_spec_timeline 返回结构）
  timeline?: Array<{
    kind: 'state' | 'run' | 'admin' | 'verify';
    time: string;
    from?: string;
    to?: string;
    // 折叠状态节点：完整状态序列（首尾与 from/to 一致，中间状态不省略）
    chain?: string[];
    reason?: string;
    run_id?: string;
    agent_type?: string;
    status?: string;
    duration_seconds?: number;
    spec?: string;
    // 验证执行节点：verify_engine 报告摘要（report.json 仅引擎验证写入）
    total?: number;
    passed?: number;
    failed?: number;
    warnings?: number;
    errors?: number;
    env_error?: string;
    // 运行节点：ClaudeCode 最后一条总结（result 事件的 result 字段，兜底 assistant 文本）
    summary?: string;
    // 运行节点：实际驱动的 LLM（provider_marker 的 model@provider，failover 取最后一个）
    llm?: string;
    // 运行节点：spec 当前实现重试轮次（仅最新 run 节点携带，>0 时出现；_timeline_with_retry）
    retry_count?: number;
    retry_max?: number;
    // add-model-billing-cost-display：可计价 run 的本地计算成本（$；不可计价不渲染）
    cost_usd?: number;
    // admin 运维节点（add-timeline-admin-events）：escalation/disposition 事件
    record_kind?: 'escalation' | 'disposition';
    signal_type?: string;
    severity?: string;
    description?: string;
    handled?: boolean;
    result?: string;
  }>;
  // 场景结果 — report.json 的 scenarios 平铺数组（parse_report）
  scenarios?: Array<{
    scenario_id: string;
    description?: string;
    status: 'pass' | 'warning' | 'fail' | 'error';
    // 场景 kind（web/cli/api；multi-kind-report-compat，缺省 web）
    kind?: string;
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
      actual?: string | number | object;
      // 引擎按类型输出的字段（web: core/verify_engine/assertions.py；
      // cli/api: cli_assertions.py / api_assertions.py 口径），见 detail.tsx assertionDetail
      selector?: string;
      expected?: string | number | object;
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
      // cli
      path?: string;
      exists?: boolean;
      glob?: string;
      count?: number;
      stream?: string;
      negate?: boolean;
      actual_snippet?: string;
      // api
      header?: string;
      hit_count?: number;
      min?: number;
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
    // 降级标注（add-planready-artifact-gate D4）：框架合成报告时从
    // degrade_context.json 注入 report.json 顶层 degrade_annotation；
    // 无降级时缺省（前端不渲染）
    degrade_annotation?: {
      reason?: string;
      run_id?: string;
      duration_seconds?: number;
      cost_usd?: number | null;
      degraded_at?: string;
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
  // 被分类过滤（非 product-bug）的失败/错误场景摘要 — 后端
  // parse_filtered_failures() 返回结构（fix-verify-verdict-visibility）
  filtered_failures?: Array<{
    scenario_id: string;
    classification?: 'test-defect' | 'flaky' | 'env' | string;
    evidence_summary?: string;
    screenshots?: string[];
    status_corrected?: boolean;
    status?: 'fail' | 'failed' | 'error' | string;
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
  // add-model-billing-cost-display：SPEC 级成本合计（本地计算口径）。
  // 计费开关关闭时后端不下发该字段；computed_usd 为 null = 全部 run 不可计价
  cost_summary?: {
    computed_usd: number | null;
    priced_runs: number;
    unpriced_runs: number;
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
  // 终态事件原因：error 事件为 error，interrupted/cancelled 事件为 reason
  error?: string;
  reason?: string;
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
  // add-spec-review-gate D1：方案评审中（dedicated tone 独立于其他 info 暖色）
  reviewing: { label: '评审中', tone: 'aqua' },
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
  // improve-provider-billing-config（task 3.1）：计费配置内嵌 Provider 对象
  billing?: ProviderBilling;
}

// improve-provider-billing-config（task 3.1）：内嵌 billing 的价格行——归属于
// 所属 Provider 卡片（不再含 provider 字段），行内模型名 + 4 项单价
export interface ProviderBillingPrice {
  model: string;
  /** 每百万输入 token 费用（$/1M tokens） */
  input_per_million: number;
  /** 每百万输出 token 费用（$/1M tokens） */
  output_per_million: number;
  /** 每百万缓存命中 token 费用（$/1M tokens） */
  cache_read_per_million: number;
  /** 每百万缓存写入 token 费用（$/1M tokens） */
  cache_creation_per_million: number;
}

export interface ProviderBilling {
  /** 卡片级计费开关（缺省 false；关闭时价格区隐藏、该卡片不参与成本计算） */
  enabled?: boolean;
  prices?: ProviderBillingPrice[];
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
  /** open-impl-budget-ceiling：实现尝试预算的可配置上限（agents.impl_run_budget_max，缺省 100，硬天花板 1000） */
  impl_run_budget_max?: number;
  /** 重启重验预算（agents.verify_redo_budget，缺省 3）：daemon 重启恢复路径累计重验次数上限 */
  verify_redo_budget?: number;
  /** 瞬断治理（fix-provider-transient-backoff D6）：原地退避秒序列（逗号分隔，缺省 30,60,120） */
  transient_backoff_schedule?: string;
  /** 瞬断终态 dispatch 排程等待秒（缺省 600） */
  transient_redispatch_delay_seconds?: number;
  /** 全局同错误指纹熔断阈值（窗口内次数，缺省 3；0=关闭） */
  transient_break_threshold?: number;
  /** 熔断滑动窗口秒（缺省 600） */
  transient_break_window_seconds?: number;
  /** 熔断冷却秒（缺省 600） */
  transient_break_cooldown_seconds?: number;
}

export interface GatesConfig {
  approve_mode?: 'manual' | 'auto';
  /** 草稿晋升模式（add-draft-promotion-gate）：manual 时 drafted SPEC 停留草稿态等待人工放行（/fenix-ready / 项目页按钮 / CLI promote） */
  promote_mode?: 'manual' | 'auto';
}

export interface VerifyConfig {
  /** static 验证契约的服务范围：main=主树（方案 1，默认）| worktree=验证 worktree（方案 2） */
  static_scope?: 'main' | 'worktree';
  /** worktree node_modules 供给模式：prefer-offline=npm 缓存安装（默认）| hardlink=主树硬链接副本 */
  deps_mode?: 'prefer-offline' | 'hardlink';
  /** planner 生成节流：全框架同时在出题的 planner 数上限（0/缺省=不节流） */
  planner_max_concurrent?: number;
}

export interface SelfReviewConfig {
  /** 每日自省总开关（add-daily-self-review，缺省 false） */
  enabled?: boolean;
  /** 每晚执行时间 HH:MM（缺省 02:00） */
  run_at?: string;
  /** 是否把既有 todo.md 全文注入自省 prompt（缺省 false） */
  read_todo?: boolean;
}

// add-settings-system-tab：系统页签受管 admin.* 键（read_config 白名单 6 键）
export interface AdminConfig {
  /** 自动自愈总开关（缺省 true） */
  enabled?: boolean;
  /** 自愈监视器巡检周期（分钟，缺省 5） */
  interval_minutes?: number;
  /** 同 spec 同类困境信号的唤起冷却（分钟，缺省 15） */
  escalation_cooldown_minutes?: number;
  /** merge 熔断阈值（复用 agents.merge_breaker_threshold，缺省 2） */
  merge_breaker_threshold?: number;
  /** 计划性重启排水窗口（秒，0=快速停机，缺省 1800） */
  shutdown_drain_seconds?: number;
  /** 验证失败（bug-found）修复方式（add-bug-repair-mode-config，缺省 inplace）：
   * inplace=原地打回（缺省）；derive=派生 fix-* 子 SPEC */
  bug_repair_mode?: 'inplace' | 'derive';
  /** stuck 处置后静默期（分钟，缺省 120）：result=resolved/partially-resolved
   *  处置后同 (spec, signal_type) 在窗口内不产信号（0=不静默） */
  stuck_silence_minutes?: number;
}

// add-stale-code-selfheal：代码陈旧自愈配置节（enabled 缺省 true /
// idle_confirm_seconds 缺省 120）
export interface StaleCodeSelfhealConfig {
  /** 陈旧自愈总开关（缺省 true）：陈旧 + 配置启用 + 托管 + 连续空闲达阈值 → 触发重启 */
  enabled?: boolean;
  /** 连续空闲确认秒数（缺省 120）：陈旧状态 + 启用 + 托管 + 空闲持续达到该时长后 touch restart_request */
  idle_confirm_seconds?: number;
}

// ── 框架自进化（add-framework-self-evolution）───────────────────────

/** self_evolution 配置节（全局用户级键：auto_accept / max_items_per_run / spec_run_at） */
export interface SelfEvolutionConfig {
  /** 允许框架自改进（缺省 false）：打开后自动接受全部判定值得立项的条目 */
  auto_accept?: boolean;
  /** 每轮分析条目上限（1..200，缺省 20） */
  max_items_per_run?: number;
  /**
   * 立项后的 SPEC 执行时刻（缺省 null = 立即执行）。
   * "HH:mm" 表示「每日该时刻执行」——本地时区解释，立项时把新 SPEC 排到下一个
   * 该时刻（STATE.start_after），到点前不派发。
   */
  spec_run_at?: string | null;
}

/** 建议改进项摘要（GET /api/evolution/items 列表元素） */
export interface EvolutionItem {
  id: string;
  project: string;
  date_section: string;
  section: string;
  title: string;
  verdict?: {
    problem_exists: string;
    suggestion_sound: string;
    worth_spec: boolean;
    rationale: string;
  };
  status: string;
  has_draft: boolean;
  spec_name?: string;
  /** 文档来源：'draft'（草稿目录存在）/ 'spec'（草稿不存在但可从 SPEC 目录读回）/ null（两者皆无） */
  doc_source?: 'draft' | 'spec' | null;
  created_at: string;
  decided_at?: string;
}

/** 条目状态 → 中文文案映射（spec「状态文案映射」） */
export const EVOLUTION_STATUS_LABELS: Record<string, string> = {
  pending: '待决策',
  analyzed: '不需要立项',
  draft_failed: '草稿生成失败',
  accepted: '已同意',
  auto_accepted: '已自动接受',
  rejected: '已拒绝',
  accept_failed: '接受失败',
};

/** 草稿文档白名单（GET /api/evolution/draft 的 doc 参数） */
export const EVOLUTION_DOCS = ['proposal', 'design', 'tasks', 'spec'] as const;
export type EvolutionDoc = typeof EVOLUTION_DOCS[number];

export async function getEvolutionItems(project?: string): Promise<{ items: EvolutionItem[] }> {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<{ items: EvolutionItem[] }>(`/api/evolution/items${q}`);
}

export async function getEvolutionAnalysis(
  itemId: string,
): Promise<{ found: boolean; content: string }> {
  return request<{ found: boolean; content: string }>(
    `/api/evolution/analysis?item_id=${encodeURIComponent(itemId)}`,
  );
}

export async function getEvolutionDraft(
  itemId: string,
  doc: EvolutionDoc,
): Promise<{ found: boolean; content: string }> {
  return request<{ found: boolean; content: string }>(
    `/api/evolution/draft?item_id=${encodeURIComponent(itemId)}&doc=${encodeURIComponent(doc)}`,
  );
}

export async function acceptEvolutionItem(
  itemId: string,
  startAfter?: string | null,
): Promise<{ ok: boolean; status?: string; spec_name?: string; error?: string }> {
  // request() 直传 RequestInit 给 fetch，须以 body 字段携带 JSON 请求体
  // （与既有 POST 封装同形态，勿用 axios 风格 data 键——fetch 不识别）
  //
  // start_after：新 SPEC 的定时拾取时刻（UTC ISO）。null/缺省 = 立项后立即执行。
  // 「立即」必须显式传 null（而非省略），才能与「未指定」区分——设置页的
  // spec_run_at 可能配着定时，用户却在弹窗里选了立即。
  return request('/api/evolution/accept', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_id: itemId, start_after: startAfter ?? null }),
  });
}

export async function rejectEvolutionItem(
  itemId: string,
): Promise<{ ok: boolean; status?: string; error?: string }> {
  return request('/api/evolution/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_id: itemId }),
  });
}

export async function deleteEvolutionItem(
  itemId: string,
): Promise<{ ok: boolean; status?: string; error?: string }> {
  // 硬删：条目移出 items.jsonl 且不写墓碑，todo.md 中同名记录可能在下一轮
  // 分析 run 重新入库（UI 确认弹窗须明示）。
  return request('/api/evolution/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_id: itemId }),
  });
}

export async function clearAllEvolutionTodo(): Promise<{
  ok: boolean;
  cleared: string[];
  skipped: { project: string; reason: string }[];
  failed: { project: string; error: string }[];
}> {
  // 全局动作：清空所有项目的 .fenix/todo.md（不传项目参数）。
  // 仅清 todo.md 上游文件，不触碰 items.jsonl，故条目列表不受影响。
  return request('/api/evolution/clear-todo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

// ── SPEC 状态事件 hook 订阅（add-spec-hooks，存 .fenix/config.yaml hooks 段） ──

export type HookAction =
  | 'restart-daemon'
  | 'restart-dashboard'
  | 'commit'
  | 'push'
  | 'commit-push'
  | 'webhook'
  | 'shell';

export interface HookConfig {
  /** 短随机 id（前端生成），UI 增删改的稳定 key */
  id: string;
  enabled?: boolean;
  /** 订阅的事件类型（十状态枚举，非空） */
  events: string[];
  action: HookAction;
  /** webhook 必填：POST 目标 URL */
  url?: string;
  /** shell 必填：命令行（bash -c 执行） */
  command?: string;
  /** commit/commit-push 可选：提交信息模板（缺省 `[fenix] hook: {spec} {event}`） */
  message?: string;
  /** shell 缺省 60 / webhook 缺省 10 */
  timeout_seconds?: number;
  /** restart-dashboard 可选：目标 tmux 会话名（缺省 fenix-dashboard） */
  target?: string;
}

export interface HooksConfig {
  global?: HookConfig[];
  specs?: Record<string, HookConfig[]>;
}

export const HOOK_ACTIONS: HookAction[] = [
  'restart-daemon',
  'restart-dashboard',
  'commit',
  'push',
  'commit-push',
  'webhook',
  'shell',
];

export const HOOK_ACTION_LABELS: Record<HookAction, string> = {
  'restart-daemon': '重启 daemon',
  'restart-dashboard': '重启 dashboard',
  commit: '提交变更（commit）',
  push: '推送（push）',
  'commit-push': '提交并推送（commit-push）',
  webhook: 'Webhook 通知',
  shell: '执行 Shell 命令',
};

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
  /** add-settings-system-tab：系统配置（admin.* 受管键） */
  admin?: AdminConfig;
  /** add-spec-hooks：两级 hook 订阅配置（global + specs） */
  hooks?: HooksConfig;
  /** add-stale-code-selfheal：代码陈旧自愈（enabled / idle_confirm_seconds） */
  stale_code_selfheal?: StaleCodeSelfhealConfig;
  /** add-framework-self-evolution：自进化配置（auto_accept / max_items_per_run） */
  self_evolution?: SelfEvolutionConfig;
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

// ── 项目 todo.md（/api/todo，设置页「自省」面板查看与编辑）──

export interface TodoData {
  project: string;
  path: string;
  /** 文件尚不存在（自省未运行过）时为 false，content 为空串 */
  exists: boolean;
  content: string;
}

export async function getTodo(project: string): Promise<TodoData> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<TodoData>(`/api/todo${q}`);
}

export async function saveTodo(
  project: string,
  content: string,
): Promise<{ ok: boolean; project: string; path: string }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request(`/api/todo${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

// ── 项目 verify.yaml（/api/verify-yaml，设置页「项目简介」面板查看与编辑）──

export interface VerifyYamlData {
  project: string;
  path: string;
  /** 文件尚不存在时为 false，content 为空串 */
  exists: boolean;
  content: string;
}

export async function getVerifyYaml(project: string): Promise<VerifyYamlData> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<VerifyYamlData>(`/api/verify-yaml${q}`);
}

export async function saveVerifyYaml(
  project: string,
  content: string,
): Promise<{ ok: boolean; project: string; path: string }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request(`/api/verify-yaml${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

export async function getVerifyYamlTemplate(): Promise<{ path: string; template: string }> {
  return request(`/api/verify-yaml-template`);
}

export async function autodraftVerifyYaml(
  project: string,
  overwrite: boolean,
): Promise<{ ok: boolean; project: string; status: 'dispatched' | 'skipped'; message: string }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request(`/api/verify-yaml-autodraft${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overwrite }),
  });
}

// ── SPEC 状态事件 hook 审计（add-spec-hooks，/api/hooks/audit） ──

export interface HookAuditRecord {
  ts: string;
  spec: string;
  event: string;
  from_status?: string | null;
  to_status?: string | null;
  hook_id?: string | null;
  action: HookAction | string;
  scope: 'global' | 'spec';
  status: 'success' | 'failure' | 'noop' | 'skipped';
  detail?: string;
  duration_ms?: number;
}

export interface HookAuditData {
  project?: string | null;
  audit: HookAuditRecord[];
}

export async function getHookAudit(
  project: string,
  spec?: string,
  limit = 20,
): Promise<HookAuditData> {
  const q = new URLSearchParams();
  q.set('project', project);
  if (spec) q.set('spec', spec);
  q.set('limit', String(limit));
  return request<HookAuditData>(`/api/hooks/audit?${q.toString()}`);
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
