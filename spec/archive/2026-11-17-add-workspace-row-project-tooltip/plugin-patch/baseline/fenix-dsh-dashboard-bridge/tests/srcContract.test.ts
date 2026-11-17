/**
 * Client 半单测（move-project-nav-to-workspace-rows 退役「项目」侧栏条目后重整）：
 * - iframe src 契约逐字符断言（默认/非默认前缀两组）+ 条目注册断言（固定条目
 *   集合=5、每项目 main keyed 注册契约不变、fenix-projects 不再注册）；
 * - `#panel=fenix-projects` 旧深链未注册吞语义（deepLinkPanels，window 桩驱动
 *   hashchange 路径）；
 * - apply 桩上下文零网络（对齐依赖三缺一在测试桩上整段禁用的装配契约）；
 * - 工作区行名称导航契约面（D1 锚点链 findNameTextElement node 桩替身、D2 判据
 *   四态 matchWorkspaceForProject、PROJECT_ROW_CSS 退役后形态、常量钉值）；
 * - projectSessionStarter 保留能力（行尾新会话 action 属官方 rowActions 链路）。
 */
import { describe, expect, it, vi } from 'vitest'
import {
  FIXED_ENTRIES,
  apply,
  deepLinkPanels,
  inject,
  projectIdFor,
  projectPanelSelector,
  projectRouteFor,
  projectSessionStarter,
  resolveWorkspaceIdForProject,
} from '../src/client/index.js'
import {
  buildProjectRowMap,
  matchWorkspaceForProject,
  normalizeWorkspacePath,
  parseProjectPath,
} from '../src/client/projectSync.js'
import type { ClientPluginOptions } from '../src/client/index.js'
import type { ProjectRowInfo, WorkspaceItemLike } from '../src/client/projectSync.js'
import { buildPanelSrc, resolveBridgeConfig } from '../src/shared/config.js'
import {
  PROJECT_ROW_CSS,
  WORKSPACE_NAV_OVERLAY_ATTR,
  WORKSPACE_NAV_RESCAN_DEBOUNCE_MS,
  WORKSPACE_ROW_KEY_PREFIX,
  WORKSPACE_ROW_SELECTOR,
  findNameTextElement,
  installWorkspaceNav,
  projectGroupStore,
} from '../src/client/panels.js'
import type { SyncTimer } from '../src/client/projectSync.js'

const flush = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await new Promise((resolve) => setTimeout(resolve, 0))
}

interface ElementLike {
  readonly type?: unknown
  readonly props?: { readonly children?: unknown; readonly [key: string]: unknown }
}

/** 深度收集元素树中 type 命中的 React 元素（含数组与嵌套 children）。 */
function collectByType(node: unknown, type: string, acc: ElementLike[] = []): ElementLike[] {
  if (node === null || node === undefined) return acc
  if (typeof node === 'string' || typeof node === 'number' || typeof node === 'boolean') return acc
  if (Array.isArray(node)) {
    for (const child of node) collectByType(child, type, acc)
    return acc
  }
  if (typeof node === 'object' && 'type' in node && 'props' in node) {
    const element = node as ElementLike
    if (element.type === type) acc.push(element)
    collectByType(element.props?.children, type, acc)
  }
  return acc
}

interface Registration {
  readonly slotName: string
  readonly options: Record<string, unknown>
  readonly component: unknown
}

/** 最小 slots/layout 桩：记录注册、维护 live 表、注销登记（无 uiWorkspace/
 * workspaces 服务——对齐依赖在桩上整段禁用，零网络）。 */
function stubSlotsCtx() {
  const registrations: Registration[] = []
  const removed: string[] = []
  const injectCalls: string[] = []
  const live = new Map<string, Registration>()
  const ctx = {
    slots: {
      inject(slot: string, factory: () => unknown) {
        injectCalls.push(slot)
        factory()
      },
      register(options: Record<string, unknown>, component: unknown) {
        const entry: Registration = { slotName: String(options.name), options, component }
        registrations.push(entry)
        const key = entry.slotName === 'main' ? `main:${String(options.key)}` : `list:${String(options.id)}`
        live.set(key, entry)
        return () => {
          if (live.delete(key)) removed.push(key)
        }
      },
    },
    layout: {
      selectPanel(panelId: string | null) {
        // 未注册面板抛错（对齐 dsh layout 真实行为，深链吞语义经此验证）。
        if (panelId !== null && !live.has(`main:${panelId}`)) {
          throw new Error(`layout.selectPanel: main panel "${panelId}" is not registered`)
        }
      },
    },
  }
  return { ctx, registrations, removed, injectCalls, live }
}

