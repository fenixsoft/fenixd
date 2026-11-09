/**
 * fenix-dsh-dashboard-bridge Client 半（dsh.client, platform web）：
 * 向 `sidebar.panellist` 列表插槽注册 6 个固定菜单条目（概览/指挥中心/项目/
 * 配置/运维/帮助，order 10–18，2026-11-05 用户指令重排后段位）并以 priority -10
 * 遮蔽重排官方 Plugins/自动化任务 条目（reorderOfficialPanels，零改 dist）；在
 * layout `main` keyed 插槽以相同 id 挂对应 iframe
 * 面板（hash 深链直达）；启动时拉取 `<prefix>/api/projects`，项目不再逐个
 * 注册顶层侧栏条目，而是驱动「项目」条目（order 12）的 Portal 内嵌分区
 * （条目列表 nav 与工作区之间的常驻分区；「项目」菜单行自带整行折叠开关
 * 拦截层，点击仅切换分区展开/折叠、不切换主面板——2026-11-05 用户指令；
 * 锚点漂移自动降级浮层分组）数据源与每项目 main keyed 面板（深链
 * `#/projects/<name>` 契约不变），60s 周期 + window focus 重拉并幂等同步
 * （见 projectSync.ts）。boot 后等工作区列表就绪调 startSession() 落新会话
 * 界面（bootToNewSession，进入/刷新不再落入上次会话视图，2026-11-05 二次
 * 定调覆盖同日「落概览」先行指令）。
 *
 * 注册形态对照发行包 @deepseek-ai/dsh-client-ui-plugin-manager/lib/client.js：
 * `ctx.slots.inject(slotName, factory)` + `ctx.slots.register(options, component)`，
 * 侧栏条目组件为图标组件（props {size, active}），main 条目以 `key` 注册。
 * 程序化面板切换入口 = `ctx.layout.selectPanel(id)`（见 src/types/dsh-runtime.d.ts
 * 类型缝注释）。插件卸载时：固定条目由 inject 工厂返回的 disposer 注销；项目
 * main 面板由同步停止函数统一 dispose。
 */
import type { Context } from '@deepseek-ai/cordis'
import { buildPanelSrc, resolveBridgeConfig } from '../shared/config.js'
import type { BridgeConfigInput } from '../shared/config.js'
import { DashboardPanel, fixedIconComponent, projectSectionComponent, projectGroupStore } from './panels.js'
import type { FixedEntryId } from './panels.js'
import { DEFAULT_POLL_INTERVAL_MS, parseProjectNames, parseProjectPath, startProjectSync } from './projectSync.js'
import type { ProjectEntrySink, ProjectListFetcher, SyncTimer } from './projectSync.js'

/** 本插件消费的 client 服务键（无 RPC 需求，不引 api-remotes）。 */
export const inject = ['slots', 'layout', 'uiWorkspace', 'workspaces']

/** 6 个固定条目：id 与深链一一对应，order 10–15（位于 dsh web 既有条目之后）。 */
export interface FixedEntry {
  readonly id: FixedEntryId
  readonly label: string
  readonly route: string
  readonly order: number
}

export const FIXED_ENTRIES: readonly FixedEntry[] = [
  // order 段位（2026-11-05 用户指令重排）：概览 10 / 项目 12 / 配置 13 为桥接
  // 原段位；运维 14→15、指挥中心 11→16、帮助 15→18 为重排腾位——插件菜单
  // （官方 order 0，经下方 OFFICIAL_PANEL_REORDER 遮蔽改写为 14）落到配置之后，
  // 指挥中心(16)与自动化任务（官方 order 10，遮蔽改写为 17）落到运维之后。
  // 设置条目名「配置」（2026-11-05 用户指令）：避让 dsh web 既有「设置」官方菜单。
  { id: 'fenix-overview', label: '概览', route: '#/overview', order: 10 },
  { id: 'fenix-command-center', label: '指挥中心', route: '#/command-center', order: 16 },
  { id: 'fenix-projects', label: '项目', route: '#/projects', order: 12 },
  { id: 'fenix-settings', label: '配置', route: '#/settings', order: 13 },
  { id: 'fenix-activities', label: '运维', route: '#/activities', order: 15 },
  { id: 'fenix-help', label: '帮助', route: '#/help', order: 18 },
]

