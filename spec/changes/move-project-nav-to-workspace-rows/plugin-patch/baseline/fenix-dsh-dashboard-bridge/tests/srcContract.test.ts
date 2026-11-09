/**
 * Client 半单测：iframe src 契约逐字符断言（默认/非默认前缀两组）+ 条目注册
 * 断言（桩 slots 上 6 固定条目 id/label/order、项目不再平铺注册、main keyed
 * 注册一一对应、面板组件渲染出的 iframe 属性）+ 「项目」条目 Portal 化退化
 * 断言（条目组件 = Portal 分区组件）+ 降级浮层分组与 Portal 分区两条路径的
 * 纯渲染/交互契约 + 锚点/宿主/挂载状态机纯判定（node 桩替身，不依赖真实 DOM）。
 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  FIXED_ENTRIES,
  apply,
  inject,
  projectIdFor,
  projectPanelSelector,
  projectRouteFor,
  projectSessionStarter,
  resolveWorkspaceIdForProject,
} from '../src/client/index.js'
import { parseProjectPath } from '../src/client/projectSync.js'
import type { ClientPluginOptions } from '../src/client/index.js'
import { buildPanelSrc, resolveBridgeConfig } from '../src/shared/config.js'
import {
  PORTAL_DEGRADE_FAILURES,
  PROJECT_ROW_CSS,
  SECTION_ANCHOR_SELECTOR,
  SECTION_HOST_TESTID,
  SECTION_ROW_SELECTOR,
  clampSectionRowWidth,
  isAnchorReachable,
  isPortalActive,
  isWideSectionWidth,
  measureHeaderGeometry,
  mountSectionHost,
  nextPortalMountState,
  projectGroupStore,
  projectGroupHandlers,
  renderProjectAnchor,
  renderProjectGroup,
  renderProjectSection,
  sectionAnchorFrom,
  sidebarNavFrom,
} from '../src/client/panels.js'
import type { PortalMountState, ProjectGroupHandlers, SectionHostElement } from '../src/client/panels.js'
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

/** 按 data-testid 收集元素树命中的 React 元素。 */
function collectByTestId(node: unknown, testId: string, acc: ElementLike[] = []): ElementLike[] {
  if (node === null || node === undefined) return acc
  if (typeof node === 'string' || typeof node === 'number' || typeof node === 'boolean') return acc
  if (Array.isArray(node)) {
    for (const child of node) collectByTestId(child, testId, acc)
    return acc
  }
  if (typeof node === 'object' && 'type' in node && 'props' in node) {
    const element = node as ElementLike
    if (element.props?.['data-testid'] === testId) acc.push(element)
    collectByTestId(element.props?.children, testId, acc)
  }
  return acc
}

interface Registration {
  readonly slotName: string
  readonly options: Record<string, unknown>
  readonly component: unknown
}