function fakeTimer(): SyncTimer {
  return {
    setInterval: () => Symbol('interval'),
    clear: () => {},
    onFocus: () => () => {},
  }
}

function noopFetch(): Promise<readonly string[]> {
  return Promise.resolve([])
}

/** 运行 apply 并等待启动拉取落定，返回桩上下文与 apply 停止函数。 */
async function applied(options: Omit<ClientPluginOptions, 'upstream'>) {
  const stub = stubSlotsCtx()
  const stop = apply(stub.ctx as never, { ...options, timer: fakeTimer() })
  await flush()
  return { ...stub, stop }
}

function sidebarEntries(stub: { registrations: Registration[] }, predicate?: (options: Record<string, unknown>) => boolean): Registration[] {
  return stub.registrations.filter(
    (entry) => entry.slotName === 'sidebar.panellist' && (predicate === undefined || predicate(entry.options)),
  )
}

function mainEntries(stub: { registrations: Registration[] }): Registration[] {
  return stub.registrations.filter((entry) => entry.slotName === 'main')
}

function iframeOf(component: unknown, props: Record<string, unknown> = {}): ElementLike {
  const tree = (component as (p: Record<string, unknown>) => unknown)(props)
  const iframes = collectByType(tree, 'iframe')
  if (iframes.length !== 1) throw new Error(`期望恰好一个 iframe，实际 ${iframes.length}`)
  return iframes[0] as ElementLike
}

describe('iframe src 契约（逐字符断言）', () => {
  it('默认前缀：5 固定条目深链 → src 形态逐字符一致', () => {
    expect(buildPanelSrc('/fenix-dashboard/', '#/overview')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/overview',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/command-center')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/command-center',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/settings')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/settings',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/activities')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/activities',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/help')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/help',
    )
  })

  it('非默认前缀：归一（补/去尾斜杠）后同一形态；apiBase 直拼不产生双斜杠', () => {
    expect(buildPanelSrc('/dash/', '#/projects')).toBe('/dash/?embed=1&apiBase=/dash#/projects')
    expect(buildPanelSrc('/dash', '#/projects')).toBe('/dash/?embed=1&apiBase=/dash#/projects')
    expect(buildPanelSrc('dash', '#/settings')).toBe('/dash/?embed=1&apiBase=/dash#/settings')

    // apiBase 直拼 '/api/...' 不产生双斜杠（默认与非默认前缀）。
    expect(`${resolveBridgeConfig().apiBase}/api/projects`).toBe('/fenix-dashboard/api/projects')
    expect(`${resolveBridgeConfig({ prefix: '/dash/' }).apiBase}/api/projects`).toBe('/dash/api/projects')

    // hashRoute 容错：带 # 与不带 # 等价。
    expect(buildPanelSrc('/dash/', '/projects')).toBe(buildPanelSrc('/dash/', '#/projects'))
  })

  it('每项目深链契约不变：#/projects/<name>（name 经 URI 编码）', () => {
    expect(projectRouteFor('dsh-plugins')).toBe('#/projects/dsh-plugins')
    expect(projectRouteFor('my project')).toBe('#/projects/my%20project')
    expect(projectIdFor('dsh-plugins')).toBe('fenix-project-dsh-plugins')
    expect(buildPanelSrc('/fenix-dashboard/', projectRouteFor('fenixd'))).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects/fenixd',
    )
  })

  it('注册面板组件渲染出契约 src（默认前缀，逐字符）', async () => {
    const stub = await applied({ fetchProjects: noopFetch })
    const panel = mainEntries(stub).find((entry) => entry.options.key === 'fenix-overview')
    expect(panel).toBeDefined()
    const iframe = iframeOf(panel?.component)
    expect(iframe.props?.src).toBe('/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/overview')
    stub.stop()
  })

  it('注册面板组件渲染出契约 src（非默认前缀，逐字符）', async () => {
    const stub = await applied({ prefix: '/dash/', fetchProjects: noopFetch })
    const panel = mainEntries(stub).find((entry) => entry.options.key === 'fenix-help')
    const iframe = iframeOf(panel?.component)
    expect(iframe.props?.src).toBe('/dash/?embed=1&apiBase=/dash#/help')
    stub.stop()
  })

  it('iframe 面板铺满、无边框并预留顶部 clearance', async () => {
    const stub = await applied({ fetchProjects: noopFetch })
    const panel = mainEntries(stub)[0]
    const iframe = iframeOf(panel?.component)
    const style = iframe.props?.style as Record<string, unknown>
    expect(style?.['border']).toBe('none')
    expect(style?.['width']).toBe('100%')
    expect(style?.['height']).toBe('100%')
    const container = collectByType((panel?.component as () => unknown)(), 'div')[0]
    expect(container).toBeDefined()
    expect((container?.props?.style as Record<string, unknown>)?.['paddingTop']).toBe(
      'var(--dsh-frame-leading-clearance, 0px)',
    )
    stub.stop()
  })
})