/**
 * 官方面板重排表（2026-11-05 用户指令）：sidebar.panellist 为 list 槽——cell
 * 键 = options.id，entries 按 priority 升序稳定重排后每 cell 取首个
 * （dsh-client-ui-slots entriesOfSlot 契约）——以更低 priority 重注册同 id 即
 * 遮蔽官方注册，仅改写 order 落位；label/icon 组件复用官方 entry 的引用
 * （渲染观感零变化）。零改 dist：官方注册保持原样，宿主升级不破坏本表语义
 * （官方 id 漂移时重排项自动缺席、降级为官方排位，不崩）。
 */
const OFFICIAL_PANEL_REORDER: readonly { readonly id: string; readonly order: number }[] = [
  // 插件（官方 plugin-manager 注册 order 0 排首位）→ 挪到配置(13)之后
  { id: 'plugins', order: 14 },
  // 自动化任务（官方 schedule 注册 order 10）→ 挪到指挥中心(16)之后
  { id: 'schedules', order: 17 },
]

/**
 * 官方面板遮蔽重排：订阅 panellist 变更，官方 id 在场（entriesOfSlot 胜出者）
 * 即以 priority -10 重注册同 id 改写 order，label/icon 复用官方 entry 引用；
 * 全部到位后自动退订。事件驱动零时序假设——官方注册无论先于还是晚于本插件
 * apply 都会在下一次条目变更后被捕获。id 漂移（升级改 id）时对应项静默缺席
 * （降级为官方排位），已到位项不受影响。
 *
 * @returns 退订函数（含未到位项的等待订阅；插件卸载统一收口）。
 */
export function reorderOfficialPanels(ctx: Context): () => void {
  // 形状漂移/测试桩自守：facade 缺 entriesOfSlot/subscribe（dsh 升级改名或桩
  // 上下文）时整体跳过（降级官方排位），不产生未处理异常（design Risks 条款）。
  if (typeof ctx.slots.entriesOfSlot !== 'function' || typeof ctx.slots.subscribe !== 'function') {
    return () => {}
  }
  const done = new Set<string>()
  const attempt = () => {
    let entries: ReturnType<Context['slots']['entriesOfSlot']>
    try {
      entries = ctx.slots.entriesOfSlot('sidebar.panellist')
    } catch {
      return // 插槽未声明（形状漂移）：等下一次变更再试
    }
    for (const target of OFFICIAL_PANEL_REORDER) {
      if (done.has(target.id)) continue
      const found = entries.find((entry) => entry.options.id === target.id)
      if (found === undefined) continue
      try {
        ctx.slots.register(
          {
            name: 'sidebar.panellist',
            id: target.id,
            order: target.order,
            priority: -10,
            label: found.options.label,
          },
          found.component,
        )
        done.add(target.id)
      } catch (error) {
        console.warn(
          `[fenix-dsh-dashboard-bridge] 官方面板 ${target.id} 重排注册失败：${
            error instanceof Error ? error.message : String(error)
          }`,
        )
        done.add(target.id) // 失败也不重试（同 id 同 priority 冲突等恒定错误）
      }
    }
    if (done.size >= OFFICIAL_PANEL_REORDER.length) unsubscribe()
  }
  const unsubscribe = ctx.slots.subscribe('sidebar.panellist', attempt)
  attempt() // 官方先于本插件注册时首轮即中
  return unsubscribe
}

/**
 * boot 落新会话（2026-11-05 用户指令二次定调「进入/刷新默认停留在新会话界面」，
 * 覆盖同日先行指令「落概览」）：工作区模块的 restoreSelection 在 boot 链路把
 * mainReference 重开到上次会话（持久化 `dsh.sessions.current` 恢复 +
 * recentWorkspace 兜底，两条路都绕不开），默认落点是上次会话视图。本插件
 * boot 后短轮询调 `uiWorkspace.startSession()`——原生侧栏 New Session 按钮逐键
 * 路径（新建/复用空白会话，blank 会话即新会话界面）。URL 带 `#panel=<id>` 深
 * 链时改走 selectPanel 直达该面板（深链优先于默认落点）。门禁：工作区 list
 * 相位 'ready' 后才触发（过早调用 target 解析不到会 clearMain 落「选择工作区」
 * 空态，与按钮点击观感不符）；250ms ×40 上限；node 环境（vitest 单测）无
 * window 整段跳过，不产计时器泄漏。
 */
