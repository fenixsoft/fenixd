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

/** 请求超时（毫秒）。code-review item 9985f4b5f79a：旧实现 fetch 无 signal/
    timeout，后端挂起（daemon 重启/supervisor 排水/网络黑洞）时 Promise 永不
    settle，UI 转圈无出路。统一 30s；个别长耗时端点经 request 第三参覆盖。 */
const REQUEST_TIMEOUT_MS = 30000;

/** ocr 一键安装的 per-call 超时（毫秒，code-review item bbd22d435c3e）：
    服务端 install_ocr 同步执行 `npm install -g`、预算 _INSTALL_TIMEOUT=300s，
    统一 30s 超时会让用户看到「安装失败：请求超时」而安装仍在跑（重试又得
    「安装进行中」）。给足 300s + 余量，客户端等到服务端真实结论。 */
const OCR_INSTALL_TIMEOUT_MS = 330000;

/** SSE 事件流端点（业务端点，跨视图组件复用——code-review item ba13417eb1ff：
    以共享服务层常量单源，视图不再各自硬编码字面量）。 */
export const STREAM_URL = '/api/stream';

/** API 错误：携带 HTTP 状态码与错误类别（code-review item e49991904b1f：
    旧实现把所有失败压成裸 Error，调用方无法区分网络/鉴权/业务/服务端）。 */
export class ApiError extends Error {
  status: number;
  kind: 'network' | 'timeout' | 'cancelled' | 'auth' | 'client' | 'server' | 'unknown';
  /** 后端错误体携带的稳定机器可读业务错误码（缺省 undefined；
      code-review item 934af264345f：客户端控制流按 code 分支，
      不依赖中文消息子串——措辞/locale 改动不再静默丢失定向提示）。 */
  code?: string;
  constructor(message: string, status: number, kind: ApiError['kind'], code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    if (code !== undefined) this.code = code;
  }
}

/** 后端错误体形状（code-review item e49991904b1f：此前 await res.json() 得 any）。 */
interface ApiErrorBody {
  error?: string;
  code?: string;
}

/** HTTP 状态码 → 错误类别（code-review item 8806027630b2：旧实现为 3 层
    嵌套三元链，难读且被项目审查清单禁止）。 */
function classifyHttpKind(status: number): ApiError['kind'] {
  if (status === 401 || status === 403) return 'auth';
  if (status >= 500) return 'server';
  if (status >= 400) return 'client';
  return 'unknown';
}

// ── ETag 条件请求缓存（add-dashboard-paging-and-etag 3.1）──────────────
// 模块级 Map<完整 URL（含 query）, {etag, data}>：GET 命中缓存时随请求携带
// If-None-Match，服务端数据源未变回 304（空 body）时返回缓存数据的结构化
// 拷贝——对调用方完全透明（仍拿到完整 T，且调用方原地变异不会污染缓存），
// 省掉响应体传输与 JSON 解析。仅 200 且
// 响应带 ETag 头时写缓存；304 判定先于 !res.ok（304 非 ok，误入错误分支会
// 把「数据未变」报成失败）。生命周期 = 页面会话（刷新即清），数据源变更由
// 服务端签名翻转兜底，无需手动失效；容量有上限（ETAG_CACHE_MAX，写满淘汰
// 最旧键），超长驻留会话内存占用有界。
const etagCache = new Map<string, { etag: string; data: unknown }>();
// 容量上限（code-review item 7e546940fab6）：run-tail 翻页（offset_from_end
// 递增）/跨项目跨 spec 文档浏览会持续新增缓存键（单键值含整页 run 事件的
// 完整解析体），无上限则超长驻留会话内存无界增长；写满按插入序淘汰最旧。
const ETAG_CACHE_MAX = 100;

/** 测试钩子：清空 ETag 缓存（单测隔离用；生产代码勿调用）。 */
export function _clearEtagCache(): void {
  etagCache.clear();
}

async function request<T>(
  path: string,
  init?: RequestInit,
  opts?: { timeoutMs?: number },
): Promise<T> {
  // AbortController 超时（code-review item 9985f4b5f79a）。与调用方自带
  // signal 组合：item 08d0dff8eb09——旧实现 `init?.signal ?? controller.signal`
  // 只保留一个信号，调用方传自己 signal 时内部超时定时器永不到达 fetch。
  // 改为把外部 signal 的 abort 转发给内部 controller（两信号叠加，任一
  // 触发均生效），fetch 恒用内部 signal。
  const controller = new AbortController();
  // 超时保护覆盖到 body 消费完毕（item eebe470f0864）：旧实现 finally 的
  // clearTimeout 在响应头一到达就执行，body 下方 await res.json()/res.text()
  // 期间 abort 定时器已消失——后端先发头再挂起（流式/hung handler）时
  // promise 永挂。timer 现于最外层 finally（整段读毕）才清。
  let timedOut = false;
  const timeoutMs = opts?.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const externalSignal = init?.signal;
  const forwardExternalAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort(externalSignal.reason);
    else externalSignal.addEventListener('abort', forwardExternalAbort);
  }
  // abort 分类（item 08d0dff8eb09）：只有内部定时器真正触发过才归 timeout，
  // 调用方经外部 signal 的主动取消（unmount/切页）归 cancelled，不再误标
  // 成 >30s 超时。
  const classifyAbort = () =>
    timedOut
      ? new ApiError(`请求超时（>${timeoutMs / 1000}s）`, 0, 'timeout')
      : new ApiError('请求已取消', 0, 'cancelled');
  // abort 判定放宽（item bcf32b5cce85）：`instanceof DOMException` 在非标准
  // 环境（旧 Safari、部分 fetch polyfill、SSR 下的 undici 老版本）会把 abort
  // 抛出的普通 Error 漏判成「网络请求失败」。改为名称判定（AbortError 名称
  // 跨环境稳定）+ signal.aborted 兜底（覆盖非 DOMException 形态的取消），
  // 下方三处 catch 统一走本谓词；非 abort 异常仍归 'network' 不变。
  const isAbort = (e: unknown) =>
    (e as { name?: string })?.name === 'AbortError' || controller.signal.aborted;
  // ETag 条件请求（add-dashboard-paging-and-etag 3.1）：仅无副作用的 GET 走
  // 缓存通道——缓存命中时带 If-None-Match，304 在 !res.ok 判定**之前**短路
  // 返回缓存数据（304 非 ok，落入错误分支会把「数据未变」误报失败）。
  const isGet = (init?.method ?? 'GET').toUpperCase() === 'GET';
  const cachedEntry = isGet ? etagCache.get(path) : undefined;
  const reqHeaders = new Headers(init?.headers);
  if (cachedEntry) reqHeaders.set('If-None-Match', cachedEntry.etag);
  try {
    let res: Response;
    try {
      res = await fetch(path, { ...init, headers: reqHeaders, signal: controller.signal });
    } catch (e) {
      // 网络失败 / 超时区分（e49991904b1f）
      if (isAbort(e)) throw classifyAbort();
      throw new ApiError(
        `网络请求失败：${e instanceof Error ? e.message : String(e)}`,
        0,
        'network',
      );
    }
    if (cachedEntry && res.status === 304) {
      // 304 返回结构化拷贝（code-review item e4a589e90e6c）：缓存条目是共享
      // 单例，直接返回引用会让调用方的原地变异（push/sort/改字段）写进
      // etagCache，其后该键每次 304 命中都拿到被污染数据且存活到淘汰。缓存
      // 数据恒为 JSON.parse 产物（纯 JSON 值），structuredClone 必然可克隆，
      // 且与 200 路径「每次拿全新对象」的透明度对齐。
      return structuredClone(cachedEntry.data) as T;
    }
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      let code: string | undefined;
      try {
        const body = (await res.json()) as ApiErrorBody;
        if (body?.error) msg = body.error;
        if (body?.code) code = body.code;
      } catch (e) {
        // 错误体消费期间的 abort（挂起的错误响应被超时/取消中止，item
        // eebe470f0864 同理）同样纳入分类——不得被当作「非 JSON 错误体」
        // 静默改写成 HTTP 状态码错误。
        if (isAbort(e)) throw classifyAbort();
        // 非 JSON 错误体，保留 HTTP 状态码信息
      }
      throw new ApiError(msg, res.status, classifyHttpKind(res.status), code);
    }
    // 204/205 无体响应（code-review item be91f3a413fe）：不得以 undefined 冒充
    // T——`undefined as T` 让声明泛型对空 body 撒谎，解构类型化结果的调用方
    // （const {ok} = await …）编译通过、运行时 TypeError。本文件对外恒抛
    // ApiError（item 29fcb06957b6），无体响应对「期望 JSON 体」的端点即契约
    // 违约，归 server 类显式抛出（服务端处理器经 _json/_error 恒写 JSON 体，
    // 本分支纯防御，现网行为不变）。
    if (res.status === 204 || res.status === 205) {
      throw new ApiError(`响应无 body（HTTP ${res.status}）`, res.status, 'server');
    }
    let text: string;
    try {
      text = await res.text();
    } catch (e) {
      // body 消费期间的 abort（挂起流被超时中止）同样纳入分类（item
      // eebe470f0864）——不得永挂，也不得误报为网络失败。
      if (isAbort(e)) throw classifyAbort();
      throw new ApiError(
        `读取响应失败：${e instanceof Error ? e.message : String(e)}`,
        res.status,
        'network',
      );
    }
    if (!text) {
      throw new ApiError(`响应为空 body（HTTP ${res.status}）`, res.status, 'server');
    }
    let data: T;
    try {
      data = JSON.parse(text) as T;
    } catch {
      // 契约：本文件对外恒抛 ApiError（code-review item 29fcb06957b6）——
      // 裸 Error 会让按 e.kind/e.status 分支的调用方静默落空。200 但体非法
      // JSON 属服务端异常形态，归 'server'。
      throw new ApiError(`响应不是合法 JSON（HTTP ${res.status}）`, res.status, 'server');
    }
    // 仅 200 且响应携带 ETag 头时写缓存（错误响应服务端本就不挂 ETag；
    // 无 ETag 头的 GET 保持原行为，零副作用）。
    if (isGet && res.status === 200) {
      const etag = res.headers.get('ETag');
      if (etag) {
        // 写满先淘汰最旧键（Map 保持插入序，首键即最旧）；已存在键覆盖写
        // 不增条数，跳过淘汰以免误伤。
        if (!etagCache.has(path) && etagCache.size >= ETAG_CACHE_MAX) {
          const oldest = etagCache.keys().next().value;
          if (oldest !== undefined) etagCache.delete(oldest);
        }
        etagCache.set(path, { etag, data });
      }
    }
    return data;
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener('abort', forwardExternalAbort);
  }
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