describe('条目注册（桩 slots）', () => {
  it('固定条目集合=5：id/label/order 与 specs 一致；main keyed 注册一一对应', async () => {
    const stub = await applied({ fetchProjects: noopFetch })

    expect(stub.injectCalls).toContain('sidebar.panellist')
    expect(stub.injectCalls).toContain('main')

    const fixed = sidebarEntries(stub, (options) => !String(options.id).startsWith('fenix-project-'))
    expect(fixed.map((entry) => entry.options.id)).toEqual([
      'fenix-overview',
      'fenix-command-center',
      'fenix-settings',
      'fenix-activities',
      'fenix-help',
    ])
    expect(fixed.map((entry) => entry.options.label)).toEqual(['概览', '指挥中心', '配置', '运维', '帮助'])
    // order 段位（2026-11-05 重排）：概览10 / 配置13 / 运维15 / 指挥中心16 /
    // 帮助18；「项目」条目（原 order 12）随 move-project-nav-to-workspace-rows
    // 退役。视觉序由 OFFICIAL_PANEL_REORDER 遮蔽段位（14/17）合成。
    expect(fixed.map((entry) => entry.options.order)).toEqual([10, 16, 13, 15, 18])

    const panels = mainEntries(stub)
    expect(panels.map((entry) => entry.options.key)).toEqual([
      'fenix-overview',
      'fenix-command-center',
      'fenix-settings',
      'fenix-activities',
      'fenix-help',
    ])
    // main keyed 注册 id 与侧栏条目一一对应。
    expect(panels.map((entry) => entry.options.key)).toEqual(fixed.map((entry) => entry.options.id))
    // 退役确认：fenix-projects 既不在侧栏也不在 main keyed 注册。
    expect(panels.map((entry) => entry.options.key)).not.toContain('fenix-projects')

    // 固定条目组件：全部为线性 svg 图标组件（「项目」Portal 分区组件已退役）。
    for (const entry of fixed) {
      const rendered = (entry.component as (props: Record<string, unknown>) => unknown)({ size: 16 }) as ElementLike
      expect(collectByType(rendered, 'svg'), `${String(entry.options.id)} 应为线性图标组件`).toHaveLength(1)
    }
    stub.stop()
  })

  it('FIXED_ENTRIES 常量与 stub 注册一致（条目集合=5；2026-11-05 重排段位：配置13/运维15/指挥中心16/帮助18）', () => {
    expect(FIXED_ENTRIES.map((entry) => `${entry.id}${entry.route}${entry.order}`)).toEqual([
      'fenix-overview#/overview10',
      'fenix-command-center#/command-center16',
      'fenix-settings#/settings13',
      'fenix-activities#/activities15',
      'fenix-help#/help18',
    ])
    const ids = FIXED_ENTRIES.map((entry) => entry.id)
    expect(ids).toHaveLength(5)
    expect(ids).not.toContain('fenix-projects')
    // 重排段位契约（2026-11-05 用户指令）：与 OFFICIAL_PANEL_REORDER 遮蔽改写
    // （plugins→14 / schedules→17）合成后，侧栏视觉序为 概览/配置/插件/运维/
    // 指挥中心/自动化任务/帮助——桥接自身段位与官方遮蔽段位互不重叠。
    expect(Object.fromEntries(FIXED_ENTRIES.map((entry) => [entry.id, entry.order]))).toEqual({
      'fenix-overview': 10,
      'fenix-command-center': 16,
      'fenix-settings': 13,
      'fenix-activities': 15,
      'fenix-help': 18,
    })
  })

  it('项目分组化：不平铺顶层条目；每项目 main 面板深链直达；数据源驱动名称导航', async () => {
    // 故意乱序输入，验证数据源按名称序。
    const stub = await applied({ fetchProjects: () => Promise.resolve(['fenixd', 'dsh-plugins', 'cc-import']) })

    // spec「项目收纳进官方工作区列表」：侧栏不出现平铺的项目顶层条目。
    const projects = sidebarEntries(stub, (options) => String(options.id).startsWith('fenix-project-'))
    expect(projects).toHaveLength(0)
    expect(sidebarEntries(stub)).toHaveLength(5)

    // main keyed 注册契约不变：每项目 iframe 深链直达（名称导航落点）。
    const projectPanel = mainEntries(stub).find((entry) => entry.options.key === 'fenix-project-fenixd')
    const iframe = iframeOf(projectPanel?.component)
    expect(iframe.props?.src).toBe('/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects/fenixd')
    // 名称导航数据源驱动（去重码点序）。
    expect(projectGroupStore.getSnapshot().projects).toEqual(['cc-import', 'dsh-plugins', 'fenixd'])

    // stop：项目 main 面板全部 dispose，固定条目不在 stop 范围（由 inject disposer 注销）。
    const projectPanelCount = mainEntries(stub).filter((entry) =>
      String(entry.options.key).startsWith('fenix-project-'),
    ).length
    stub.stop()
    expect(stub.removed).toHaveLength(projectPanelCount)
    for (const id of ['fenix-overview', 'fenix-settings', 'fenix-activities', 'fenix-command-center', 'fenix-help']) {
      expect(stub.removed).not.toContain(`list:${id}`)
      expect(stub.removed).not.toContain(`main:${id}`)
    }
  })

  it('apply 桩上下文零网络：对齐依赖（uiWorkspace/workspaces 服务）在桩上缺席 → fetchProjectRows 不被消费', async () => {
    // 装配契约：defaultFetchProjectRows 恒注入但依赖三缺一整段禁用——测试桩
    // 不产生任何真实 fetch 外呼（网络泄漏防线）。
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const stub = await applied({ fetchProjects: noopFetch })
    await flush()
    expect(fetchSpy).not.toHaveBeenCalled()
    stub.stop()
    fetchSpy.mockRestore()
  })

  it('空列表/上游停机：不注册项目 main 面板、数据源清空，无未处理异常', async () => {
    projectGroupStore.reset()
    const empty = await applied({ fetchProjects: () => Promise.resolve([]) })
    expect(mainEntries(empty).filter((entry) => String(entry.options.key).startsWith('fenix-project-'))).toHaveLength(0)
    expect(projectGroupStore.getSnapshot().projects).toEqual([])
    empty.stop()

    const failed = await applied({ fetchProjects: () => Promise.reject(new Error('upstream down')) })
    await flush()
    expect(mainEntries(failed).filter((entry) => String(entry.options.key).startsWith('fenix-project-'))).toHaveLength(0)
    failed.stop()
  })
})