function bootToNewSession(ctx: Context): () => void {
  if (typeof window === 'undefined') return () => {}
  let tries = 0
  const timer = setInterval(() => {
    tries += 1
    const ui = ctx.uiWorkspace
    if (ui === undefined) {
      clearInterval(timer)
      return
    }
    const phase = ui.workspaces?.list?.getSnapshot?.().phase
    if (phase !== 'ready' && tries < 40) return
    clearInterval(timer)
    if (phase !== 'ready') {
      console.warn('[fenix-dsh-dashboard-bridge] boot 落新会话失败：工作区列表未就绪')
      return
    }
    const hashPanelId = panelIdFromHash()
    if (hashPanelId !== null) {
      // 深链优先：URL 带 #panel=<id> 直达该面板，默认新会话落点让位
      try {
        ctx.layout?.selectPanel?.(hashPanelId)
      } catch {
        console.warn(`[fenix-dsh-dashboard-bridge] 深链面板 ${hashPanelId} 未注册，维持默认落点`)
      }
      return
    }
    try {
      ui.startSession()
    } catch (error) {
      console.warn(
        `[fenix-dsh-dashboard-bridge] boot 落新会话失败：${
          error instanceof Error ? error.message : String(error)
        }`,
      )
    }
  }, 250)
  return () => {
    clearInterval(timer)
  }
}

/** 项目 main 面板键：`fenix-project-<name>`（与旧顶层条目 id 一致，深链契约不变）。 */
export function projectIdFor(name: string): string {
  return `fenix-project-${name}`
}

/** 项目面板深链：`#/projects/<name>`（name 经 URI 编码）。 */
export function projectRouteFor(name: string): string {
  return `#/projects/${encodeURIComponent(name)}`
}

/** apply 的可注入选项：prefix 供测试/定制，其余注入点仅供单测桩用。 */
export interface ClientPluginOptions extends BridgeConfigInput {
  /** 项目列表拉取桩（缺省 fetch `<prefix>api/projects`）。 */
  readonly fetchProjects?: ProjectListFetcher
  /** 轮询周期（缺省 60s）。 */
  readonly intervalMs?: number
  /** 计时/焦点钩子桩（缺省真实定时器 + window focus）。 */
  readonly timer?: SyncTimer
}

/** 默认项目列表拉取超时（毫秒）：悬挂请求超时后 abort，不让同步循环永久停摆。 */
const FETCH_PROJECTS_TIMEOUT_MS = 10_000

/** 默认项目列表拉取：GET `<prefix>api/projects` → parseProjectNames（10s 超时）。 */
export function defaultFetchProjects(prefix: string): ProjectListFetcher {
  return async () => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), FETCH_PROJECTS_TIMEOUT_MS)
    try {
      const response = await fetch(`${prefix}api/projects`, {
        headers: { accept: 'application/json' },
        signal: controller.signal,
      })
      if (!response.ok) {
        throw new Error(`fenix-dsh-dashboard-bridge: 拉取项目列表失败 HTTP ${response.status}`)
      }
      return parseProjectNames(await response.json())
    } finally {
      clearTimeout(timeout)
    }
  }
}

/**
 * 项目行点击 → 激活该项目 main keyed 面板并更新分组高亮：
 * `ctx.layout.selectPanel(projectId)`（未注册面板会抛错——吞掉并 warn，不产生
 * 未处理异常）；layout 服务缺失（异常环境）时保持静默降级，仅更新高亮。
 */
export function projectPanelSelector(ctx: Context): (name: string) => void {
  return (name: string) => {
    try {
      ctx.layout?.selectPanel?.(projectIdFor(name))
      projectGroupStore.setActiveProject(name)
    } catch (error) {
      console.warn(
        `[fenix-dsh-dashboard-bridge] 切换项目面板失败：${
          error instanceof Error ? error.message : String(error)
        }`,
      )
    }
  }
}

