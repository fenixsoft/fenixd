/**
 * Client 半项目列表同步（spec「每项目动态条目」2026-10 分组化改版）：
 * 启动拉取 `<prefix>/api/projects` 驱动「项目」分组数据源与每项目 main keyed
 * 面板注册；60s 周期 + window focus 重拉；以名称集合为指纹做幂等 reconcile——
 * 新增注册面板、消失注销面板、无变化零操作；拉取失败仅保留既有状态且无未
 * 处理异常。
 *
 * 项目不再逐个注册顶层侧栏条目（spec 变更：平铺条目改为「项目」分组，2026-11
 * Portal 化为常驻内嵌分区——条目列表 nav 与工作区之间，浮层分组保留为锚点
 * 漂移时的自动降级路径，见 panels.tsx projectSectionComponent/renderProjectGroup）；
 * 分区与降级浮层共享同一数据源 projectGroupStore（setProjects 整体替换，
 * store 内去重排序、无变化零通知），同步目标 = main keyed 面板（契约不变）。
 *
 * 不订阅 dashboard SSE 拿项目表（design D6：避免常驻第二长连接 + 解析负担），
 * 60s 窗口对「侧栏多/少一个项目行」的时效足够。
 */

/** 项目列表轮询周期。 */
export const DEFAULT_POLL_INTERVAL_MS = 60_000

/** 轮询周期下界：合法但低于该值的配置按笔误钳到下界，防高频请求轰炸后端。 */
export const MIN_POLL_INTERVAL_MS = 5_000

/**
 * 规整轮询周期（仅在启动时调用一次，warn 只发一次、不随轮询刷屏）：
 * 非有限/非正数视为配置笔误，回退缺省值；合法但低于下界的钳到下界。
 */
function normalizeIntervalMs(raw: number | undefined): number {
  if (raw === undefined) return DEFAULT_POLL_INTERVAL_MS
  if (!Number.isFinite(raw) || raw <= 0) {
    console.warn(
      `[fenix-dsh-dashboard-bridge] intervalMs 配置非法（${String(raw)}），回退缺省 ${DEFAULT_POLL_INTERVAL_MS}ms`,
    )
    return DEFAULT_POLL_INTERVAL_MS
  }
  if (raw < MIN_POLL_INTERVAL_MS) {
    console.warn(
      `[fenix-dsh-dashboard-bridge] intervalMs=${String(raw)}ms 低于下界，钳制为 ${MIN_POLL_INTERVAL_MS}ms（防高频轰炸后端）`,
    )
    return MIN_POLL_INTERVAL_MS
  }
  return raw
}

/**
 * 项目条目汇：reconcile 差异（main keyed 面板注册/注销）与分组数据源
 * （setProjects 整体替换）的落点。
 */
export interface ProjectEntrySink {
  /** 项目新增（或消失后重现）：注册该项目 main keyed 面板。 */
  addProject(name: string): void
  /** 项目消失：注销该项目 main keyed 面板并清理分组残留态。 */
  removeProject(name: string): void
  /** 分组数据源整体替换（实现应去重排序、无变化零通知）。 */
  setProjects(names: readonly string[]): void
}

export type ProjectListFetcher = () => Promise<readonly string[]>

/** 名称比较（码点序，跨环境确定）。 */
export function compareNames(a: string, b: string): number {
  if (a < b) return -1
  if (a > b) return 1
  return 0
}

/**
 * 解析 `/api/projects` 应答为项目名数组：`{ projects: [{ name }] }`；
 * 非 projects 数组抛错（按拉取失败处理），空数组合法；缺失/非字符串 name
 * 的行跳过并计数 warn（行级形状漂移可观测）；projects 非空但全部行无有效
 * name 视为形状漂移（如 name 字段改名），抛错走「拉取失败保留既有状态」
 * 路径，防止把「项目全部消失」伪装成合法空列表而注销全部面板。
 */
export function parseProjectNames(payload: unknown): string[] {
  const projects = (payload as { projects?: unknown } | null | undefined)?.projects
  if (!Array.isArray(projects)) {
    throw new Error('fenix-dsh-dashboard-bridge: /api/projects 应答形状异常（projects 非数组）')
  }
  const names: string[] = []
  let skipped = 0
  for (const item of projects) {
    const name = (item as { name?: unknown } | null | undefined)?.name
    if (typeof name === 'string' && name.length > 0) names.push(name)
    else skipped += 1
  }
  if (projects.length > 0 && names.length === 0) {
    throw new Error(
      `fenix-dsh-dashboard-bridge: /api/projects 应答形状异常（${projects.length} 行均无有效 name，疑似字段漂移）`,
    )
  }
  if (skipped > 0) {
    console.warn(
      `[fenix-dsh-dashboard-bridge] /api/projects ${skipped}/${projects.length} 行缺失/非字符串 name，已跳过`,
    )
  }
  return names
}