describe('deepLinkPanels：#panel=fenix-projects 旧深链未注册吞语义', () => {
  /** 最小 window 桩：注入 globalThis.window 驱动 hashchange 读向路径，测试后摘除。 */
  function withFakeWindow<T>(hash: string, run: (listeners: Map<string, Array<() => void>>) => T): T {
    const listeners = new Map<string, Array<() => void>>()
    const win = {
      location: { hash, pathname: '/', search: '' },
      history: { replaceState: () => {} },
      addEventListener: (type: string, fn: () => void) => {
        const list = listeners.get(type) ?? []
        list.push(fn)
        listeners.set(type, list)
      },
      removeEventListener: () => {},
    }
    ;(globalThis as { window?: unknown }).window = win
    try {
      return run(listeners)
    } finally {
      delete (globalThis as { window?: unknown }).window
    }
  }

  it('hashchange 解析未注册面板 id：尝试 selectPanel 后吞错，维持当前视图，无未处理异常', () =>
    withFakeWindow('#panel=fenix-projects', (listeners) => {
      const selected: (string | null)[] = []
      const originalSelect = (id: string | null): void => {
        selected.push(id)
        if (id === 'fenix-projects') {
          throw new Error('layout.selectPanel: main panel "fenix-projects" is not registered')
        }
      }
      const ctx = { layout: { selectPanel: originalSelect } }
      const restore = deepLinkPanels(ctx as never)
      expect(() => {
        for (const fn of listeners.get('hashchange') ?? []) fn()
      }).not.toThrow()
      // 尝试发生了（深链 id 解析正确），错误被吞（维持当前视图）。
      expect(selected).toEqual(['fenix-projects'])
      // 恢复函数还原原生 selectPanel（身份可逆，双层包装防残留）。
      restore()
      expect((ctx.layout as { selectPanel: unknown }).selectPanel).toBe(originalSelect)
    }))

  it('无 hash：applyHash 空操作（不触碰 selectPanel）', () =>
    withFakeWindow('', (listeners) => {
      const selected: (string | null)[] = []
      const ctx = { layout: { selectPanel: (id: string | null) => void selected.push(id) } }
      const restore = deepLinkPanels(ctx as never)
      for (const fn of listeners.get('hashchange') ?? []) fn()
      expect(selected).toEqual([])
      restore()
    }))
})