/** 项目行「新建会话」action 的可注入依赖（测试桩用）。 */
export interface SessionStarterDeps {
  /** 项目目录路径查询桩（缺省 GET `<prefix>api/projects` 解析 exists 行）。 */
  readonly fetchProjectPath?: (name: string) => Promise<string | null>
}

/**
 * 项目行「新建会话」action：已有对应 dsh 工作区 → 原生
 * `uiWorkspace.startSession(workspaceId)`（新建/复用空白会话并把主面板切回
 * 会话视图，与工作区行 rowActions 的 + 按钮行为逐键相同）；无对应工作区 →
 * 按项目目录自动建工作区（原生 addWorkspace adoptDirectory 的
 * `workspaces.create({ path })` 同键）后同样 startSession——fenix 项目即
 * 目录，注册过 dashboard 的项目必可落成工作区。服务缺失（异常环境/测试桩）、
 * 目录不可得（exists=false）或创建失败时 console.warn 降级，不产生未处理
 * 异常。async 内核 fire-and-forget：点击回调保持同步签名。
 */
export function projectSessionStarter(
  ctx: Context,
  prefix: string,
  deps?: SessionStarterDeps,
): (name: string) => void {
  const fetchPath = deps?.fetchProjectPath ?? defaultFetchProjectPath(prefix)
  return (name: string) => {
    void startProjectSessionInner(ctx, fetchPath, name)
  }
}

/** 新建会话主流程（全量错误路径 warn 落日志，不外溢）。 */
async function startProjectSessionInner(
  ctx: Context,
  fetchPath: (name: string) => Promise<string | null>,
  name: string,
): Promise<void> {
  try {
    const ui = ctx.uiWorkspace
    if (ui === undefined) {
      console.warn('[fenix-dsh-dashboard-bridge] uiWorkspace 服务不可用，无法新建会话')
      return
    }
    const existing = resolveWorkspaceIdForProject(ui.workspaces.list.getSnapshot().items, name)
    if (existing !== null) {
      ui.startSession(existing)
      return
    }
    const workspaces = ctx.workspaces
    if (workspaces === undefined) {
      console.warn(
        `[fenix-dsh-dashboard-bridge] 项目 ${name} 无对应工作区且 workspaces 服务不可用，无法自动建工作区`,
      )
      return
    }
    const path = await fetchPath(name)
    if (path === null) {
      console.warn(`[fenix-dsh-dashboard-bridge] 项目 ${name} 无可用目录（未注册或目录不存在），无法新建会话`)
      return
    }
    const created = await workspaces.create({ path })
    ui.startSession(created.workspaceId)
  } catch (error) {
    console.warn(
      `[fenix-dsh-dashboard-bridge] 新建会话失败：${
        error instanceof Error ? error.message : String(error)
      }`,
    )
  }
}

/** 默认项目目录查询：GET `<prefix>api/projects` → parseProjectPath（10s 超时，同主链路口径）。 */
export function defaultFetchProjectPath(prefix: string): (name: string) => Promise<string | null> {
  return async (name) => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), FETCH_PROJECTS_TIMEOUT_MS)
    try {
      const response = await fetch(`${prefix}api/projects`, {
        headers: { accept: 'application/json' },
        signal: controller.signal,
      })
      if (!response.ok) {
        throw new Error(`fenix-dsh-dashboard-bridge: 拉取项目列表失败 HTTP ${response.status}`)
      }
      return parseProjectPath(await response.json(), name)
    } finally {
      clearTimeout(timeout)
    }
  }
}

/**
 * 项目名 → dsh 工作区 id 解析（纯函数，可独立单测）：title 精确匹配优先，
 * 回落 path 末段（'/' 或 '\\' 分隔的 basename）匹配——fenix 项目名即工作区
 * 目录名，两种口径覆盖 title 被用户改名过的工作区。未命中返回 null。
 */