/** 最小 slots/layout 桩：记录注册、维护 live 表、注销登记、selectPanel 调用迹。 */
function stubSlotsCtx() {
  const registrations: Registration[] = []
  const removed: string[] = []
  const injectCalls: string[] = []
  const selectedPanels: (string | null)[] = []
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
        selectedPanels.push(panelId)
      },
    },
  }
  return { ctx, registrations, removed, injectCalls, live, selectedPanels }
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
  it('默认前缀：6 固定条目深链 → src 形态与 specs Scenario 逐字符一致', () => {
    expect(buildPanelSrc('/fenix-dashboard/', '#/overview')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/overview',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/command-center')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/command-center',
    )
    expect(buildPanelSrc('/fenix-dashboard/', '#/projects')).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects',
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

  it('项目条目深链：#/projects/<name>（name 经 URI 编码）', () => {
    expect(projectRouteFor('dsh-plugins')).toBe('#/projects/dsh-plugins')
    expect(projectRouteFor('my project')).toBe('#/projects/my%20project')
    expect(projectIdFor('dsh-plugins')).toBe('fenix-project-dsh-plugins')
    expect(buildPanelSrc('/fenix-dashboard/', projectRouteFor('fenixd'))).toBe(
      '/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects/fenixd',
    )
  })

  it('注册面板组件渲染出契约 src（默认前缀，逐字符）', async () => {
    const stub = await applied({ fetchProjects: noopFetch })
    const panel = mainEntries(stub).find((entry) => entry.options.key === 'fenix-projects')
    expect(panel).toBeDefined()
    const iframe = iframeOf(panel?.component)
    expect(iframe.props?.src).toBe('/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects')
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
  it('6 固定条目 id/label/order 与 specs 一致；main keyed 注册 id 一一对应', async () => {
    const stub = await applied({ fetchProjects: noopFetch })

    expect(stub.injectCalls).toContain('sidebar.panellist')
    expect(stub.injectCalls).toContain('main')

    const fixed = sidebarEntries(stub, (options) => !String(options.id).startsWith('fenix-project-'))
    expect(fixed.map((entry) => entry.options.id)).toEqual([
      'fenix-overview',
      'fenix-command-center',
      'fenix-projects',
      'fenix-settings',
      'fenix-activities',
      'fenix-help',
    ])
    expect(fixed.map((entry) => entry.options.label)).toEqual(['概览', '指挥中心', '项目', '配置', '运维', '帮助'])
    // order 段位（2026-11-05 重排）：概览10 / 指挥中心16 / 项目12 / 配置13 /
    // 运维15 / 帮助18；视觉序由 OFFICIAL_PANEL_REORDER 遮蔽段位（14/17）合成。
    expect(fixed.map((entry) => entry.options.order)).toEqual([10, 16, 12, 13, 15, 18])

    const panels = mainEntries(stub)
    expect(panels.map((entry) => entry.options.key)).toEqual([
      'fenix-overview',
      'fenix-command-center',
      'fenix-projects',
      'fenix-settings',
      'fenix-activities',
      'fenix-help',
    ])
    // main keyed 注册 id 与侧栏条目一一对应。
    expect(panels.map((entry) => entry.options.key)).toEqual(fixed.map((entry) => entry.options.id))

    // 固定条目组件：线性 svg 图标组件 ×4 + 「项目」Portal 分区组件（hook 组件，
    // 订阅分组 store + 锚点/宿主管理；降级浮层与分区纯渲染断言分别在
    // 「项目」分组块 / 「项目」Portal 分区 describe 内经纯渲染面覆盖）。
    for (const entry of fixed) {
      const rendered = (entry.component as (props: Record<string, unknown>) => unknown)({ size: 16 }) as ElementLike
      if (entry.options.id === 'fenix-projects') {
        expect(typeof rendered.type, '「项目」条目为 Portal 分区组件（函数组件）').toBe('function')
        expect((rendered.type as { name?: string }).name, '「项目」条目组件为 Portal 分区内部组件').toBe(
          'ProjectSectionEntry',
        )
        expect(collectByType(rendered, 'svg')).toHaveLength(0)
      } else {
        expect(collectByType(rendered, 'svg'), `${String(entry.options.id)} 应为线性图标组件`).toHaveLength(1)
      }
    }
    stub.stop()
  })

  it('FIXED_ENTRIES 常量与 stub 注册一致（深链一一对应；2026-11-05 重排段位：配置13/运维15/指挥中心16/帮助18）', () => {
    expect(FIXED_ENTRIES.map((entry) => `${entry.id}${entry.route}${entry.order}`)).toEqual([
      'fenix-overview#/overview10',
      'fenix-command-center#/command-center16',
      'fenix-projects#/projects12',
      'fenix-settings#/settings13',
      'fenix-activities#/activities15',
      'fenix-help#/help18',
    ])
    // 重排段位契约（2026-11-05 用户指令）：与 OFFICIAL_PANEL_REORDER 遮蔽改写
    // （plugins→14 / schedules→17）合成后，侧栏视觉序为 概览/项目/配置/插件/
    // 运维/指挥中心/自动化任务/帮助——桥接自身段位与官方遮蔽段位互不重叠。
    const ids = FIXED_ENTRIES.map((entry) => entry.id)
    expect(ids.indexOf('fenix-settings')).toBe(ids.indexOf('fenix-projects') + 1)
    expect(ids.indexOf('fenix-activities')).toBe(ids.indexOf('fenix-settings') + 1)
  })

  it('项目分组化：不平铺顶层条目；main 面板深链直达；数据源驱动分组', async () => {
    // 故意乱序输入，验证数据源按名称序。
    const stub = await applied({ fetchProjects: () => Promise.resolve(['fenixd', 'dsh-plugins', 'cc-import']) })

    // spec「项目收纳进分组」：侧栏不出现平铺的项目顶层条目。
    const projects = sidebarEntries(stub, (options) => String(options.id).startsWith('fenix-project-'))
    expect(projects).toHaveLength(0)
    expect(sidebarEntries(stub)).toHaveLength(6)

    // main keyed 注册契约不变：每项目 iframe 深链直达。
    const projectPanel = mainEntries(stub).find((entry) => entry.options.key === 'fenix-project-fenixd')
    const iframe = iframeOf(projectPanel?.component)
    expect(iframe.props?.src).toBe('/fenix-dashboard/?embed=1&apiBase=/fenix-dashboard#/projects/fenixd')
    expect(projectGroupStore.getSnapshot().projects).toEqual(['cc-import', 'dsh-plugins', 'fenixd'])

    // stop：项目 main 面板全部 dispose，固定条目不在 stop 范围（由 inject disposer 注销）。
    const projectPanelCount = mainEntries(stub).filter((entry) =>
      String(entry.options.key).startsWith('fenix-project-'),
    ).length
    stub.stop()
    expect(stub.removed).toHaveLength(projectPanelCount)
    for (const id of ['fenix-overview', 'fenix-projects', 'fenix-settings', 'fenix-activities', 'fenix-help']) {
      expect(stub.removed).not.toContain(`list:${id}`)
      expect(stub.removed).not.toContain(`main:${id}`)
    }
  })

  it('空列表/上游停机：不注册项目 main 面板、分组数据源清空，无未处理异常', async () => {
    projectGroupStore.setActiveProject('stale')
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

describe('「项目」分组块（降级浮层路径：纯渲染 + 交互契约）', () => {
  const noopRef = { current: null }

  /** 构造仅带 stopPropagation 的伪事件（handlers 契约面只消费它）。 */
  const fakeEvent = (): Parameters<ProjectGroupHandlers['toggleHeader']>[0] => ({ stopPropagation() {} }) as never

  function groupView(overrides: Partial<Parameters<typeof renderProjectGroup>[0]> = {}) {
    return {
      projects: ['fenixd', 'dsh-plugins'],
      expanded: true,
      activeProject: null,
      wide: true,
      rowWidth: 260,
      glyphRef: noopRef,
      ...overrides,
    }
  }

  beforeEach(() => {
    projectGroupStore.reset()
  })

  it('宽态展开：项目行 = 首字母徽标 + 项目名；行可点且带 data-testid', () => {
    const tree = renderProjectGroup(groupView(), {
      toggleHeader: () => {},
      selectProject: () => {},
      startProjectSession: () => {},
    })
    const list = collectByTestId(tree, 'fenix-projects-list')
    expect(list).toHaveLength(1)
    for (const name of ['fenixd', 'dsh-plugins']) {
      const row = collectByTestId(tree, `fenix-project-row-${name}`)
      expect(row, `项目行 ${name}`).toHaveLength(1)
      // 行内含首字母圆形徽标（span borderRadius 50%）与项目名文本。
      const style = row[0] && (collectByType(row[0], 'span').map((span) => span.props?.['style']) as (Record<string, unknown> | undefined)[])
      expect(style?.some((item) => item?.['borderRadius'] === '50%')).toBe(true)
    }
  })

  it('宽态折叠：列表不渲染；窄态（收起轨）仅徽标计数', () => {
    const collapsed = renderProjectGroup(groupView({ expanded: false }), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    expect(collectByTestId(collapsed, 'fenix-projects-list')).toHaveLength(0)
    expect(collectByTestId(collapsed, 'fenix-projects-header')).toHaveLength(1)

    const rail = renderProjectGroup(groupView({ wide: false }), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    const count = collectByTestId(rail, 'fenix-projects-rail-count')
    expect(count).toHaveLength(1)
    expect(collectByTestId(rail, 'fenix-projects-list')).toHaveLength(0)
  })

  it('空列表：分组呈现空态提示，不渲染项目行', () => {
    const tree = renderProjectGroup(groupView({ projects: [] }), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    expect(collectByTestId(tree, 'fenix-projects-empty')).toHaveLength(1)
    expect(collectByTestId(tree, 'fenix-projects-list')).toHaveLength(1)
  })

  it('限高滚动：列表容器 maxHeight 有上限且 overflowY auto', () => {
    const tree = renderProjectGroup(groupView(), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    const list = collectByTestId(tree, 'fenix-projects-list')[0]
    const style = list?.props?.['style'] as Record<string, unknown>
    expect(String(style?.['maxHeight'])).toMatch(/min\(\d+px/)
    expect(style?.['overflowY']).toBe('auto')
  })

  it('点击项目行：stopPropagation + selectProject(name)，当前行高亮', () => {
    const selected: string[] = []
    let propagationStopped = false
    const tree = renderProjectGroup(
      groupView({ activeProject: 'fenixd' }),
      projectGroupHandlers(projectGroupStore, {
        selectProject: (name) => {
          selected.push(name)
        },
        startProjectSession: () => {},
      }),
    )
    const row = collectByTestId(tree, 'fenix-project-row-dsh-plugins')[0]
    const onClick = row?.props?.['onClick'] as (event: { stopPropagation(): void }) => void
    onClick({
      stopPropagation: () => {
        propagationStopped = true
      },
    })
    expect(selected).toEqual(['dsh-plugins'])
    expect(propagationStopped).toBe(true)
    // 当前高亮项目行 data-active 标记（选中底色由 PROJECT_ROW_CSS 的
    // [data-active] 类规则驱动，inline 无 background——inline 会压过 :hover）。
    const activeRow = collectByTestId(tree, 'fenix-project-row-fenixd')[0]
    expect(activeRow?.props?.['data-active']).toBe(true)
    expect(activeRow?.props?.['className']).toBe('fenix-project-row')
  })

  it('点击头部行：stopPropagation + 仅切换展开/折叠（不触发 selectProject）', () => {
    let selected = 0
    const tree = renderProjectGroup(
      groupView(),
      projectGroupHandlers(projectGroupStore, {
        startProjectSession: () => {},
        selectProject: () => {
          selected += 1
        },
      }),
    )
    const header = collectByTestId(tree, 'fenix-projects-header')[0]
    const onClick = header?.props?.['onClick'] as (event: { stopPropagation(): void }) => void
    onClick({ stopPropagation: () => {} })
    expect(projectGroupStore.getSnapshot().expanded).toBe(false)
    expect(selected).toBe(0)
  })

  it('头部拦截层宽度：headerWidth 缺省回退 rowWidth；提供时用原始量测（不受 360 钳制）', () => {
    const fallback = renderProjectGroup(groupView(), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    const fallbackHeader = collectByTestId(fallback, 'fenix-projects-header')[0]
    expect((fallbackHeader?.props?.['style'] as Record<string, unknown>)?.['width']).toBe(260)

    const wide = renderProjectGroup(groupView({ headerWidth: 420 }), { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} })
    const wideHeader = collectByTestId(wide, 'fenix-projects-header')[0]
    expect((wideHeader?.props?.['style'] as Record<string, unknown>)?.['width']).toBe(420)
  })

  it('projectGroupHandlers：stopPropagation 后分别落 store 切换与 deps.selectProject', () => {
    const selected: string[] = []
    const handlers = projectGroupHandlers(projectGroupStore, {
      startProjectSession: () => {},
      selectProject: (name) => selected.push(name),
    })
    handlers.toggleHeader(fakeEvent())
    expect(projectGroupStore.getSnapshot().expanded).toBe(false)
    handlers.selectProject('fenixd', fakeEvent())
    expect(selected).toEqual(['fenixd'])
    // store 高亮由 index.ts 的 selector 落（此处只验证 handler 不越权改高亮）。
    expect(projectGroupStore.getSnapshot().activeProject).toBeNull()
  })
})

describe('projectPanelSelector（点击 → layout.selectPanel 契约）', () => {
  beforeEach(() => {
    projectGroupStore.reset()
  })

  it('调用 layout.selectPanel(projectId) 并更新分组高亮', () => {
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
    expect(projectGroupStore.getSnapshot().activeProject).toBe('fenixd')
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
    expect(projectGroupStore.getSnapshot().activeProject).toBeNull()
  })

  it('layout 服务缺失（异常环境）：静默降级，仅 warn 不抛', () => {
    expect(() => projectPanelSelector({} as never)('fenixd')).not.toThrow()
  })
})

/* ==================== 「项目」Portal 分区（spec 2026-11 Portal 化） ==================== */

describe('「项目」Portal 分区（纯渲染 + 交互契约）', () => {
  const noopHandlers: ProjectGroupHandlers = { toggleHeader: () => {}, selectProject: () => {}, startProjectSession: () => {} }

  function sectionView(overrides: Partial<Parameters<typeof renderProjectSection>[0]> = {}) {
    return {
      projects: ['fenixd', 'dsh-plugins'],
      expanded: true,
      activeProject: null,
      wide: true,
      rowWidth: 260,
      ...overrides,
    }
  }

  beforeEach(() => {
    projectGroupStore.reset()
  })

  it('宽态：常驻分区 = 纯项目行列表（无自带标题，避免与「项目」菜单重复）', () => {
    const tree = renderProjectSection(sectionView(), noopHandlers)
    const section = collectByTestId(tree, 'fenix-projects-section')
    expect(section).toHaveLength(1)
    expect(section[0]?.props?.['aria-label']).toBe('项目')
    // 分区容器无盒契约（2026-11-03 用户裁决：与原生工作区列表一致）：无
    // border/底色/圆角——行直接铺在侧栏底上，高亮只发生在行 hover/选中。
    const sectionStyle = section[0]?.props?.['style'] as Record<string, unknown>
    expect(sectionStyle?.['border']).toBeUndefined()
    expect(sectionStyle?.['background']).toBeUndefined()
    expect(sectionStyle?.['borderRadius']).toBeUndefined()
    // 无自带标题/计数/折叠头：上方「项目」菜单行即唯一菜单。
    expect(collectByTestId(tree, 'fenix-projects-section-title')).toHaveLength(0)
    expect(collectByTestId(tree, 'fenix-projects-section-count')).toHaveLength(0)
    for (const name of ['fenixd', 'dsh-plugins']) {
      const row = collectByTestId(tree, `fenix-project-row-${name}`)
      expect(row, `项目行 ${name}`).toHaveLength(1)
      const styles = row[0] && (collectByType(row[0], 'span').map((span) => span.props?.style) as (Record<string, unknown> | undefined)[])
      expect(styles?.some((item) => item?.['borderRadius'] === '50%'), '行内含首字母圆形徽标').toBe(true)
    }
  })

  it('行几何与滚动条几何对齐原生工作区列表（2026-11-03 用户裁决）', () => {
    const tree = renderProjectSection(sectionView({ activeProject: 'fenixd' }), noopHandlers)
    // 行：逐键对齐 ui-workspace .projectRow（34px 高 / radius-md / 14px /
    // 20px 行盒 / gap 6 / user-select none / 选中态=interactive-bg-hover，
    // 与原生 selected 同色；非选中行 hover 底走 CSS :hover 不在 inline）。
    const row = collectByTestId(tree, 'fenix-project-row-fenixd')[0]
    const rowStyle = row?.props?.['style'] as Record<string, unknown>
    expect(rowStyle?.['height']).toBe(34)
    expect(rowStyle?.['fontSize']).toBe(14)
    expect(rowStyle?.['lineHeight']).toBe('20px')
    expect(rowStyle?.['gap']).toBe(6)
    expect(String(rowStyle?.['borderRadius'])).toContain('--dsw-radius-md')
    expect(rowStyle?.['userSelect']).toBe('none')
    // hover/选中底色 = 注入式类规则（inline background 会压过 :hover——
    // 历史缺陷），行挂 fenix-project-row 类，CSS 含 :hover/[data-active]/
    // focus-visible 三态且取 interactive-bg-hover 变量。
    expect(row?.props?.['className']).toBe('fenix-project-row')
    expect(rowStyle?.['background']).toBeUndefined()
    expect(PROJECT_ROW_CSS).toContain('.fenix-project-row:hover')
    expect(PROJECT_ROW_CSS).toContain('[data-active]')
    expect(PROJECT_ROW_CSS).toContain(':focus-visible')
    expect(PROJECT_ROW_CSS).toContain('--dsw-alias-interactive-bg-hover')
    // 列表滚动条定制（2026-11-06 用户指令：只留滑块——去上下箭头/轨道底色、
    // 滑块 6px 收窄；testid 作用域限定本列表，不波及页面其他滚动条）。
    expect(PROJECT_ROW_CSS).toContain('[data-testid="fenix-projects-list"]::-webkit-scrollbar { width: 6px; }')
    expect(PROJECT_ROW_CSS).toContain('::-webkit-scrollbar-thumb { border: 0;')
    expect(PROJECT_ROW_CSS).toContain('--dsh-scrollbar-thumb')
    expect(PROJECT_ROW_CSS).toContain('::-webkit-scrollbar-track { background-color: transparent; }')
    expect(PROJECT_ROW_CSS).toContain('::-webkit-scrollbar-button { display: none; }')
    // 官方 Workspaces 列表同款滚动条（2026-11-06 用户指令：与项目卡片一致）。
    // 宿主类名是 CSS modules 哈希（如 bhn1Oq_list），用语义段属性包含匹配
    // （哈希前缀随构建变，_regionArea/_list 语义段稳定）；regionArea 后代
    // 限定不外溢到宿主其他 _list。
    expect(PROJECT_ROW_CSS).toContain('[class*="_regionArea"] [class*="_list"]::-webkit-scrollbar { width: 6px; }')
    expect(PROJECT_ROW_CSS).toContain('[class*="_regionArea"] [class*="_list"]::-webkit-scrollbar-thumb { border: 0;')
    expect(PROJECT_ROW_CSS).toContain('[class*="_regionArea"] [class*="_list"]::-webkit-scrollbar-track { background-color: transparent; }')
    expect(PROJECT_ROW_CSS).toContain('[class*="_regionArea"] [class*="_list"]::-webkit-scrollbar-button { display: none; }')
    // 列表：滚动条贴侧栏右缘（负右边距越过 inline-padding 线只留 offset）+
    // padding-right 把行内容收回 padding 线 + gutter stable 防两态行宽跳动。
    const list = collectByTestId(tree, 'fenix-projects-list')[0]
    const listStyle = list?.props?.['style'] as Record<string, unknown>
    expect(String(listStyle?.['marginRight'])).toContain('--dsh-sidebar-inline-padding')
    // 滑块收窄到 6px 后 gutter 预留同缩（不再引用官方 10px scrollbar-width 变量）
    expect(String(listStyle?.['paddingRight'])).toContain('- 6px')
    expect(listStyle?.['scrollbarGutter']).toBe('stable')
  })

  it('行尾「新建会话」action：宽态行 hover 显现（CSS 类规则），点击/键盘回调 startProjectSession 且阻断冒泡', () => {
    const started: string[] = []
    let propagationStopped = false
    const handlers = projectGroupHandlers(projectGroupStore, {
      selectProject: () => {},
      startProjectSession: (name) => {
        started.push(name)
      },
    })
    const tree = renderProjectSection(sectionView(), handlers)
    const row = collectByTestId(tree, 'fenix-project-row-fenixd')[0]
    // 显现机制：action 包裹层挂 fenix-project-actions 类（行 hover 时由
    // PROJECT_ROW_CSS 显现），按钮挂 fenix-project-action 类 + 原生词典 aria。
    const spans = collectByType(row, 'span')
    const actions = spans.find((span) => span.props?.['className'] === 'fenix-project-actions')
    expect(actions, '行尾 action 包裹层').toBeDefined()
    expect(PROJECT_ROW_CSS).toContain('.fenix-project-row:hover .fenix-project-actions')
    const buttons = collectByType(actions as never, 'button')
    const button = buttons[0]
    const buttonProps = button?.props as Record<string, unknown> | undefined
    expect(buttonProps?.['className']).toBe('fenix-project-action')
    expect(buttonProps?.['aria-label']).toBe('在“fenixd”中新建会话')
    // 点击：回调 startProjectSession 且 stopPropagation（不触发行 selectProject）。
    ;(buttonProps?.['onClick'] as (event: { stopPropagation(): void }) => void)({
      stopPropagation: () => {
        propagationStopped = true
      },
    })
    expect(started).toEqual(['fenixd'])
    expect(propagationStopped).toBe(true)
    // 按钮键盘按键阻断冒泡（行级 Enter/Space 处理器不得把它当「选中项目」）。
    const keyDown = buttonProps?.['onKeyDown'] as (event: { stopPropagation(): void }) => void
    let keyPropagationStopped = false
    keyDown({ stopPropagation: () => { keyPropagationStopped = true } })
    expect(keyPropagationStopped).toBe(true)
    // 窄态徽标栈行无 action（原生收起轨无行内动作）。
    const rail = renderProjectSection(sectionView({ wide: false }), handlers)
    const railRow = collectByTestId(rail, 'fenix-project-row-fenixd')[0]
    expect(collectByType(railRow, 'button')).toHaveLength(0)
  })

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

  it('inject 声明：slots/layout/uiWorkspace/workspaces 四键（新建会话消费二者）', () => {
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

  it('限高滚动：列表容器 5 行封顶（2026-11-06 用户指令：对齐工作区显示逻辑——固定显示 5 个项目，超出滚动条；6 个项目即触发滚动）且 overflowY auto', () => {
    const tree = renderProjectSection(sectionView(), noopHandlers)
    const list = collectByTestId(tree, 'fenix-projects-list')[0]
    const style = list?.props?.['style'] as Record<string, unknown>
    // 5 × GROUP_ROW_HEIGHT(34) + 12 = 182；46vh 兜底防矮视口撑破
    expect(String(style?.['maxHeight'])).toBe('min(182px, 46vh)')
    expect(style?.['overflowY']).toBe('auto')
  })

  it('点击项目行：stopPropagation + selectProject(name)；当前行高亮', () => {
    const selected: string[] = []
    let propagationStopped = false
    const tree = renderProjectSection(
      sectionView({ activeProject: 'fenixd' }),
      projectGroupHandlers(projectGroupStore, {
        selectProject: (name) => {
          selected.push(name)
        },
        startProjectSession: () => {},
      }),
    )
    const row = collectByTestId(tree, 'fenix-project-row-dsh-plugins')[0]
    const onClick = row?.props?.['onClick'] as (event: { stopPropagation(): void }) => void
    onClick({
      stopPropagation: () => {
        propagationStopped = true
      },
    })
    expect(selected).toEqual(['dsh-plugins'])
    expect(propagationStopped).toBe(true)
    const activeRow = collectByTestId(tree, 'fenix-project-row-fenixd')[0]
    expect(activeRow?.props?.['data-active']).toBe(true)
    expect(activeRow?.props?.['className']).toBe('fenix-project-row')
  })

  it('折叠门：expanded=false 分区整体不渲染（宽窄两态同门）；expanded=true 恢复渲染', () => {
    // 2026-11-05 用户指令：「项目」菜单行点击 = 分区折叠开关（不再切换主面板），
    // 折叠态分区整体消失（含空态壳），宽窄两态同门。
    const collapsed = renderProjectSection(sectionView({ expanded: false }), noopHandlers)
    expect(collapsed, '宽态折叠返回 null').toBeNull()
    const railCollapsed = renderProjectSection(sectionView({ expanded: false, wide: false }), noopHandlers)
    expect(railCollapsed, '窄态折叠返回 null').toBeNull()

    const rail = renderProjectSection(sectionView({ wide: false }), noopHandlers)
    expect(collectByTestId(rail, 'fenix-projects-section-title')).toHaveLength(0)
    expect(collectByTestId(rail, 'fenix-projects-section-count')).toHaveLength(0)
    const rows = collectByTestId(rail, 'fenix-project-row-fenixd')
    expect(rows).toHaveLength(1)
    // 徽标栈行：仅首字母徽标（文本=首字母，带 50% 圆角），无项目名文本 span。
    const spans = collectByType(rows[0], 'span')
    expect(spans.map((span) => span.props?.children)).toEqual(['F'])
    expect(
      spans.some((span) => (span.props?.style as Record<string, unknown> | undefined)?.['textOverflow'] === 'ellipsis'),
      '窄态行不含项目名（ellipsis）span',
    ).toBe(false)
  })

  it('空列表折叠：宽态折叠连空态壳一起收起', () => {
    const tree = renderProjectSection(sectionView({ projects: [], expanded: false }), noopHandlers)
    expect(tree).toBeNull()
  })

  it('空列表（宽态）：分区呈现空态提示，不渲染项目行', () => {
    const tree = renderProjectSection(sectionView({ projects: [] }), noopHandlers)
    expect(collectByTestId(tree, 'fenix-projects-empty')).toHaveLength(1)
    expect(collectByTestId(tree, 'fenix-projects-list')).toHaveLength(1)
  })

  describe('「项目」菜单行拦截层（行点击 = 折叠开关，2026-11-05 用户指令）', () => {
    function anchorView(overrides: Partial<Parameters<typeof renderProjectAnchor>[0]> = {}) {
      return {
        portalActive: true,
        iconSize: 16,
        rowWidth: 260,
        headerWidth: 280,
        headerGeometry: { top: -10, left: -30, height: 36 } as const,
        anchorRef: { current: null },
        expanded: true,
        wide: true,
        ...overrides,
      }
    }

    it('portalActive：锚点 = 图标 + 整行拦截层；点击仅切换展开/折叠（阻断 selectPanel）', () => {
      let selected = 0
      const tree = renderProjectAnchor(
        anchorView(),
        projectGroupHandlers(projectGroupStore, {
          startProjectSession: () => {},
          selectProject: () => {
            selected += 1
          },
        }),
      )
      // 定位原点：relative + 可见溢出（拦截层须越出 16×16 图标盒覆盖整行）。
      const style = (tree?.props?.['style'] ?? {}) as Record<string, unknown>
      expect(style['position']).toBe('relative')
      expect(style['overflow']).toBe('visible')
      expect(collectByType(tree, 'svg'), '文件夹图标 + 右侧状态箭头').toHaveLength(2)
      // 拦截层：几何/宽度按量测落 style（宽度用原始量测 headerWidth，不钳 360）。
      const header = collectByTestId(tree, 'fenix-projects-header')[0]
      expect(header).toBeDefined()
      const headerStyle = header?.props?.['style'] as Record<string, unknown>
      expect(headerStyle?.['position']).toBe('absolute')
      expect(headerStyle?.['top']).toBe(-10)
      expect(headerStyle?.['left']).toBe(-30)
      expect(headerStyle?.['height']).toBe(36)
      expect(headerStyle?.['width']).toBe(280)
      // 点击：stopPropagation + 仅切换展开/折叠，不触发 selectProject。
      let propagationStopped = false
      const onClick = header?.props?.['onClick'] as (event: { stopPropagation(): void }) => void
      onClick({
        stopPropagation: () => {
          propagationStopped = true
        },
      })
      expect(projectGroupStore.getSnapshot().expanded).toBe(false)
      expect(propagationStopped).toBe(true)
      expect(selected).toBe(0)
    })

    it('拦截层几何缺省：headerGeometry/headerWidth 缺省回退 DEFAULT 几何与 rowWidth', () => {
      const tree = renderProjectAnchor(anchorView({ headerGeometry: null, headerWidth: undefined }), noopHandlers)
      const headerStyle = collectByTestId(tree, 'fenix-projects-header')[0]?.props?.['style'] as Record<string, unknown>
      expect(headerStyle?.['top']).toBe(-10)
      expect(headerStyle?.['left']).toBe(-10)
      expect(headerStyle?.['height']).toBe(36)
      expect(headerStyle?.['width']).toBe(260)
    })

    it('降级窗口：零尺寸占位，无图标无拦截层（让位浮层分组）', () => {
      const tree = renderProjectAnchor(anchorView({ portalActive: false }), noopHandlers)
      const style = (tree?.props?.['style'] ?? {}) as Record<string, unknown>
      expect(style['width']).toBe(0)
      expect(style['height']).toBe(0)
      expect(style['overflow']).toBe('hidden')
      expect(collectByType(tree, 'svg')).toHaveLength(0)
      expect(collectByTestId(tree, 'fenix-projects-header')).toHaveLength(0)
    })

    it('右侧状态箭头（宽态）：展开 ▾（rotate 90°）/ 折叠 ▸；pointer-events none 点击落到拦截层', () => {
      // 展开态：箭头在行右缘（几何右端内缩），rotate 90° 指向下（与降级路径
      // chevron 同语言：▸ 折叠 / ▾ 展开）。
      const open = renderProjectAnchor(anchorView({ expanded: true }), noopHandlers)
      const openChevron = collectByTestId(open, 'fenix-projects-chevron')[0]
      expect(openChevron, '展开态箭头在场').toBeDefined()
      const openStyle = openChevron?.props?.['style'] as Record<string, unknown>
      // 位置：行右缘 = geometry.left + headerWidth，内缩 12px 行内边距 + 16px 箭头盒。
      expect(openStyle?.['left']).toBe(-30 + 280 - 12 - 16)
      // 垂直居中于行：geometry.top + (行高 - 盒高)/2。
      expect(openStyle?.['top']).toBe(-10 + (36 - 16) / 2)
      expect(openStyle?.['transform']).toBe('rotate(90deg)')
      expect(openStyle?.['pointerEvents']).toBe('none')
      expect(collectByType(openChevron, 'svg'), '箭头 svg 在场').toHaveLength(1)

      // 折叠态：同位箭头回正（▸）。
      const closed = renderProjectAnchor(anchorView({ expanded: false }), noopHandlers)
      const closedChevron = collectByTestId(closed, 'fenix-projects-chevron')[0]
      expect(closedChevron, '折叠态箭头在场').toBeDefined()
      expect((closedChevron?.props?.['style'] as Record<string, unknown>)?.['transform']).toBe('rotate(0deg)')
    })

    it('右侧状态箭头（窄态/降级）：收起轨不放箭头（原生窄轨无展开指示）', () => {
      const rail = renderProjectAnchor(anchorView({ wide: false }), noopHandlers)
      expect(collectByTestId(rail, 'fenix-projects-chevron')).toHaveLength(0)
      const degraded = renderProjectAnchor(anchorView({ portalActive: false, wide: false }), noopHandlers)
      expect(collectByTestId(degraded, 'fenix-projects-chevron')).toHaveLength(0)
    })
  })
})

describe('「项目」分区锚点/宿主/挂载状态机（纯判定，node 桩替身）', () => {
  /** 桩锚点原点：closest 按 selector 返回注入候选（未注入的 selector 返回 null）。 */
  function fakeOrigin(candidates: Record<string, unknown>): { closest(selectors: string): unknown } {
    return {
      closest(selectors: string) {
        return candidates[selectors] ?? null
      },
    }
  }

  function fakeHost(overrides: Partial<SectionHostElement> = {}): SectionHostElement {
    return {
      dataset: {},
      style: { cssText: '' },
      isConnected: true,
      remove() {},
      previousElementSibling: undefined,
      ...overrides,
    }
  }

  it('sidebarNavFrom：语义锚点 closest(nav) 命中；非 nav/缺失原点返回 null', () => {
    const nav = { tag: 'nav' }
    expect(sidebarNavFrom(fakeOrigin({ [SECTION_ANCHOR_SELECTOR]: nav }))).toBe(nav)
    expect(sidebarNavFrom(fakeOrigin({}))).toBeNull()
    expect(sidebarNavFrom(null)).toBeNull()
    expect(sidebarNavFrom(undefined)).toBeNull()
  })

  it('sectionAnchorFrom：优先「项目」行按钮（宿主紧贴菜单行下方）；行漂移回落 nav', () => {
    const row = { tag: 'button' }
    const nav = { tag: 'nav' }
    // 行按钮可达：优先行锚点（分区在项目菜单正下方）。
    expect(sectionAnchorFrom(fakeOrigin({ [SECTION_ROW_SELECTOR]: row, [SECTION_ANCHOR_SELECTOR]: nav }))).toBe(row)
    // 行按钮不可得（结构漂移）：回落 nav（现行为：列表末尾）。
    expect(sectionAnchorFrom(fakeOrigin({ [SECTION_ANCHOR_SELECTOR]: nav }))).toBe(nav)
    // 均不可得：null（状态机累计失败 → 浮层降级）。
    expect(sectionAnchorFrom(fakeOrigin({}))).toBeNull()
    expect(sectionAnchorFrom(null)).toBeNull()
  })

  it('measureHeaderGeometry：行按钮在图标原点左上方，量测 top/left 为负偏移（与缺省几何同语义）', () => {
    const rowRect = { top: 100, left: 8, height: 36 }
    const originRect = { top: 110, left: 18, height: 16 }
    const geometry = measureHeaderGeometry({
      closest(selectors: string) {
        return selectors === SECTION_ROW_SELECTOR ? { getBoundingClientRect: () => rowRect } : null
      },
      getBoundingClientRect: () => originRect,
    })
    expect(geometry).not.toBeNull()
    expect(geometry?.top).toBe(rowRect.top - originRect.top)
    expect(geometry?.left).toBe(rowRect.left - originRect.left)
    expect(geometry?.top).toBeLessThanOrEqual(0)
    expect(geometry?.left).toBeLessThanOrEqual(0)
  })

  it('isAnchorReachable：isConnected 判定可达性（null/非对象不可达）', () => {
    expect(isAnchorReachable(fakeHost())).toBe(true)
    expect(isAnchorReachable(fakeHost({ isConnected: false }))).toBe(false)
    expect(isAnchorReachable(null)).toBe(false)
    expect(isAnchorReachable('nav')).toBe(false)
  })

  it('mountSectionHost：宿主 div 插入 nav 紧后兄弟位并带 testid/收缩样式', () => {
    const host = fakeHost()
    const inserted: { position?: string; element?: unknown } = {}
    const nav = {
      insertAdjacentElement(position: string, element: unknown) {
        inserted.position = position
        inserted.element = element
        return element
      },
    }
    expect(mountSectionHost(nav, { createElement: () => host })).toBe(host)
    expect(inserted.position).toBe('afterend')
    expect(inserted.element).toBe(host)
    expect(host.dataset.testid).toBe(SECTION_HOST_TESTID)
    expect(host.style.cssText).toContain('min-height:0')
  })

  it('mountSectionHost：插入失败（返回 null，如 nav 断连）→ 返回 null 交状态机累计', () => {
    const nav = {
      insertAdjacentElement() {
        return null
      },
    }
    expect(mountSectionHost(nav, { createElement: () => fakeHost() })).toBeNull()
  })

  it('nextPortalMountState：连续失败达阈值置 degraded；成功清零；同态幂等同引用', () => {
    let state: PortalMountState = { status: 'seeking', failures: 0 }
    state = nextPortalMountState(state, false)
    expect(state).toEqual({ status: 'seeking', failures: 1 })
    state = nextPortalMountState(state, false)
    expect(state).toEqual({ status: 'seeking', failures: 2 })
    state = nextPortalMountState(state, false)
    expect(state, `连续 ${PORTAL_DEGRADE_FAILURES} 次失败置 degraded`).toEqual({ status: 'degraded', failures: 3 })
    // degraded 幂等：继续失败保持原态（轮询兜底持续运行，不无限累计）。
    expect(nextPortalMountState(state, false)).toBe(state)
    // 恢复：挂载成功 → active 且清零（degraded 可恢复而非永久停用）。
    const recovered = nextPortalMountState(state, true)
    expect(recovered).toEqual({ status: 'active', failures: 0 })
    // active 幂等：成功但已 active 返回同引用（React setState 天然去重）。
    expect(nextPortalMountState(recovered, true)).toBe(recovered)
  })

  it('isPortalActive：active + 宿主连接才生效；degraded/宿主被删均不生效', () => {
    expect(isPortalActive({ status: 'active', failures: 0 }, fakeHost())).toBe(true)
    expect(isPortalActive({ status: 'active', failures: 0 }, fakeHost({ isConnected: false }))).toBe(false)
    expect(isPortalActive({ status: 'degraded', failures: 3 }, fakeHost())).toBe(false)
    expect(isPortalActive({ status: 'seeking', failures: 1 }, fakeHost())).toBe(false)
    expect(isPortalActive({ status: 'active', failures: 0 }, null)).toBe(false)
  })

  it('宽窄态判定与行宽钳制阈值', () => {
    expect(isWideSectionWidth(280)).toBe(true)
    expect(isWideSectionWidth(120)).toBe(true)
    expect(isWideSectionWidth(56)).toBe(false)
    expect(clampSectionRowWidth(280)).toBe(280)
    expect(clampSectionRowWidth(400)).toBe(360)
    expect(clampSectionRowWidth(90)).toBe(160)
  })
})