describe('projectPanelSelector（名称点击 → layout.selectPanel 契约）', () => {
  it('调用 layout.selectPanel(projectId)（每项目 keyed 面板，契约不变）', () => {
    const selectedPanels: (string | null)[] = []
    const ctx = {
      layout: {
        selectPanel(panelId: string | null) {
          selectedPanels.push(panelId)
        },
      },
    }
    projectPanelSelector(ctx as never)('fenixd')
    expect(selectedPanels).toEqual([projectIdFor('fenixd')])
  })

  it('layout.selectPanel 抛错（面板未注册）：吞掉 warn，不抛未处理异常', () => {
    const ctx = {
      layout: {
        selectPanel() {
          throw new Error('layout.selectPanel: main panel "fenix-project-x" is not registered')
        },
      },
    }
    expect(() => projectPanelSelector(ctx as never)('x')).not.toThrow()
  })

  it('layout 服务缺失（异常环境）：静默降级，仅 warn 不抛', () => {
    expect(() => projectPanelSelector({} as never)('fenixd')).not.toThrow()
  })
})

/* ============ 工作区行名称导航（D1 锚点链 + D2 判据，node 桩替身） ============ */

describe('工作区行名称导航契约面', () => {
  const item = (workspaceId: string, path: string, title: string): WorkspaceItemLike => ({ workspaceId, path, title })

  it('常量钉值（语义锚点，非 CSS 哈希类名）', () => {
    expect(WORKSPACE_ROW_KEY_PREFIX).toBe('workspace:')
    expect(WORKSPACE_ROW_SELECTOR).toBe('[data-row-key^="workspace:"]')
    expect(WORKSPACE_NAV_OVERLAY_ATTR).toBe('data-fenix-wsnav')
    expect(WORKSPACE_NAV_RESCAN_DEBOUNCE_MS).toBe(300)
  })

  it('D2 判据①：归一化路径优先命中（分隔符/尾斜杠归一后相等）', () => {
    const items = [item('w1', '/root/fenixd/', 'fenixd'), item('w2', '/root/other', 'other')]
    expect(matchWorkspaceForProject(items, '/root/fenixd', 'fenixd')?.workspaceId).toBe('w1')
    expect(matchWorkspaceForProject(items, '/root\\fenixd', 'fenixd')?.workspaceId).toBe('w1')
  })

  it('D2 判据②：同名标题非同路径不命中（path 在场只认路径身份，标题不回落）', () => {
    // 用户自建同名标题工作区不是项目行（D2 刻意严于 resolveWorkspaceIdForProject
    // 的标题优先序——路径身份才是真项目行）。
    const items = [item('w-user', '/root/user-fenixd', 'fenixd')]
    expect(matchWorkspaceForProject(items, '/root/fenixd', 'fenixd')).toBeNull()
  })

  it('D2 判据③：title 回落——path 不可得时标题精确相等命中', () => {
    const items = [item('w1', '/root/renamed-dir', 'fenixd')]
    expect(matchWorkspaceForProject(items, null, 'fenixd')?.workspaceId).toBe('w1')
  })

  it('D2 判据④：未命中返回 null（空表/title 非精确相等）', () => {
    expect(matchWorkspaceForProject([], null, 'fenixd')).toBeNull()
    expect(matchWorkspaceForProject([item('w1', '/r/x', 'fenixd-renamed')], null, 'fenixd')).toBeNull()
  })

  it('normalizeWorkspacePath：反斜杠统一 + 去尾斜杠；不做 fs 规范化（无 realpath 承诺）', () => {
    expect(normalizeWorkspacePath('/root/fenixd')).toBe('/root/fenixd')
    expect(normalizeWorkspacePath('/root/fenixd/')).toBe('/root/fenixd')
    expect(normalizeWorkspacePath('/root\\fenixd\\')).toBe('/root/fenixd')
    expect(normalizeWorkspacePath('C:\\repo\\fenixd\\\\')).toBe('C:/repo/fenixd')
    expect(normalizeWorkspacePath('/')).toBe('')
  })

  it('buildProjectRowMap：workspaceId→项目名映射；rows 缺行走 title 兜底；项目不在列表不入 map', () => {
    const items = [
      item('w1', '/root/fenixd', 'fenixd'),
      item('w2', '/root/other-dir', 'dsh-plugins'), // title 精确相等（路径不可得时兜底命中）
    ]
    const rows: readonly ProjectRowInfo[] = [
      { name: 'fenixd', path: '/root/fenixd' },
      { name: 'dsh-plugins', path: null }, // 路径查询缺失 → title 兜底命中 w2
    ]
    const map = buildProjectRowMap(items, ['fenixd', 'dsh-plugins'], rows)
    expect(map.get('w1')).toBe('fenixd')
    expect(map.get('w2')).toBe('dsh-plugins')
    // 项目已删除（不在 projects）：其工作区行不入 map → 行失去拦截层回退原生。
    expect(buildProjectRowMap(items, ['fenixd'], rows).has('w2')).toBe(false)
  })

  it('D1 锚点链：无子元素且 trim 文本精确相等的元素命中（span.projectText > span.title 双层内层）', () => {
    const leaf = (text: string, childrenLength = 0) => ({ textContent: text, children: { length: childrenLength } })
    const row = {
      querySelectorAll: () => [
        leaf('fenixd', 1), // 外层 projectText（有子元素，跳过）
        leaf(' fenixd '), // 内层 title（trim 后精确相等，命中）
        leaf('other'),
      ],
    }
    expect(findNameTextElement(row, 'fenixd')).toEqual(leaf(' fenixd '))
  })

  it('D1 锚点缺失：名称文本不可定位返回 null（该行不装拦截层，静默降级）', () => {
    const miss = { querySelectorAll: () => [{ textContent: 'other', children: { length: 0 } }] }
    expect(findNameTextElement(miss, 'fenixd')).toBeNull()
    expect(findNameTextElement({ querySelectorAll: () => [] }, 'fenixd')).toBeNull()
    // 同文本多命中取文档序最深（最后一个无子元素命中）。
    const first = { textContent: 'fenixd', children: { length: 0 } }
    const second = { textContent: 'fenixd', children: { length: 0 } }
    const nested = { querySelectorAll: () => [first, second] }
    expect(findNameTextElement(nested, 'fenixd')).toBe(second)
  })

  it('installWorkspaceNav node 环境 no-op（无 document 不产观察器/定时器泄漏）', () => {
    expect(typeof document).toBe('undefined')
    const stop = installWorkspaceNav({} as never, { selectProject: () => {} })
    expect(() => stop()).not.toThrow()
    expect(() => stop()).not.toThrow() // 幂等
  })

  it('PROJECT_ROW_CSS 退役后形态：仅官方 regionArea 列表滚动条 5 规则（分区列表失效选择器已删）', () => {
    const rules = PROJECT_ROW_CSS.split('\n')
    expect(rules).toHaveLength(5)
    for (const rule of rules) {
      expect(rule).toContain('[class*="_regionArea"] [class*="_list"]::-webkit-scrollbar')
    }
    expect(PROJECT_ROW_CSS).toContain('width: 6px')
    expect(PROJECT_ROW_CSS).toContain('--dsh-scrollbar-thumb')
    expect(PROJECT_ROW_CSS).toContain('::-webkit-scrollbar-track { background-color: transparent; }')
    expect(PROJECT_ROW_CSS).toContain('::-webkit-scrollbar-button { display: none; }')
    // 分区面退役：testid 作用域选择器与行 hover/active 类规则不复存在。
    expect(PROJECT_ROW_CSS).not.toContain('[data-testid=')
    expect(PROJECT_ROW_CSS).not.toContain('.fenix-project-row')
  })
})