export function resolveWorkspaceIdForProject(
  items: readonly { workspaceId: string; path: string; title: string }[],
  name: string,
): string | null {
  const basenameOf = (path: string): string => {
    const segments = path.split(/[\\/]/)
    return segments[segments.length - 1] ?? ''
  }
  const byTitle = items.find((item) => item.title === name)
  if (byTitle !== undefined) return byTitle.workspaceId
  const byBasename = items.find((item) => basenameOf(item.path) === name)
  return byBasename?.workspaceId ?? null
}

/**
 * 项目 main 面板汇：ctx.slots 上 keyed 注册/注销，支持整体清理。
 * （spec 2026-10 分组化：侧栏不再逐项目注册 panellist 条目。）
 */
export function projectEntrySink(ctx: Context, prefix: string): ProjectEntrySink & { disposeAll(): void } {
  const disposers = new Map<string, () => void>()
  return {
    addProject(name) {
      // 防御自守：重名重复 add 先注销旧注册，避免旧 disposer 被覆盖后无法注销（泄漏）。
      disposers.get(name)?.()
      const src = buildPanelSrc(prefix, projectRouteFor(name))
      const disposePanel = ctx.slots.register({ name: 'main', key: projectIdFor(name) }, () =>
        DashboardPanel({ src }),
      )
      disposers.set(name, disposePanel)
    },
    removeProject(name) {
      const dispose = disposers.get(name)
      if (dispose !== undefined) {
        dispose()
        disposers.delete(name)
      }
      // 分组残留态清理：移除的项目若正被高亮，归空。
      if (projectGroupStore.getSnapshot().activeProject === name) {
        projectGroupStore.setActiveProject(null)
      }
    },
    setProjects(names) {
      projectGroupStore.setProjects(names)
    },
    disposeAll() {
      for (const dispose of disposers.values()) dispose()
      disposers.clear()
    },
  }
}

/**
 * 面板深链 hash 解析（外层文档 URL：`#panel=<id>`）。与 iframe 内部的 dashboard
 * hash 路由（#/overview 等）互不相干——iframe 有独立 URL 命名空间。无 hash 或
 * 值为空返回 null。
 */
export function panelIdFromHash(): string | null {
  if (typeof window === 'undefined') return null
  const PANEL_HASH_PREFIX = '#panel='
  if (!window.location.hash.startsWith(PANEL_HASH_PREFIX)) return null
  const id = decodeURIComponent(window.location.hash.slice(PANEL_HASH_PREFIX.length))
  return id.length > 0 ? id : null
}

/**
 * 面板深链双向桥（2026-11-05 用户需求「菜单切换体现在 URL、可经 URL 直达」）：
 * dsh 原生面板选中无 hash 事实源（layout client 无 hashchange 监听、无面板
 * 订阅口），插件侧双向补齐、零改 dist——
 * - 写向：包装 `ctx.layout.selectPanel`（ui-sidebar 行点击即
 *   `ctx.layout.selectPanel(id)` 动态调用，包装拦全部切换源）。面板 id → 写
 *   `location.hash = 'panel=<id>'`（赋值产生历史条目：浏览器后退可在面板间回
 *   退，与 dashboard hash 路由同观感；hash 已同值时赋值无操作、无循环）；
 *   null（会话视图）→ `history.replaceState` 清 hash（保 token 查询串、不产
 *   垃圾历史条目、不触发 hashchange）。
 * - 读向：`hashchange` 监听 → 解析 `#panel=<id>` → selectPanel（未注册 id 抛
 *   错吞掉，维持当前视图）；刷新/分享链接/后退前进三类入口同路。
 * - boot：bootToNewSession 内 hash 深链优先于默认新会话落点（见其注释）。
 * 循环安全：hashchange → selectPanel → wrapper 复写同值 hash → 赋值无操作收敛。
 * 形状漂移/测试桩自守：无 window 或 layout.selectPanel 缺失时整体跳过。
 *
 * @returns 恢复函数（摘 hashchange 监听、还原原生 selectPanel）。
 */