/** 同步/清空用户级设置：sync=把用户级 config.yaml 中 page 页签对应的受管键覆盖
 *  写入项目级；clear=删除项目级该页签受管键（清空后沿用用户级/默认值）。
 *  page 白名单见 core/dashboard/data/config_admin.py 的 _SYNC_PAGE_KEYS */
export function syncConfigFromUser(
  project: string,
  page: string,
  action: 'sync' | 'clear' = 'sync',
): Promise<ConfigData> {
  return request<ConfigData>(`/api/config/sync-from-user?project=${encodeURIComponent(project)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page, action }),
  });
}

export function deleteProject(name: string) {
  return request(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

// ── 运维记录（/api/admin-activities，与 v1 运维记录页同源） ──

export interface ActivityItem {
  // 后端 AdminStore._normalize_entry 对全部记录 setdefault("id", …)，运行时恒有值（activities 页 Timeline key）
  id: string;
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
  spec?: string;
  /** add-dashboard-paging-and-etag 2.1：带 page 请求时的服务端分页元数据
      （total=过滤后总条数；projects[] 仅含当前页记录，按项目分组、组内保持
      全局相对顺序）。缺省 page 请求不下发这些字段（向后兼容）。 */
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  /** ?project 不存在/未就绪时的**有意 200** 错误体（调用方按 error 分支） */
  error?: string;
}

/** 读取运维记录。page/pageSize 成对下发时走服务端分页（默认 50、上限 200，
 *  跨项目全局排序后切片）；缺省时响应结构与改造前一致。 */
export async function getAdminActivities(
  project?: string,
  spec?: string,
  page?: number,
  pageSize?: number,
): Promise<AdminActivitiesData> {
  const q = new URLSearchParams();
  if (project) q.set('project', project);
  if (spec) q.set('spec', spec);
  if (page != null && pageSize != null) {
    q.set('page', String(page));
    q.set('page_size', String(pageSize));
  }
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
  /** add-human-adjudication-choices：裁决选项集（发射点快照；无该字段=非裁决类，只出「知道了」） */
  choices?: AlertChoice[];
  /** add-adjudication-alert-narrative：三段式人类可读叙事（告警落盘时同步经一次
   * 轻量 LLM 调用生成；无该字段=开关关闭/生成失败/桶 0，渲染保持现状）。
   * 纯增强字段，不承载任何机器语义。 */
  narrative?: { text: string; model: string; at: string };
}

export interface AlertChoice {
  /** 稳定选项 id（同信号内唯一），alert-resolve 提交用 */
  id: string;
  /** 中文短标签（下拉框显示） */
  label: string;
  /** 一句话说明执行内容（下拉选项次行 / 二次确认文案） */
  desc?: string;
  /** 映射的后端动词标识（前端仅展示，不据此分派） */
  action?: string;
  /** 不可逆/越权语义标记（abandon/skip_review_gate）：前端据它决定执行前
   * 二次确认（code-review item 19f72b875e8f）；历史告警快照可能缺该字段 */
  destructive?: boolean;
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

/** add-human-adjudication-choices 5.1：人工裁决一次选择完成处置闭环。
 * 成功 = 动作执行 + 状态推进 + 告警 handled + 处置留痕一次完成；
 * 失败抛 ApiError（msg 含已执行步骤说明），告警保持未处理可重试。 */
export interface AlertResolveResult {
  ok?: boolean;
  id?: string;
  choice_id?: string;
  action?: string;
  steps?: string[];
  marked?: boolean;
  /** 后端留痕写入是否成功（留痕失败不回滚动作，后端仅 WARNING 留痕）；
   * 前端据此组织成功文案，不再假称「留痕已写入」（item 896c7e54dafd） */
  disposition_logged?: boolean;
  note?: string;
}

export async function resolveAlert(
  project: string | undefined,
  alertId: string,
  choiceId: string,
  note = '',
): Promise<AlertResolveResult> {
  // project 只走 body 通道（code-review item 7045ef4ae4c7）：POST 载荷本就
  // 内聚 project/alert_id/choice_id/note，旧的 ?project= 双通道系冗余
  //（后端 query 优先、body 兜底，两通道并存只会邀请日后失配）
  return request<AlertResolveResult>('/api/alert-resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, alert_id: alertId, choice_id: choiceId, note }),
  });
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
  /** add-task-progress-verify-phase：任务进度列阶段——"verify" 仅当 status==testing；
   * add-quality-gates-visibility 增 "gates"（implementing 收尾 / testing ocr 在飞），
   * 其余 "impl"（判定单点在后端） */
  progress_phase?: 'verify' | 'impl' | 'gates';
  /** add-task-progress-verify-phase：verify 阶段当前步骤文案（验证引擎 current，非空才渲染） */
  verify_current?: string;
  /**
   * add-quality-gates-visibility：门禁阶段（"gates"）——implementing 收尾
   * （任务全勾且门禁文件可见未了结）或 testing 且 ocr 车道在飞（判定单点在后端
   * spec_summary）。gates 阶段下任务进度列展示门禁完成度 gates_done/gates_total。
   */
  gates_done?: number;
  gates_total?: number;
  /** gates 阶段当前进展文案（running 门或 failed 归因，非空才渲染） */
  gates_current?: string;
  task_done: number;
  task_total: number;
  /** run 层实时进度（fix-implementer-task-progress D3）：不依赖 tasks.md 编号 */
  run_progress?: { done: number; total: number; current?: string[] } | null;
  /**
   * 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate，
   * 该工具族虽经 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 恢复，但实现期间 agent 未必
   * 立刻建 Task、历史 run 也可能无事件。本字段以「产物是否仍在写」
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
  /** add-spec-manual-activation D12：前置依赖（规范化后，null=无依赖，否则逗号分隔依赖名串） */
  depends_on?: string | null;
  /**
   * 取消保持态（add-cancelled-spec-resume-action D4）：SPEC 因人工取消 run 被
   * daemon 置为有意等待（_cancelled_hold: true），全部自动恢复链路对其跳过，
   * 唯一出路是「恢复运行」显式复位。后端单点归一化布尔，前端据此条件渲染。
   */
  cancelled_hold?: boolean;
}

// v1 兼容契约：未知/不存在项目返回 200 + {error, specs: []}（无 project 键，
// 有意不走 404），列表页按响应体 error 字段分支渲染
export async function getSpecs(project: string): Promise<{ project?: string; specs: SpecSummary[]; error?: string }> {
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
  // add-freeze-stop-inflight-agents 6.1：返回类型扩展——该 spec 有在跑 agent
  // 时后端异步受理返回 {accepted: true, stopping: N}（202）；无在跑 agent 时
  // 为既有同步删除结果。
  return request<{ ok: boolean; accepted?: boolean; stopping?: number; archived?: boolean; archive_path?: string | null }>(
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
  // add-freeze-stop-inflight-agents 6.1：返回类型扩展——冻结操作后端返回
  // 已停止的在跑 agent 计数（stopped_agents，0/缺省 = 无在跑 agent）。
  return request<{ ok: boolean; frozen?: boolean; stopped_agents?: number; error?: string | null }>(
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
  /** 清空定时时即时唤醒信号写出失败（fix-scheduling-kick-single-slot D3）：非空时须提示「由下次扫描派发」 */
  warning?: string;
  error?: string;
}

/** 设置/清除 SPEC 定时拾取时间（value=ISO8601 UTC / null 清除 / "manual" 设为待激活） */
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

// ── SPEC 手工激活（add-spec-manual-activation D10/D12-D11） ──

export interface ActivateResult {
  ok: boolean;
  project: string;
  spec: string;
  start_after: string | null;
  /** 即时唤醒信号写出失败（fix-scheduling-kick-single-slot D3）：非空时须提示「由下次扫描派发」 */
  warning?: string;
  reason?: string;
  error?: string;
}

/** 激活待激活 SPEC（start_after manual → null 并即时唤醒派发；非待激活返回 {ok:false, reason}） */
export function activateSpec(project: string, spec: string) {
  return request<ActivateResult>(
    `/api/spec-activate?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
  );
}

