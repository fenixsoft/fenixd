/**
 * Client 半单测（2026-10 分组化数据流）：reconcile 三态与幂等、失败兜底、
 * 同步循环（假定时器/焦点桩）、项目列表解析、分组数据源（store）契约。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_POLL_INTERVAL_MS,
  MIN_POLL_INTERVAL_MS,
  compareNames,
  parseProjectNames,
  reconcileProjects,
  startProjectSync,
} from '../src/client/projectSync.js'
import type { ProjectEntrySink, SyncTimer } from '../src/client/projectSync.js'
import { projectGroupStore, renderProjectSection } from '../src/client/panels.js'

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

/** 按 data-testid 收集元素树命中的 React 元素（与 srcContract 同款最小实现）。 */
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

interface ElementLike {
  readonly type?: unknown
  readonly props?: { readonly children?: unknown; readonly [key: string]: unknown }
}

interface RecordingSink extends ProjectEntrySink {
  readonly added: string[]
  readonly removed: string[]
  readonly projectSets: readonly (readonly string[])[]
  calls(): number
}

function recordingSink(): RecordingSink {
  const added: string[] = []
  const removed: string[] = []
  const projectSets: (readonly string[])[] = []
  return {
    added,
    removed,
    projectSets,
    addProject(name) {
      added.push(name)
    },
    removeProject(name) {
      removed.push(name)
    },
    setProjects(names) {
      projectSets.push([...names])
    },
    calls: () => added.length + removed.length,
  }
}

function fakeTimer(): SyncTimer & {
  triggerInterval(): void
  triggerFocus(): void
  cleared: boolean
  focusUnsubscribed: boolean
  intervalMs: number | undefined
} {
  let intervalFn: (() => void) | undefined
  let focusFn: (() => void) | undefined
  const state = {
    cleared: false,
    focusUnsubscribed: false,
    intervalMs: undefined as number | undefined,
    triggerInterval() {
      void intervalFn?.()
    },
    triggerFocus() {
      void focusFn?.()
    },
  }
  return {
    get cleared() {
      return state.cleared
    },
    get focusUnsubscribed() {
      return state.focusUnsubscribed
    },
    get intervalMs() {
      return state.intervalMs
    },
    triggerInterval: state.triggerInterval,
    triggerFocus: state.triggerFocus,
    setInterval(fn, ms) {
      intervalFn = fn
      state.intervalMs = ms
      return Symbol('interval-handle')
    },
    clear() {
      state.cleared = true
    },
    onFocus(fn) {
      focusFn = fn
      return () => {
        state.focusUnsubscribed = true
      }
    },
  }
}

describe('reconcileProjects（main 面板差异，指纹幂等）', () => {
  it('新增：空 → {a,b} 全部注册（名称序无关差异数）', () => {
    const sink = recordingSink()
    const next = reconcileProjects(new Set(), ['b', 'a'], sink)
    expect(sink.added.sort()).toEqual(['a', 'b'])
    expect(sink.removed).toEqual([])
    expect([...next].sort()).toEqual(['a', 'b'])
  })

  it('移除：消失项目 dispose，保留项零操作', () => {
    const sink = recordingSink()
    const next = reconcileProjects(new Set(['a', 'b']), ['a'], sink)
    expect(sink.removed).toEqual(['b'])
    expect(sink.added).toEqual([])
    expect([...next]).toEqual(['a'])
  })

  it('无变化：指纹一致零操作（连续同列表零重注册）', () => {
    const sink = recordingSink()
    const current = new Set(['a', 'b'])
    const once = reconcileProjects(current, ['a', 'b'], sink)
    expect(sink.calls()).toBe(0)
    const twice = reconcileProjects(once, ['b', 'a'], sink)
    expect(sink.calls()).toBe(0)
    expect(twice).toEqual(once)
  })

  it('重复名去重后视为单项目', () => {
    const sink = recordingSink()
    const next = reconcileProjects(new Set(), ['x', 'x', 'a'], sink)
    expect(sink.added.sort()).toEqual(['a', 'x'])
    expect(next.size).toBe(2)
  })

  it('compareNames 码点序确定', () => {
    expect(compareNames('a', 'b')).toBe(-1)
    expect(compareNames('b', 'a')).toBe(1)
    expect(compareNames('same', 'same')).toBe(0)
  })
})