export function deepLinkPanels(ctx: Context): () => void {
  if (typeof window === 'undefined') return () => {}
  const layout = ctx.layout
  if (typeof layout?.selectPanel !== 'function') return () => {}
  // 原属性值原样保存/还原（不用 bind 副本：还原须恢复身份可逆性，防双层包装
  // 残留——dispose/reload 语义下 bound 函数行为等价但身份漂移）
  const original: (panelId: string | null) => void = layout.selectPanel
  const applyHash = () => {
    const id = panelIdFromHash()
    if (id === null) return
    try {
      original.call(layout, id)
    } catch {
      // 未注册面板 id：忽略（维持当前视图）
    }
  }
  const wrapped = (panelId: string | null): void => {
    original.call(layout, panelId)
    try {
      if (panelId === null) {
        if (panelIdFromHash() !== null) {
          window.history.replaceState(null, '', window.location.pathname + window.location.search)
        }
        return
      }
      const want = '#panel=' + encodeURIComponent(panelId)
      if (window.location.hash !== want) window.location.hash = want
    } catch {
      // 历史操作失败不致命（隐私模式等）
    }
  }
  layout.selectPanel = wrapped
  window.addEventListener('hashchange', applyHash)
  return () => {
    window.removeEventListener('hashchange', applyHash)
    layout.selectPanel = original
  }
}

/**
 * Client 插件体：注册 6 固定条目与 main 面板，启动项目列表同步。
 * slot 形状漂移（dsh 升级改名）时注册不生效、页面不崩（design Risks）。
 *
 * @returns 停止函数：停同步循环并 dispose 全部项目 main 面板（固定条目由
 * inject 工厂 disposer 随插件卸载注销）。
 */
export function apply(ctx: Context, options?: ClientPluginOptions): () => void {
  const resolved = resolveBridgeConfig(options)
  const prefix = resolved.prefix

  // 6 固定侧栏条目（order 10–15）；「项目」条目组件为 Portal 内嵌分区 + 菜单行
  // 折叠开关（行点击仅切换展开/折叠，不切换主面板——2026-11-05 用户指令；锚点
  // 漂移自动降级浮层分组，见 panels.tsx projectSectionComponent），其余为线性图标。
  ctx.slots.inject('sidebar.panellist', () => {
    const selectProject = projectPanelSelector(ctx)
    const startProjectSession = projectSessionStarter(ctx, prefix)
    const disposers = FIXED_ENTRIES.map((entry) =>
      ctx.slots.register(
        { name: 'sidebar.panellist', id: entry.id, order: entry.order, label: entry.label },
        entry.id === 'fenix-projects'
          ? projectSectionComponent({ selectProject, startProjectSession })
          : fixedIconComponent(entry.id),
      ),
    )
    return () => {
      for (const dispose of disposers) dispose()
    }
  })

  // main keyed 插槽：与侧栏条目同 id 的 iframe 面板（深链直达）。「项目」面板
  // 保留注册：菜单行点击已被拦截层改道为折叠开关，键盘 Enter（浏览器对行按钮
  // 合成的 click 不经拦截层）仍深链 #/projects，面板缺席会抛未注册错误。
  ctx.slots.inject('main', () => {
    const disposers = FIXED_ENTRIES.map((entry) =>
      ctx.slots.register({ name: 'main', key: entry.id }, () =>
        DashboardPanel({ src: buildPanelSrc(prefix, entry.route) }),
      ),
    )
    return () => {
      for (const dispose of disposers) dispose()
    }
  })

  // 官方面板遮蔽重排 + boot 落新会话 + 面板深链双向桥（2026-11-05 用户指令，
  // 见各函数注释）。
  const stopReorder = reorderOfficialPanels(ctx)
  const stopBootSwitch = bootToNewSession(ctx)
  const stopDeepLink = deepLinkPanels(ctx)

  // 项目数据同步：main keyed 面板差异注册 + 分组数据源整体替换。
  // 60s 周期 + window focus 幂等同步。
  const sink = projectEntrySink(ctx, prefix)
  const stopSync = startProjectSync({
    fetchProjects: options?.fetchProjects ?? defaultFetchProjects(prefix),
    sink,
    intervalMs: options?.intervalMs ?? DEFAULT_POLL_INTERVAL_MS,
    timer: options?.timer,
  })

  return () => {
    stopDeepLink()
    stopBootSwitch()
    stopReorder()
    stopSync()
    sink.disposeAll()
  }
}