/* ============ projectSessionStarter（保留能力：行尾新会话 action 链路） ============ */

describe('projectSessionStarter 与配套解析（保留不动）', () => {
  it('resolveWorkspaceIdForProject：title 精确匹配优先，回落 path basename，未命中 null', () => {
    const items = [
      { workspaceId: 'w1', path: '/root/fenixd', title: 'fenixd' },
      { workspaceId: 'w2', path: '/root/dsh-plugins', title: 'dsh-plugins-renamed' },
    ]
    expect(resolveWorkspaceIdForProject(items, 'fenixd')).toBe('w1')
    // title 被改名过 → basename 口径兜底。
    expect(resolveWorkspaceIdForProject(items, 'dsh-plugins')).toBe('w2')
    expect(resolveWorkspaceIdForProject(items, 'missing')).toBeNull()
  })

  it('inject 声明：slots/layout/uiWorkspace/workspaces 四键', () => {
    expect(inject).toContain('slots')
    expect(inject).toContain('layout')
    expect(inject).toContain('uiWorkspace')
    expect(inject).toContain('workspaces')
  })

  it('项目无工作区：自动按项目目录建工作区后 startSession（2026-11-03 用户反馈补齐）', async () => {
    const started: string[] = []
    const created: string[] = []
    const ctx = {
      uiWorkspace: {
        workspaces: {
          list: {
            getSnapshot: () => ({
              items: [{ workspaceId: 'w-known', path: '/root/fenixd', title: 'fenixd' }],
            }),
          },
        },
        startSession: (id: string) => {
          started.push(id)
        },
      },
      workspaces: {
        create: async (input: { path: string }) => {
          created.push(input.path)
          return { workspaceId: 'w-new' }
        },
      },
    }
    const fetches: string[] = []
    const starter = projectSessionStarter(ctx as never, '/fenix-dashboard/', {
      fetchProjectPath: (name) => {
        fetches.push(name)
        return Promise.resolve(name === 'newproj' ? '/root/newproj' : null)
      },
    })
    // 已有工作区：不建、不查路径，直接 startSession。
    starter('fenixd')
    await flush()
    expect(started).toEqual(['w-known'])
    expect(created).toEqual([])
    expect(fetches).toEqual([])
    // 无工作区：查路径 → create → startSession。
    starter('newproj')
    await flush()
    expect(fetches).toEqual(['newproj'])
    expect(created).toEqual(['/root/newproj'])
    expect(started).toEqual(['w-known', 'w-new'])
    // 目录不可得（exists=false/未注册）：warn 降级，不建不启。
    started.length = 0
    starter('ghost')
    await flush()
    expect(started).toEqual([])
    expect(created).toEqual(['/root/newproj'])
  })

  it('无工作区且 workspaces 服务缺失：warn 降级不外溢', async () => {
    const ctx = {
      uiWorkspace: {
        workspaces: { list: { getSnapshot: () => ({ items: [] }) } },
        startSession: () => {},
      },
    }
    const starter = projectSessionStarter(ctx as never, '/fenix-dashboard/', {
      fetchProjectPath: () => Promise.resolve('/root/x'),
    })
    starter('orphan')
    await flush()
  })

  it('workspaces.create reject：warn 落日志不外溢', async () => {
    const ctx = {
      uiWorkspace: {
        workspaces: { list: { getSnapshot: () => ({ items: [] }) } },
        startSession: () => {},
      },
      workspaces: {
        create: async () => {
          throw new Error('workspace create failed')
        },
      },
    }
    const starter = projectSessionStarter(ctx as never, '/fenix-dashboard/', {
      fetchProjectPath: () => Promise.resolve('/root/x'),
    })
    starter('boom')
    await flush()
  })

  it('parseProjectPath：exists 行取 path；exists=false/未命中/形状异常返回 null', () => {
    const payload = {
      projects: [
        { name: 'fenixd', path: '/root/fenixd', exists: true },
        { name: 'ghost', path: '/no/such/dir', exists: false },
        { name: 'nopath', exists: true },
      ],
    }
    expect(parseProjectPath(payload, 'fenixd')).toBe('/root/fenixd')
    expect(parseProjectPath(payload, 'ghost')).toBeNull()
    expect(parseProjectPath(payload, 'nopath')).toBeNull()
    expect(parseProjectPath(payload, 'missing')).toBeNull()
    expect(parseProjectPath({ projects: 'bad' }, 'fenixd')).toBeNull()
  })
})