describe('parseProjectNames', () => {
  it('解析 {projects:[{name}]} 形状', () => {
    expect(parseProjectNames({ projects: [{ name: 'fenixd' }, { name: 'dsh-plugins' }] })).toEqual([
      'fenixd',
      'dsh-plugins',
    ])
  })

  it('空数组合法', () => {
    expect(parseProjectNames({ projects: [] })).toEqual([])
  })

  it('缺失/非字符串 name 的行跳过并计数 warn（行级漂移可观测）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      expect(parseProjectNames({ projects: [{ name: 'a' }, {}, { name: 42 }, null, { name: 'b' }] })).toEqual(['a', 'b'])
      expect(warn).toHaveBeenCalledTimes(1)
      expect(String(warn.mock.calls[0]?.[0])).toContain('3/5')
    } finally {
      warn.mockRestore()
    }
  })

  it('projects 非空但全部行无有效 name → 抛形状异常（防「项目全部消失」静默故障）', () => {
    expect(() => parseProjectNames({ projects: [{}, { name: 42 }] })).toThrow(/形状异常/)
    expect(() => parseProjectNames({ projects: [{ title: 'renamed' }] })).toThrow(/形状异常/)
  })

  it('形状异常抛错（按拉取失败处理）', () => {
    expect(() => parseProjectNames({ items: [] })).toThrow(/projects/)
    expect(() => parseProjectNames(null)).toThrow(/projects/)
    expect(() => parseProjectNames({ projects: 'nope' })).toThrow(/projects/)
  })
})

describe('startProjectSync 同步循环', () => {
  it('启动即拉取；周期与焦点触发重拉；幂等；stop 后不再拉取', async () => {
    let list: string[] = ['a']
    let fetchCalls = 0
    const timer = fakeTimer()
    const sink = recordingSink()

    const stop = startProjectSync({
      fetchProjects: async () => {
        fetchCalls += 1
        return list
      },
      sink,
      intervalMs: 6_000,
      timer,
    })
    await tick()
    expect(fetchCalls).toBe(1)
    expect(sink.added).toEqual(['a'])
    expect(sink.projectSets).toEqual([['a']])
    // ≥ 下界的周期原样透传（< 下界的钳制行为见下方专测）。
    expect(timer.intervalMs).toBe(6_000)

    // 周期触发：列表变化 → 差异注册 + 数据源整体替换。
    list = ['a', 'b']
    timer.triggerInterval()
    await tick()
    expect(sink.added).toEqual(['a', 'b'])
    expect(sink.projectSets).toEqual([['a'], ['a', 'b']])

    // 焦点触发：列表无变化 → 面板零操作，数据源仍整体替换（store 内幂等）。
    timer.triggerFocus()
    await tick()
    expect(sink.calls()).toBe(2)
    expect(sink.projectSets).toHaveLength(3)

    // stop：清定时器 + 退订焦点 + 停止拉取。
    stop()
    expect(timer.cleared).toBe(true)
    expect(timer.focusUnsubscribed).toBe(true)
    const callsAtStop = fetchCalls
    timer.triggerInterval()
    timer.triggerFocus()
    await tick()
    expect(fetchCalls).toBe(callsAtStop)
    expect(sink.calls()).toBe(2)

    // 再次 stop 安全。
    expect(() => stop()).not.toThrow()
  })

  it('默认周期为 60s；默认计时器在 node（无 window）下焦点订阅为 no-op', () => {
    const stop = startProjectSync({
      fetchProjects: async () => [],
      sink: recordingSink(),
      timer: undefined,
    })
    expect(DEFAULT_POLL_INTERVAL_MS).toBe(60_000)
    expect(() => stop()).not.toThrow()
  })

  it('fetch reject 失败兜底：sink 不动、无未处理异常，下一轮恢复同步', async () => {
    let shouldFail = true
    const timer = fakeTimer()
    const sink = recordingSink()
    const stop = startProjectSync({
      fetchProjects: async () => {
        if (shouldFail) throw new Error('upstream down')
        return ['a']
      },
      sink,
      intervalMs: 5_000,
      timer,
    })
    await tick()
    await tick()
    expect(sink.calls()).toBe(0)
    expect(sink.projectSets).toHaveLength(0)

    shouldFail = false
    timer.triggerInterval()
    await tick()
    expect(sink.added).toEqual(['a'])
    expect(sink.projectSets).toEqual([['a']])
    stop()
  })

  it('空列表：全部项目 main 面板 dispose（固定条目不受影响），数据源清空', async () => {
    const timer = fakeTimer()
    const sink = recordingSink()
    let list: string[] = ['a', 'b']
    const stop = startProjectSync({
      fetchProjects: async () => list,
      sink,
      intervalMs: 5_000,
      timer,
    })
    await tick()
    expect(sink.calls()).toBe(2)

    list = []
    timer.triggerInterval()
    await tick()
    expect(sink.removed.sort()).toEqual(['a', 'b'])
    expect(sink.added).toHaveLength(2)
    expect(sink.projectSets.at(-1)).toEqual([])
    stop()
  })
})