/** 恢复取消保持态 SPEC 结果（add-cancelled-spec-resume-action D4） */
export interface ResumeSpecResult {
  ok: boolean;
  project?: string;
  spec?: string;
  /** 降级标志：无可保留分支，已降级全新重派 */
  degraded?: boolean;
  /** 降级原因（degraded=true 时）或拒绝原因（ok=false 时） */
  reason?: string;
  /** 即时唤醒信号写出失败：非空时须提示「由下次扫描派发」 */
  warning?: string;
  error?: string;
}

/**
 * 恢复取消保持态 SPEC（复位 ready + 保留分支续做/降级全新重派 + 即时唤醒派发）。
 * 非取消保持态/冻结态/wm 不可用返回 {ok:false, reason}（幂等拒绝，STATE 零变更）。
 */
export function resumeSpec(project: string, spec: string) {
  return request<ResumeSpecResult>(
    `/api/spec-resume?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`,
    { method: 'POST' },
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
  // 质量门禁 — add-quality-gates-visibility：parse_quality_gates() 返回结构，
  // items 恒 6 道且顺序同后端 GATE_ORDER（前端不排序不翻译）
  quality_gates?: {
    exists: boolean;
    done: number;
    total: number;
    current?: string;
    items: Array<{
      id: string;
      desc: string;
      status: 'passed' | 'failed' | 'running' | 'pending' | 'skipped' | 'unknown';
      detail?: string;
    }>;
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
    // 状态节点回退方向单源（get_spec_timeline 按生命周期序下发）：true=回退转移；
    // 存量/归档数据可能缺失，详情页缺失时回退旧判定（带 reason 即视为回退）
    backward?: boolean;
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
    // ocr 车道 run 节点（add-timeline-ocr-lane-visibility）：审查对象摘要
    // （转录 start 事件 message：分支与 from..to 审查区间；缺失不下发不渲染）
    lane_summary?: string;
    // 最新「→ testing」状态节点（add-timeline-ocr-lane-visibility）：ocr 门
    // 当前状态（与质量门禁 Card 同源合成；非 running 前端零渲染注记）
    ocr_gate?: { status: string; detail?: string };
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
  // SDK 侧结构化事件形态（type:"system" + subtype，add-run-record-readability D1）
  subtype?: string;
  // stderr 事件原始行
  line?: string;
  // 任务生命周期/心跳事件载荷（task_started/notification、tool_progress）
  tool_use_id?: string;
  parent_tool_use_id?: string;
  elapsed_time_seconds?: number;
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

// 读取 run 尾部窗口：tail=尾部条数（默认 300），offsetFromEnd=窗口右端距流尾的
// 偏移（add-run-record-readability 4.3 向前分页；缺省 0 = 既有尾部截取语义）。
// 返回 total_events 为 run 流总事件行数（面板计数「共 M 条」）。
export async function getRunTail(
  runId: string,
  project: string,
  tail: number = 300,
  offsetFromEnd: number = 0,
): Promise<RunDetail> {
  const offsetQuery = offsetFromEnd > 0 ? `&offset_from_end=${offsetFromEnd}` : '';
  return request<RunDetail>(
    `/api/runs/${encodeURIComponent(runId)}?project=${encodeURIComponent(project)}&tail=${tail}${offsetQuery}`,
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
  /** 同因重派熔断阈值（agents.max_same_cause_redispatches，缺省 3，范围 1-100）：
   * 同一 spec 连续以同一归因（归一化指纹）判失败重派达该阈值 → 冻结转人工，不再自动重派 */
  max_same_cause_redispatches?: number;
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
  /** fast-track 派发前规模预检（agents.scale_precheck）：总开关 + 两阈值 */
  scale_precheck?: ScalePrecheckConfig;
}

/** 规模预检配置（agents.scale_precheck）：fast-track 派发前按规模分档 */
export interface ScalePrecheckConfig {
  /** 总开关：关闭后预检完全不执行（既不提高 extension 预算也不降级完整模式） */
  enabled?: boolean;
  /** higher 档阈值（严格大于才升档，缺省 30）：超过则提高 extension 上限，仍走 fast-track */
  higher_threshold?: number;
  /** full 档阈值（严格大于才降级，缺省 45）：超过则 mode 改写为 full，改走完整模式 */
  full_threshold?: number;
}

export interface GatesConfig {
  approve_mode?: 'manual' | 'auto';
  /** 草稿晋升模式（add-draft-promotion-gate）：manual 时 drafted SPEC 停留草稿态等待人工放行（/fenix-ready / 项目页按钮 / CLI promote） */
  promote_mode?: 'manual' | 'auto';
  /** 方案评审模式（add-spec-review-gate）：auto=默认全量评审，never=完全关闭 */
  spec_review_mode?: 'auto' | 'never';
  /** start_after 门控覆盖范围（add-start-after-scope-config）：dispatch（缺省）= 只约束实现派发链（旧行为），full = 同时约束晋升/评审入口 */
  start_after_scope?: 'full' | 'dispatch';
}

export interface VerifyConfig {
  /** static 验证契约的服务范围：main=主树（方案 1，默认）| worktree=验证 worktree（方案 2） */
  static_scope?: 'main' | 'worktree';
  /** worktree node_modules 供给模式：hardlink=主树硬链接副本（默认，共享 inode）| prefer-offline=npm 缓存安装 */
  deps_mode?: 'prefer-offline' | 'hardlink';
  /** planner 生成节流：全框架同时在出题的 planner 数上限（0/缺省=不节流） */
  planner_max_concurrent?: number;
  /** serving 目录自动回收（fix-verify-serving-disk-reclaim）：enabled=false 时禁用
   *  .fenix/verify-serving/ 目录与 boot.log 的生命周期清扫（缺省 true） */
  serving_reclaim?: { enabled?: boolean };
  /** 实现阶段末尾代码质量审查开关（impl-code-review-gate）：开启后实现者会在
   *  收尾阶段调用 bin/ocr_review.py（ocr）审查本次改动并自行修正真实问题；
   *  缺省 false，需环境已安装 ocr，未安装时自动跳过 */
  impl_code_review?: boolean;
  /** 收尾审查 ocr LLM 单请求超时秒（add-impl-code-review-tuning，缺省 600，
   *  正整数；写入 run 级 ocr provider 配置 custom_providers.fenix-impl.timeout_sec，
   *  确定性生效） */
  impl_code_review_timeout_sec?: number;
  /** 收尾审查 ocr 并发子任务上限（add-impl-code-review-tuning，缺省 4——
   *  add-impl-ocr-parallel-lane 由 2 上调；正整数；经提示词命令示例
   *  --concurrency <n> 承载，实现者须照抄命令示例） */
  impl_code_review_concurrency?: number;
  /** 全仓审查并发（add-code-review-concurrency-and-429-resilience，缺省 4，
   *  正整数）：控制全仓审查 run（manual_full/manual_window/scheduled）的
   *  并行审查度——提示词侧子代理扇出上限 + ocr scan --concurrency 双通道
   *  同键注入 */
  repo_code_review_concurrency?: number;
  /** 收尾审查 ocr 力度预设（add-impl-code-review-tuning，缺省 'low'；经提示词
   *  命令示例 --effort <v> 承载，实现者须照抄命令示例） */
  impl_code_review_effort?: 'low' | 'medium' | 'high';
  /** 实现分支合并后异步 ocr 车道的 join 裁决双档模式
   *  （add-impl-ocr-parallel-lane，缺省 'gate'）：gate=车道发现非 rejected
   *  findings 时打回修复轮（上限 1 轮，超限转台账）；advisory=findings 一律
   *  写 code-review 台账、join 永不打回 */
  impl_code_review_mode?: 'gate' | 'advisory';
}

export interface SelfReviewConfig {
  /** 每日自省总开关（add-daily-self-review，缺省 false） */
  enabled?: boolean;
  /** 每晚执行时间 HH:MM（缺省 02:00） */
  run_at?: string;
  /** 是否把既有 todo.md 全文注入自省 prompt（缺省 false） */
  read_todo?: boolean;
}

/** 周期性代码审查（admin.code_review；add-code-review-agent-and-quality-tab） */
export interface CodeReviewConfig {
  /** 是否启用周期性代码审查（缺省 false；手动触发不受此开关约束） */
  enabled?: boolean;
  /** 全仓审查 manifest 上限（正整数，缺省 500）：超过截断 */
  max_files?: number;
  /** 审查范围（add-code-review-scope-config）：window（缺省）| full，非法值回退 window */
  scope?: 'window' | 'full';
  /** 停滞告警阈值（分钟，正整数，缺省 15；add-code-review-sharded-out） */
  stall_alert_minutes?: number;
}

/** 自动修复代码问题（admin.code_review_fix；add-code-review-auto-fix） */
export interface CodeReviewFixConfig {
  /** 自动修复总开关（缺省 false = 全链路零动作） */
  enabled?: boolean;
  /** 每批修复的台账条目数（正整数，缺省 20，1–1000） */
  batch_size?: number;
  /** 定向回归开关（缺省 true——配置缺席或非法均视为开；读侧按 !== false
   *  归一口径，与 QualityPanel 4.3 注释一致；add-codefix-affinity-batching） */
  targeted_regression?: boolean;
}

/** 周期性全量回归（admin.regression；add-test-regression-tab） */
export interface RegressionConfig {
  /** 是否启用周期性全量回归（缺省 false；手动触发不受此开关约束） */
  enabled?: boolean;
}

// add-settings-system-tab：系统页签受管 admin.* 键（read_config 白名单，
// 键集合以后端 _managed_admin_keys 为准）
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
// idle_confirm_seconds 缺省 600，evo-reduce-stale-code-selfheal-noise）
export interface StaleCodeSelfhealConfig {
  /** 陈旧自愈总开关（缺省 true）：陈旧 + 配置启用 + 托管 + 连续空闲达阈值 → 触发重启 */
  enabled?: boolean;
  /** 连续空闲确认秒数（缺省 600）：陈旧状态 + 启用 + 托管 + 空闲持续达到该时长后 touch restart_request */
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
  return request<{ ok: boolean; status?: string; spec_name?: string; error?: string }>('/api/evolution/accept', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_id: itemId, start_after: startAfter ?? null }),
  });
}

export async function rejectEvolutionItem(
  itemId: string,
): Promise<{ ok: boolean; status?: string; error?: string }> {
  return request<{ ok: boolean; status?: string; error?: string }>('/api/evolution/reject', {
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
  return request<{ ok: boolean; status?: string; error?: string }>('/api/evolution/delete', {
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
  return request<{
    ok: boolean;
    cleared: string[];
    skipped: { project: string; reason: string }[];
    failed: { project: string; error: string }[];
  }>('/api/evolution/clear-todo', {
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
  /** add-knowledge-atlas：知识真相源总开关 + add-knowledge-atlas-maintenance：
   维护车道开关（缺省均 true；graph_enabled 已随 graphify 取消下线，不再读写） */
  knowledge?: { enabled?: boolean; audit_enabled?: boolean };
  /** add-daily-self-review：每日自省（admin.self_review 三键） */
  self_review?: SelfReviewConfig;
  /** add-settings-system-tab：系统配置（admin.* 受管键） */
  admin?: AdminConfig;
  /** add-spec-hooks：两级 hook 订阅配置（global + specs） */
  hooks?: HooksConfig;
  /** add-stale-code-selfheal：代码陈旧自愈（enabled / idle_confirm_seconds） */
  stale_code_selfheal?: StaleCodeSelfhealConfig;
  /** evo-merge-back-wip-artifact-scope / fix-artifact-paths-hardcoded-default：
   构建产物路径（项目级可编辑）+ 三态标志（has_build_artifacts：undefined=未裁决 /
   true=有产物按路径判定 / false=已声明无产物） */
  // has_build_artifacts 三态（code-review item deed1f27d507）：后端
  // worktree_config_view 恒发该键，未裁决取 None → JSON null（非 undefined），
  // 故类型含 null。
  worktree?: {
    build_artifact_paths?: string[];
    has_build_artifacts?: boolean | null;
  };
  /** add-framework-self-evolution：自进化配置（auto_accept / max_items_per_run） */
  self_evolution?: SelfEvolutionConfig;
  /** add-code-review-agent-and-quality-tab：周期性代码审查（admin.code_review 两键，
   *  设置页「质量」页签读写；项目页「代码审查」分面只读触发按钮与进度） */
  code_review?: CodeReviewConfig;
  /** add-test-regression-tab：周期性全量回归（admin.regression；设置页「质量」页签开关） */
  regression?: RegressionConfig;
  /** add-code-review-auto-fix：自动修复代码问题（admin.code_review_fix 两键，
   *  设置页「质量」页签读写；项目页「代码审查」分面呈现进度） */
  code_review_fix?: CodeReviewFixConfig;
  scope: 'user' | 'project';
  raw_exists: boolean;
  sources: Record<string, string>;
  error?: string;
  project?: string;
  description?: string;
  saved?: boolean;
  path?: string;
  /** sync-from-user action=clear 返回：实际删除的项目级键（{section: {key: 原值}}）；
   *  null = 项目级文件不存在（本来就没有覆盖） */
  cleared?: Record<string, Record<string, unknown>> | null;
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

// ── code-review（add-code-review-agent-and-quality-tab）──────────────

export interface CodeReviewItem {
  item_id: string;
  project: string;
  review_id: string;
  review_kind: string;
  reviewed_at: string;
  spec: string;
  file: string;
  line: number;
  // 含漂移值 high/medium/low（ocr scan 原样透传落台账，实测 80/543 条），
  // 与 QualityTab SEVERITY_COLOR/过滤下拉的读侧归一口径注释对齐
  severity: 'critical' | 'high' | 'major' | 'medium' | 'minor' | 'low' | 'info';
  category: string;
  title: string;
  description: string;
  suggestion: string;
  evidence: string;
  fingerprint: string;
  status: 'open' | 'in_spec' | 'resolved' | 'ignored';
  spec_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at?: string | null;
}

export interface CodeReviewProgress {
  running: boolean;
  review_id: string | null;
  review_kind: string | null;
  total: number;
  done: number;
  current: string | null;
}

/** add-code-review-agent-and-quality-tab：读取问题台账（默认仅 open，可逗号选状态）。
 *  2026-09-24：severity/page/pageSize 可选下发——表格分页 server-side，返回
 *  过滤后 total；不传 page/pageSize 时后端回退全量（旧消费者兼容）。
 *  sortBy/sortOrder 可选下发——两列排序同样 server-side（与过滤/分页同层）：
 *  分页形态下客户端 sorter 只重排当页 10 行，排序语义失真。后端白名单外值
 *  回退默认排序（severity 升序）。 */
export async function getCodeReviewItems(
  project: string,
  opts?: {
    statuses?: string[];
    severity?: string;
    page?: number;
    pageSize?: number;
    sortBy?: 'severity' | 'status';
    sortOrder?: 'asc' | 'desc';
  },
): Promise<{ items: CodeReviewItem[]; total?: number }> {
  const statusQ =
    opts?.statuses && opts.statuses.length
      ? `&status=${encodeURIComponent(opts.statuses.join(','))}`
      : '';
  const severityQ = opts?.severity ? `&severity=${encodeURIComponent(opts.severity)}` : '';
  const sortQ =
    opts?.sortBy ? `&sort_by=${opts.sortBy}&sort_order=${opts.sortOrder || 'asc'}` : '';
  const pageQ =
    opts?.page && opts?.pageSize
      ? `&page=${opts.page}&page_size=${opts.pageSize}`
      : '';
  return request<{ items: CodeReviewItem[]; total?: number }>(
    `/api/code-review/items?project=${encodeURIComponent(project)}${statusQ}${severityQ}${sortQ}${pageQ}`,
  );
}

/** add-code-review-agent-and-quality-tab：读取审查运行进度 */
export async function getCodeReviewProgress(project: string): Promise<CodeReviewProgress> {
  return request<CodeReviewProgress>(
    `/api/code-review/progress?project=${encodeURIComponent(project)}`,
  );
}

/** 自动修复进度（add-code-review-auto-fix；GET /api/code-review/fix-progress） */
export interface CodeReviewFixProgress {
  running: boolean;
  phase: 'idle' | 'selecting' | 'fixing' | 'regressing' | 'retrying' | 'merging'
    | 'blocked' | 'failed';
  total: number;
  done: number;
  current: string;
  batch_no: number;
  reason: string;
  activation_id: string;
  /** add-code-fix-item-level-progress：本批已处置条数（明细不可得时 null） */
  item_done: number | null;
  /** 最近一条处置结果摘要（明细不可得/尚未产生时 null） */
  current_item: CodeReviewFixProgressCurrentItem | null;
  /** 本批条目数（批上下文缺失时 null，条级文案分母） */
  batch_total: number | null;
  /**
   * add-code-fix-startup-stage-visibility：准备期启动阶段（读侧实时合成，
   * 批处于 fixing/retrying 且 out 零有效行时非空；不激活/不可知时 null）。
   * item_done 为 null 时本字段驱动进度卡准备段渲染。
   */
  startup_stage: CodeReviewFixProgressStartupStage | null;
}

/** add-code-fix-startup-stage-visibility：启动阶段（waited_minutes 取不到 birth time 时为 null） */
export interface CodeReviewFixProgressStartupStage {
  stage: string;
  waited_minutes: number | null;
}

/** add-code-fix-item-level-progress：最近一条处置结果摘要（title/line 由台账回查补全，降级时缺省） */
export interface CodeReviewFixProgressCurrentItem {
  item_id: string;
  /** status/file 由后端从 agent 产物行拷贝（仅校验 item_id），可合法为 null（D4 降级语义） */
  status: string | null;
  file: string | null;
  title?: string;
  line?: number;
}

/** add-code-review-auto-fix：读取自动修复进度（无副作用，缺失文件返回缺省态） */
export async function getCodeReviewFixProgress(project: string): Promise<CodeReviewFixProgress> {
  return request<CodeReviewFixProgress>(
    `/api/code-review/fix-progress?project=${encodeURIComponent(project)}`,
  );
}

/** add-code-review-agent-and-quality-tab：手动触发审查（full=全仓库 / window=本周期）。409 时抛错带后端文案 */
export function triggerCodeReview(project: string, scope: 'full' | 'window', confirm = false) {
  return request<{ ok: boolean; scope: string; requested_at: string }>(
    `/api/code-review/run?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, confirm }),
    },
  );
}

/** add-code-review-trigger-ack：审查触发受理判定结果（GET
 *  /api/code-review/run-result 透传 .fenix/code_review_request_result.json）
 *
 * wire 契约：缺省态（文件缺失/损坏）后端返回**全 null 字段对象**
 * （requested_at/status/reason/message/finished_at 均为 null，运行时真值为
 * null 而非字段缺席）。前端以 ``requested_at`` 真值且与本次触发返回的
 * ``requested_at`` 一致回链判定是否本次结果；``status`` 三值：
 * started（已投递执行）/ dropped（被守卫拒绝）/ failed（已受理但前置失败）。
 */
export interface CodeReviewRunResult {
  requested_at?: string | null;
  status?: 'started' | 'dropped' | 'failed' | null;
  reason?: string | null;
  message?: string | null;
  finished_at?: string | null;
}

/** add-code-review-trigger-ack：读取审查触发受理判定结果（无副作用，缺失返回缺省态） */
export async function getCodeReviewRunResult(project: string): Promise<CodeReviewRunResult> {
  return request<CodeReviewRunResult>(
    `/api/code-review/run-result?project=${encodeURIComponent(project)}`,
  );
}

/** 手动「自动修复」触发判定结果（add-code-fix-manual-trigger；
 *  GET /api/code-review/fix-run-result 透传 .fenix/code_fix_request_result.json）
 *
 * wire 契约：缺省态（文件缺失/损坏/未消费完）后端返回**空对象 ``{}``**——
 * 全部字段缺席（运行时 undefined），并非「全 null 字段的对象」（code-review
 * item 74c58ba954c8：类型如实声明为可选，与缺省响应形态一致）。前端以
 * ``request_created`` 真值且与本次触发返回的 ``requested_at`` 一致回链判定
 * 是否本次结果。
 */
export interface CodeFixRunResult {
  request_created?: string | null;
  triggered?: boolean;
  reason?: string;
  message?: string;
  finished_at?: string | null;
}

/** add-code-fix-manual-trigger：手动触发自动修复（写文件信号，daemon 消费）。
 *  受理返回 200 {ok, requested_at}；409（并发/残留未消费信号）抛错带后端文案。 */
export function triggerCodeFixRun(project: string) {
  // [fenix-ignore:468d69c4a34a] 问题已不存在：本封装已带空对象 body（与同族
  // triggerCodeReview/triggerRegression 同口径），Content-Type 声明名副其实。
  return request<{ ok: boolean; requested_at: string }>(
    `/api/code-review/fix-run?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

/** add-code-fix-manual-trigger：读取手动触发判定结果（无副作用，缺失返回缺省态） */
export async function getCodeFixRunResult(project: string): Promise<CodeFixRunResult> {
  return request<CodeFixRunResult>(
    `/api/code-review/fix-run-result?project=${encodeURIComponent(project)}`,
  );
}

/** add-code-review-agent-and-quality-tab：把选中条目批量生成修复 SPEC
 *
 * ``startAfter`` 三态（与设置页「同意立项」同一语义，见 ScheduleFields）：
 * 缺省/undefined = 立即执行；``"manual"`` = 待激活；UTC ISO = 定时拾取。
 * 显式传 null 亦为立即执行——后端按「缺省/null/空串 → 立即」归一。
 */
export function generateFixSpec(
  project: string,
  itemIds: string[],
  startAfter?: string | null,
) {
  return request<{
    ok: boolean;
    spec_name: string;
    skipped: Array<{ item_id: string; reason: string }>;
    error?: string;
    start_after?: string | null;
  }>(
    `/api/code-review/generate-spec?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_ids: itemIds, start_after: startAfter ?? null }),
    },
  );
}

/** add-code-review-agent-and-quality-tab：逐条人工状态流转（ignored / open 清除归属） */
export function setCodeReviewItemStatus(project: string, itemId: string, status: 'ignored' | 'open') {
  return request<{ ok: boolean; item_id: string; status: string; error?: string }>(
    `/api/code-review/items/status?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, status }),
    },
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
  return request<{ ok: boolean; agent_type: string; path: string }>(`/api/prompts${q}`, {
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
  return request<{ ok: boolean; project: string; path: string }>(`/api/todo${q}`, {
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
  return request<{ ok: boolean; project: string; path: string }>(`/api/verify-yaml${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

export async function getVerifyYamlTemplate(): Promise<{ path: string; template: string }> {
  return request(`/api/verify-yaml-template`);
}

// ── 质量页签：open-code-review 安装探测与一键安装 ──────────────────────

export interface OcrStatus {
  installed: boolean;
  bin: string | null;
  version: string | null;
}

export async function getOcrStatus(): Promise<OcrStatus> {
  return request<OcrStatus>(`/api/quality/ocr-status`);
}

export async function installOcr(): Promise<{
  ok: boolean;
  version: string | null;
  error?: string | null;
}> {
  // 补 error 字段（code-review item 52c15fcd9bc1）：后端失败路径返回
  // {ok:false, error:"…", version:null}，前端旧类型缺 error 使调用方无法透出原因。
  // per-call 超时 330s（code-review item bbd22d435c3e）：服务端同步安装预算
  // 300s，统一 30s 超时会先行中止、把仍在跑的安装误报为「请求超时」。
  return request<{ ok: boolean; version: string | null; error?: string | null }>(
    `/api/quality/ocr-install`,
    { method: 'POST' },
    { timeoutMs: OCR_INSTALL_TIMEOUT_MS },
  );
}

export async function autodraftVerifyYaml(
  project: string,
  overwrite: boolean,
): Promise<{ ok: boolean; project: string; status: 'dispatched' | 'skipped'; message: string }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<{
    ok: boolean;
    project: string;
    status: 'dispatched' | 'skipped';
    message: string;
  }>(`/api/verify-yaml-autodraft${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overwrite }),
  });
}

// ── LLM Provider 健康检测（add-provider-health-check，/api/config/llm-health-check）──

/** 健康检测结果：ok=true 时 model 回显请求的模型名；失败按四分类
    （http_error 带 status / connection_error / timeout / empty_reply）。 */
export interface LlmHealthCheckResult {
  ok: boolean;
  latency_ms: number;
  error_kind?: 'http_error' | 'connection_error' | 'timeout' | 'empty_reply' | null;
  status?: number | null;
  error?: string | null;
  model?: string | null;
}

/** LLM Provider 健康检测：daemon 代理对 {baseurl}/v1/messages 发最小消息请求
    （后端 15s 超时，默认 30s 请求超时可覆盖，无需 per-call 调整）。 */
export async function checkLlmHealth(params: {
  baseurl: string;
  apikey: string;
  model: string;
}): Promise<LlmHealthCheckResult> {
  return request<LlmHealthCheckResult>(`/api/config/llm-health-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
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

// ── 项目级自由会话（dashboard-live-session） ───────────────────────────────

// 会话事件是 claude CLI stream-json 原始事件（与 RunEvent 同构），扩展
// 会话侧字段（uuid 去重键 / session_id 归属）。
// 继承 RunEvent 使 runEventsToChatMessages(events) 可直接接收 SessionEvent[]。
export interface SessionEvent extends RunEvent {
  uuid?: string;
  session_id?: string;
  isReplay?: boolean;
  message?: unknown;
}

export interface SessionInfo {
  id: string;
  started_at: number;
}

export interface SessionState {
  session: SessionInfo | null;
  events: SessionEvent[];
  truncated?: boolean;
  error?: string;
}

export async function startSession(project: string): Promise<{ session: SessionInfo }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<{ session: SessionInfo }>(`/api/session/start${q}`, { method: 'POST' });
}

export async function getSession(project: string): Promise<SessionState> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<SessionState>(`/api/session${q}`);
}

export async function sendSessionMessage(project: string, text: string): Promise<{ ok: boolean }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<{ ok: boolean }>(`/api/session/send${q}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
}

export async function stopSession(project: string): Promise<{ ok: boolean }> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<{ ok: boolean }>(`/api/session/stop${q}`, { method: 'POST' });
}

export async function registerSessionWatch(project: string, cid: string): Promise<void> {
  const q = `?project=${encodeURIComponent(project)}&cid=${encodeURIComponent(cid)}`;
  await request(`/api/session/watch${q}`, { method: 'POST' });
}

export async function unregisterSessionWatch(project: string, cid: string): Promise<void> {
  const q = `?project=${encodeURIComponent(project)}&cid=${encodeURIComponent(cid)}`;
  await request(`/api/session/watch${q}`, { method: 'DELETE' });
}

// ── 会话补全数据源（add-session-composer 3.1） ───────────────────────────
// 两个封装均「错误吞掉返回空数组」：补全是输入辅助能力，端点失败/非 git/
// 无会话一律降级为无候选，MUST NOT 打断输入。

/** 项目文件相对路径列表（@ 提及候选；git ls-files，上限 5000）。 */
export async function fetchSessionFiles(project: string): Promise<string[]> {
  const q = `?project=${encodeURIComponent(project)}`;
  try {
    const data = await request<string[]>(`/api/session/files${q}`);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export interface SessionCommands {
  slash_commands: string[];
  skills: string[];
}

/** 斜杠命令/skill 列表（/ 补全候选；取自会话 init 事件缓存）。 */
export async function fetchSessionCommands(project: string): Promise<SessionCommands> {
  const q = `?project=${encodeURIComponent(project)}`;
  try {
    const data = await request<Partial<SessionCommands>>(`/api/session/commands${q}`);
    return {
      slash_commands: Array.isArray(data?.slash_commands) ? data.slash_commands : [],
      skills: Array.isArray(data?.skills) ? data.skills : [],
    };
  } catch {
    return { slash_commands: [], skills: [] };
  }
}

// ── 全量回归（add-test-regression-tab）────────────────────────────────

/** 单个失败/错误用例（JUnit XML 的 failure/error 子元素）。kind 区分
 *  failure（断言失败）与 error（执行错误）；time 为用例耗时（秒）。 */
export interface RegressionFailure {
  name: string;
  file: string;
  line: number;
  time: number;
  kind: 'failure' | 'error';
  message: string;
}

/** 长耗时用例（time > long_test_threshold_seconds，含通过的用例）。 */
export interface RegressionLongTest {
  name: string;
  file: string;
  line: number;
  time: number;
}

/** GET /api/regression/result 快照（design D6 结构）。
 *
 * status 五态：passed（全绿）/ failed（有失败或错误）/ timeout（硬超时中止）/
 * parse_error（XML 缺失或不可解析，附 reason）/ never_run（尚未执行过）。
 * running 为读侧补充的「是否正在执行」标记（marker 新鲜度判定），
 * 供分面在跨刷新后仍能显示运行中态（task 5.6：MUST NOT 依赖前端本地计时）。
 */
/**
 * 运行中执行进度（read_progress 三级口径）：
 * - percent 非 null + estimated=false → stdout 终端标记的真实进度
 * - percent 非 null + estimated=true  → 已耗时/上次总耗时的估算进度
 * - percent null → 进度未知（前端渲染不确定动画条）
 */
export interface RegressionProgress {
  elapsed_seconds?: number | null;
  percent?: number | null;
  estimated?: boolean;
  total_estimate?: number | null;
  last_duration_seconds?: number | null;
}

export interface RegressionResult {
  status: 'passed' | 'failed' | 'timeout' | 'parse_error' | 'never_run';
  running?: boolean;
  progress?: RegressionProgress;
  cmd?: string;
  output?: string;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  total?: number;
  passed?: number;
  failed?: number;
  errors?: number;
  skipped?: number;
  long_test_threshold_seconds?: number;
  failures?: RegressionFailure[];
  long_tests?: RegressionLongTest[];
  reason?: string;
}

/** 读取项目最近一次全量回归快照（分面 active 门控轮询）。 */
export async function getRegressionResult(project: string): Promise<RegressionResult> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<RegressionResult>(`/api/regression/result${q}`);
}

/** 手动触发一次全量回归（POST /api/regression/run）。409/400 时抛错带后端文案 */
export function triggerRegression(project: string) {
  return request<{ ok: boolean; requested_at: string }>(
    `/api/regression/run?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

/** add-regression-auto-fix：手动「自动修复回归问题」触发判定结果
 *  （GET /api/regression/fix-result 透传 .fenix/regression_fix_request_result.json）
 *
 * wire 契约：结果文件缺失/损坏时后端返回 ``{"status": "none"}`` 缺省态
 * （MUST NOT 404 报错）。前端以 ``request_created`` 真值且与本次触发返回的
 * ``requested_at`` 一致回链判定是否本次结果，陈旧残留不当作本次反馈。
 */
export interface RegressionFixRunResult {
  status?: string;
  request_created?: string | null;
  triggered?: boolean;
  reason?: string;
  message?: string;
  finished_at?: string | null;
}

/** add-regression-auto-fix：手动触发回归问题自动修复
 *  （写文件信号，daemon 消费）。受理返回 200 {ok, requested_at}；
 *  400（regression_never_run / regression_no_issues，ApiError.code 承载稳定
 *  错误码）/ 409（并发/残留未消费信号）抛错带后端文案。 */
export function fixRegression(project: string) {
  return request<{ ok: boolean; requested_at: string }>(
    `/api/regression/fix?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

/** add-regression-auto-fix：读取回归修复触发判定结果（无副作用，缺失返回缺省态） */
export async function getRegressionFixResult(
  project: string,
): Promise<RegressionFixRunResult> {
  return request<RegressionFixRunResult>(
    `/api/regression/fix-result?project=${encodeURIComponent(project)}`,
  );
}

/** 手动触发判定结果回链判读统一入口（code-review / code-fix / regression-fix
 * 三端点共用）。
 *
 * 三个「手动触发 → 轮询受理判定结果」封装（getCodeReviewRunResult /
 * getCodeFixRunResult / getRegressionFixResult）的缺省态（结果文件缺失/损坏）
 * wire 契约各不相同，回链键名亦二择：
 *   - CodeReviewRunResult：缺省态为**全 null 字段对象**（requested_at/status/
 *     reason/message/finished_at 均 null，运行时真值 null 而非缺席），回链键
 *     ``requested_at``；
 *   - CodeFixRunResult：缺省态为**空对象 {}**（全部字段缺席，运行时 undefined；
 *     引用 74c58ba954c8：类型曾按全 null 声明而实际为空对象，故如实声明可选），
 *     回链键 ``request_created``；
 *   - RegressionFixRunResult：缺省态为 ``{"status": "none"}``（MUST NOT 404），
 *     回链键 ``request_created``。
 * 三种缺省态在回链判读上运行时行为一致：回链键真值缺失/为 null，必然不匹配
 * 本次触发返回的 ``requested_at``。本函数收敛「是否本次触发结果」判读，新
 * 消费者直接调用，勿再自行区分键名与缺省形态。
 */
export function isTriggerResultForRequest(
  snap: CodeReviewRunResult | CodeFixRunResult | RegressionFixRunResult,
  wantedAt: string,
): boolean {
  // 键名二择：code-review 用 requested_at，code-fix/regression-fix 用
  // request_created（缺省态下该键为 null/缺席，恒不匹配本次触发时间）。
  // 两键均为可选字段，`in` 收窄的后置分支仍保留可选字段成员，故直接按
  // 可选键逐次取值（先 requested_at 后 request_created），不依赖收窄。
  const triggerAt: string | null | undefined =
    (snap as { requested_at?: string | null }).requested_at ??
    (snap as { request_created?: string | null }).request_created;
  return !!triggerAt && triggerAt === wantedAt;
}

/** 有效 regression 段的解析字段（GET /api/regression/config）。 */
export interface RegressionSpecView {
  /** 执行命令：str（shell）或 list（argv）；cwd 为项目根 */
  cmd: string | string[];
  /** 命令产出的 JUnit XML 路径（相对项目根） */
  output: string;
  timeout_seconds: number;
  format: string;
  long_test_threshold_seconds: number;
}

/** verify.yaml regression 段配置状态（权威判定走后端 load_verify_contract）。 */
export interface RegressionConfigStatus {
  project: string;
  /** .fenix/verify.yaml 文件是否存在 */
  exists: boolean;
  /** 契约文件存在且可解析（load_verify_contract 非 None） */
  contract_valid: boolean;
  /** 有效 regression 段字段；无段 / 整段无效 → null */
  regression: RegressionSpecView | null;
  /** 同步 AI 生成是否在途（后端单飞锁 locked()）。质量页签组件条件渲染
   *  （切页签即卸载、本地 loading state 丢失），重挂载重拉本端点据此恢复
   *  按钮 loading 态并防重复触发。 */
  autodraft_in_flight: boolean;
}

/** 读取项目 verify.yaml 的 regression 段配置状态（设置页「质量」页签）。 */
export async function getRegressionConfig(project: string): Promise<RegressionConfigStatus> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<RegressionConfigStatus>(`/api/regression/config${q}`);
}

/** regression 段 AI 同步生成的 per-call 超时（毫秒）。后端在 HTTP 线程内同步
 *  跑 headless claude 起草 + 自证（自证会按 cmd 真跑一次全量回归），预算
 *  AUTODRAFT_TIMEOUT_SECONDS=900s，客户端给足 900s + 30s 余量——参照
 *  OCR_INSTALL_TIMEOUT_MS 先例，让用户等到服务端真实结论而非 30s 假失败。 */
export const REGRESSION_AUTODRAFT_TIMEOUT_MS = 930000;

/** 同步 AI 生成 regression 段（POST /api/regression/autodraft）。
 *  success = 已落位 verify.yaml；skipped = 段已配置，无需生成；
 *  no_test_system = 项目无可用测试体系，未臆造命令。
 *  执行失败（超时/CLI 失败/自证未落位）= HTTP 200 + {ok: false, error}
 *  （describe 同款错误契约，细节走服务端日志）。 */
export async function autodraftRegression(
  project: string,
): Promise<
  | { ok: true; project: string; status: 'success' | 'skipped' | 'no_test_system'; message: string }
  | { ok: false; error: string }
> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<
    | { ok: true; project: string; status: 'success' | 'skipped' | 'no_test_system'; message: string }
    | { ok: false; error: string }
  >(
    `/api/regression/autodraft${q}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
    { timeoutMs: REGRESSION_AUTODRAFT_TIMEOUT_MS },
  );
}

// ── add-project-architecture-tab：项目架构图（archify 按需生成）──────

/** 项目架构图生成状态（GET /api/architecture/status，后端四态机）。 */
export interface ArchitectureStatus {
  project?: string;
  state: 'none' | 'generating' | 'ready' | 'failed';
  started_at?: string | null;
  generated_at?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  component_count?: number | null;
}

/** 读取项目架构图生成状态（分面 active 门控；generating 期间 3s 轮询）。 */
export async function getArchitectureStatus(
  project: string,
): Promise<ArchitectureStatus> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<ArchitectureStatus>(`/api/architecture/status${q}`);
}

/** 手动触发架构图生成（POST /api/architecture/refresh）。仅受理——生成在
 *  后台线程进行；同项目在飞时后端回 409（ApiError.status 承载，前端按
 *  状态码分支，不做中文消息子串匹配）。 */
export function refreshArchitecture(project: string) {
  return request<{ ok: boolean; state: string }>(
    `/api/architecture/refresh?project=${encodeURIComponent(project)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

/** 架构图产物下发端点 URL（iframe sandbox 加载；未生成时端点回 404
 *  结构化错误，前端仅在 state==='ready' 时渲染 iframe）。
 *  追加 present=1：archify 模板原生参数（首屏脚本读 iframe 自身
 *  location.search → data-present，渲染前生效无闪烁，与图内右上角
 *  「演示」按钮同一状态、按钮态同步为「退出演示模式」），页签内架构图
 *  默认以演示模式展示；后端忽略多余 query，仅前端语义。 */
export function architectureDiagramUrl(project: string): string {
  return `/api/architecture/diagram?project=${encodeURIComponent(project)}&present=1`;
}

// ── add-knowledge-atlas：项目知识真相源（只读视图）──────────────────

/** 域清单条目（GET /api/knowledge/index 的 domains[]）。 */
export interface KnowledgeDomain {
  name: string;
  /** 域内能力页文件名清单（不含 _domain.md）。 */
  pages: string[];
  nav_exists: boolean;
}

/** ADR 清单条目（index 响应的 adrs[]，后端解析文件头）。 */
export interface KnowledgeAdrEntry {
  file: string;
  title: string | null;
  status: string;
  superseded_by: string | null;
}

/** 项目知识总目录（GET /api/knowledge/index；未初始化 initialized=false）。 */
export interface KnowledgeIndexData {
  project?: string;
  initialized: boolean;
  index_md: string | null;
  domains: KnowledgeDomain[];
  adrs: KnowledgeAdrEntry[];
  /** 页路径剥 .md → 首 H1 标题（面包屑中文名数据源）；无 H1/读取失败为
   *  null。仅域与能力页（domains/<域>、domains/<域>/<页>）；ADR 标题经
   *  adrs[].title 另取。 */
  titles: Record<string, string | null>;
}

/** 读取项目知识总目录（分面 active 门控；未初始化为占位结构，非错误）。 */
export async function getKnowledgeIndex(project: string): Promise<KnowledgeIndexData> {
  const q = `?project=${encodeURIComponent(project)}`;
  return request<KnowledgeIndexData>(`/api/knowledge/index${q}`);
}

/** 读取真相源单文件（GET /api/knowledge/file；path 白名单 domains/ 与 adr/
 *  前缀，越界与 .. 后端恒 400）。 */
export async function getKnowledgeFile(
  project: string,
  path: string,
): Promise<{ project?: string; path: string; content: string }> {
  const q = `?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`;
  return request<{ project?: string; path: string; content: string }>(
    `/api/knowledge/file${q}`,
  );
}