/**
 * 解析指定项目在 `/api/projects` 应答中的目录路径（项目行「新建会话」action
 * 对无工作区项目自动建工作区用）：仅接受 `exists: true` 且 `path` 为非空
 * 字符串的行——目录不存在的注册行（exists=false）拿不到可用路径，返回 null
 * （调用方 warn 降级）。项目未注册/应答形状异常同样返回 null（与主链路的
 * 抛错口径不同：这是点击期单次查询，静默降级即可，不产生未处理异常）。
 */
export function parseProjectPath(payload: unknown, name: string): string | null {
  const projects = (payload as { projects?: unknown } | null | undefined)?.projects
  if (!Array.isArray(projects)) return null
  for (const item of projects) {
    const row = item as { name?: unknown; path?: unknown; exists?: unknown } | null | undefined
    if (row?.name !== name) continue
    if (row.exists !== true) return null
    return typeof row.path === 'string' && row.path.length > 0 ? row.path : null
  }
  return null
}

/**
 * 幂等 reconcile（main keyed 面板差异）：期望集 = 去重后的名称集合。
 * - 消失 → removeProject；
 * - 新增 → addProject；
 * - 指纹（名称集合）不变 → 零操作。
 * 返回新的已注册集合，作为下一轮 reconcile 的 current。
 */
export function reconcileProjects(
  current: ReadonlySet<string>,
  next: readonly string[],
  sink: Pick<ProjectEntrySink, 'addProject' | 'removeProject'>,
): ReadonlySet<string> {
  const desired = new Set([...new Set(next)])
  for (const name of current) {
    if (!desired.has(name)) sink.removeProject(name)
  }
  for (const name of desired) {
    if (!current.has(name)) sink.addProject(name)
  }
  return desired
}

/** 计时/焦点钩子（测试注入假定时器；node 环境无 window 时焦点订阅为 no-op）。 */
export interface SyncTimer {
  setInterval(fn: () => void, ms: number): unknown
  clear(handle: unknown): void
  onFocus(fn: () => void): () => void
}

function defaultTimer(): SyncTimer {
  return {
    setInterval(fn, ms) {
      return setInterval(fn, ms)
    },
    clear(handle) {
      clearInterval(handle as ReturnType<typeof setInterval>)
    },
    onFocus(fn) {
      if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') {
        return () => {}
      }
      window.addEventListener('focus', fn)
      return () => {
        window.removeEventListener('focus', fn)
      }
    },
  }
}

export interface ProjectSyncOptions {
  /** 拉取项目名列表（默认实现 fetch `<prefix>/api/projects` 并解析）。 */
  readonly fetchProjects: ProjectListFetcher
  /** 差异落点（main keyed 面板注册/注销 + 分组数据源）。 */
  readonly sink: ProjectEntrySink
  /** 轮询周期；缺省 60s；非有限/非正数回退缺省，低于 5s 下界的钳到 5s（均 warn 一次）。 */
  readonly intervalMs?: number
  /** 计时/焦点钩子；缺省真实 setInterval + window focus。 */
  readonly timer?: SyncTimer
}

/**
 * 启动项目列表同步循环：立即拉取一次，随后按周期 + 窗口聚焦重拉。
 * 返回停止函数：清定时器、退订焦点、丢弃在途拉取结果；再次调用安全。
 */
export function startProjectSync(options: ProjectSyncOptions): () => void {
  const intervalMs = normalizeIntervalMs(options.intervalMs)
  const timer = options.timer ?? defaultTimer()
  let current: ReadonlySet<string> = new Set()
  let stopped = false
  let inFlight = false

  const pull = async (): Promise<void> => {
    if (stopped || inFlight) return
    inFlight = true
    try {
      const names = await options.fetchProjects()
      if (!stopped) {
        current = reconcileProjects(current, names, options.sink)
        options.sink.setProjects(names)
      }
    } catch (error) {
      // 拉取失败：仅保留既有状态（面板与分组数据源原样），无未处理异常，
      // 等下一轮/聚焦重试。失败要吞但不能不可见：warn 出状态便于排障。
      console.warn(
        `[fenix-dsh-dashboard-bridge] 拉取项目列表失败（保留既有状态，等下一轮/聚焦重试）：${
          error instanceof Error ? error.message : String(error)
        }`,
      )
    } finally {
      inFlight = false
    }
  }

  const handle = timer.setInterval(() => {
    void pull()
  }, intervalMs)
  const unfocus = timer.onFocus(() => {
    void pull()
  })
  void pull()

  return () => {
    stopped = true
    timer.clear(handle)
    unfocus()
  }
}