describe('startProjectSync intervalMs 规整（下界钳制防御）', () => {
  it('非有限/非正数回退缺省 60s 并 warn 一次', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
        const timer = fakeTimer()
        const stop = startProjectSync({
          fetchProjects: async () => [],
          sink: recordingSink(),
          intervalMs: bad,
          timer,
        })
        expect(timer.intervalMs).toBe(DEFAULT_POLL_INTERVAL_MS)
        stop()
      }
      expect(warn).toHaveBeenCalledTimes(4)
      expect(String(warn.mock.calls[0]?.[0])).toContain('回退缺省')
    } finally {
      warn.mockRestore()
    }
  })

  it('合法但低于 5s 下界的钳到 5s 并 warn；≥5s 原样透传且不 warn', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const clampedTimer = fakeTimer()
      const stopClamped = startProjectSync({
        fetchProjects: async () => [],
        sink: recordingSink(),
        intervalMs: MIN_POLL_INTERVAL_MS - 1,
        timer: clampedTimer,
      })
      expect(clampedTimer.intervalMs).toBe(MIN_POLL_INTERVAL_MS)
      stopClamped()

      const passthroughTimer = fakeTimer()
      const stopPassthrough = startProjectSync({
        fetchProjects: async () => [],
        sink: recordingSink(),
        intervalMs: 30_000,
        timer: passthroughTimer,
      })
      expect(passthroughTimer.intervalMs).toBe(30_000)
      stopPassthrough()

      expect(warn).toHaveBeenCalledTimes(1)
      expect(String(warn.mock.calls[0]?.[0])).toContain('钳制')
    } finally {
      warn.mockRestore()
    }
  })
})

describe('projectGroupStore（分组数据源契约）', () => {
  beforeEach(() => {
    projectGroupStore.reset()
  })

  it('setProjects 去重 + 码点序排序；无变化零通知', () => {
    const seen: string[][] = []
    const unsubscribe = projectGroupStore.subscribe(() => {
      seen.push([...projectGroupStore.getSnapshot().projects])
    })
    projectGroupStore.setProjects(['dsh-plugins', 'fenixd', 'fenixd'])
    expect(projectGroupStore.getSnapshot().projects).toEqual(['dsh-plugins', 'fenixd'])
    projectGroupStore.setProjects(['fenixd', 'dsh-plugins'])
    expect(seen).toHaveLength(1)
    unsubscribe()
  })

  it('展开/折叠与高亮切换；高亮项目从列表消失时归空', () => {
    projectGroupStore.setProjects(['a', 'b'])
    projectGroupStore.setActiveProject('a')
    expect(projectGroupStore.getSnapshot().activeProject).toBe('a')
    projectGroupStore.toggleExpanded()
    expect(projectGroupStore.getSnapshot().expanded).toBe(false)
    projectGroupStore.setProjects(['b'])
    expect(projectGroupStore.getSnapshot().activeProject).toBeNull()
    expect(projectGroupStore.getSnapshot().expanded).toBe(false)
    projectGroupStore.toggleExpanded()
    expect(projectGroupStore.getSnapshot().expanded).toBe(true)
  })

  it('同步驱动共享数据源：setProjects 后 Portal 分区纯渲染面直接可见（分区/降级浮层同源）', async () => {
    const sink: ProjectEntrySink = {
      addProject() {},
      removeProject() {},
      setProjects(names) {
        projectGroupStore.setProjects(names)
      },
    }
    const timer = fakeTimer()
    const stop = startProjectSync({
      fetchProjects: async () => ['fenixd', 'dsh-plugins'],
      sink,
      intervalMs: 5_000,
      timer,
    })
    await tick()
    const snapshot = projectGroupStore.getSnapshot()
    expect(snapshot.projects).toEqual(['dsh-plugins', 'fenixd'])
    // Portal 分区纯渲染面（renderProjectSection）从同一快照渲染项目行。
    const tree = renderProjectSection(
      { projects: snapshot.projects, expanded: true, activeProject: null, wide: true, rowWidth: 260 },
      { toggleHeader() {}, selectProject() {}, startProjectSession() {} },
    )
    expect(collectByTestId(tree, 'fenix-projects-section')).toHaveLength(1)
    expect(collectByTestId(tree, 'fenix-project-row-fenixd')).toHaveLength(1)
    expect(collectByTestId(tree, 'fenix-project-row-dsh-plugins')).toHaveLength(1)
    stop()
  })
})
