/**
 * Client 半单测（2026-10 分组化数据流 + move-project-nav-to-workspace-rows
 * 工作区自动对齐步）：reconcile 三态与幂等、失败兜底、同步循环（假定时器/
 * 焦点桩）、项目列表解析、数据源（store）契约、工作区对齐四态（新建/已存在
 * 跳过/删除项目不删工作区/拉取失败整轮跳过）。
 */
import { describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_POLL_INTERVAL_MS,
  MIN_POLL_INTERVAL_MS,
  compareNames,
  parseProjectNames,
  reconcileProjects,
  startProjectSync,
} from '../src/client/projectSync.js'
import type { ProjectEntrySink, ProjectRowInfo, SyncTimer, WorkspaceItemLike } from '../src/client/projectSync.js'
import { projectGroupStore } from '../src/client/panels.js'

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

/** 等待启动拉取 + 对齐步整链落定（pull → reconcile → setProjects → align）。 */
const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) await tick()
}

interface RecordingSink extends ProjectEntrySink {
  readonly added: string[]
  readonly removed: string[]
  readonly projectSets: readonly (readonly string[])[]
  readonly rowSets: readonly (readonly ProjectRowInfo[])[]
  calls(): number
}

function recordingSink(): RecordingSink {
  const added: string[] = []
  const removed: string[] = []
  const projectSets: (readonly string[])[] = []
  const rowSets: (readonly ProjectRowInfo[])[] = []
  return {
    added,
    removed,
    projectSets,
    rowSets,
    addProject(name) {
      added.push(name)
    },
    removeProject(name) {
      removed.push(name)
    },
    setProjects(names) {
      projectSets.push([...names])
    },
    setProjectRows(rows) {
      rowSets.push([...rows])
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

/** 工作区快照行构造（WorkspaceItemLike）。 */
const wsItem = (workspaceId: string, path: string, title: string): WorkspaceItemLike => ({ workspaceId, path, title })

/** 对齐步依赖装配：固定 payload + 工作区快照 + create 调用迹。 */
function alignFixture(items: readonly WorkspaceItemLike[], payload: unknown) {
  const created: string[] = []
  return {
    created,
    deps: {
      fetchProjectRows: async () => payload,
      workspaceItems: () => items,
      createWorkspace: async (input: { readonly path: string }) => {
        created.push(input.path)
        return { workspaceId: `w-${created.length}` }
      },
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

describe('工作区自动对齐（alignWorkspaces 四态 + 降级路径）', () => {
  it('①新建：exists 可达项目无命中工作区 → workspaces.create({path}) 注册（不开会话）', async () => {
    const sink = recordingSink()
    const timer = fakeTimer()
    const { created, deps } = alignFixture([wsItem('w-other', '/r/other', 'other')], {
      projects: [{ name: 'newproj', path: '/r/newproj', exists: true }],
    })
    const stop = startProjectSync({
      fetchProjects: async () => ['newproj'],
      sink,
      intervalMs: 5_000,
      timer,
      ...deps,
    })
    await settle()
    expect(created).toEqual(['/r/newproj'])
    // 行信息沉淀（名称导航路径判据消费）：names 序，path 来自 payload。
    expect(sink.rowSets.at(-1)).toEqual([{ name: 'newproj', path: '/r/newproj' }])
    stop()
  })

  it('②已存在跳过：归一化路径命中（尾斜杠差异）→ 零 create', async () => {
    const sink = recordingSink()
    const timer = fakeTimer()
    const { created, deps } = alignFixture([wsItem('w-a', '/r/a', 'a')], {
      projects: [{ name: 'a', path: '/r/a/', exists: true }],
    })
    const stop = startProjectSync({
      fetchProjects: async () => ['a'],
      sink,
      intervalMs: 5_000,
      timer,
      ...deps,
    })
    await settle()
    expect(created).toEqual([])
    expect(sink.rowSets.at(-1)).toEqual([{ name: 'a', path: '/r/a/' }])
    stop()
  })

  it('③删除项目不删工作区：项目从列表消失后其工作区保留（只增不改不删，无删除通道）', async () => {
    const sink = recordingSink()
    const timer = fakeTimer()
    const { created, deps } = alignFixture([wsItem('w-gone', '/r/gone', 'gone')], { projects: [] })
    const stop = startProjectSync({
      fetchProjects: async () => [], // 项目已全部删除
      sink,
      intervalMs: 5_000,
      timer,
      ...deps,
    })
    await settle()
    expect(created).toEqual([]) // 无对齐动作
    expect(sink.rowSets.at(-1)).toEqual([]) // 行表为空，快照不动工作区
    stop()
  })

  it('④拉取失败整轮跳过：warn 落日志、不建不删、无未处理异常', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const sink = recordingSink()
      const timer = fakeTimer()
      const { created } = alignFixture([], { projects: [] })
      const stop = startProjectSync({
        fetchProjects: async () => ['a'],
        sink,
        intervalMs: 5_000,
        timer,
        fetchProjectRows: async () => {
          throw new Error('align fetch down')
        },
        workspaceItems: () => [],
        createWorkspace: async () => {
          throw new Error('should not be called')
        },
      })
      await settle()
      expect(created).toEqual([])
      const messages = warn.mock.calls.map((call) => String(call[0]))
      expect(messages.some((message) => message.includes('对齐拉取项目列表失败') && message.includes('本轮跳过'))).toBe(
        true,
      )
      stop()
    } finally {
      warn.mockRestore()
    }
  })

  it('exists=false（目录不可达）不对齐：path null → continue，不 create', async () => {
    const sink = recordingSink()
    const timer = fakeTimer()
    const { created, deps } = alignFixture([], {
      projects: [{ name: 'ghost', path: '/no/such/dir', exists: false }],
    })
    const stop = startProjectSync({
      fetchProjects: async () => ['ghost'],
      sink,
      intervalMs: 5_000,
      timer,
      ...deps,
    })
    await settle()
    expect(created).toEqual([])
    // 不可达行仍沉淀（path null → 名称导航走 title 兜底）。
    expect(sink.rowSets.at(-1)).toEqual([{ name: 'ghost', path: null }])
    stop()
  })

  it('依赖三缺一整段禁用：fetchProjectRows 不被消费（测试桩零动作零网络）', async () => {
    const fetchRows = vi.fn(async () => ({ projects: [] }))
    const timer = fakeTimer()
    const sink = recordingSink()
    const stop = startProjectSync({
      fetchProjects: async () => ['a'],
      sink,
      intervalMs: 5_000,
      timer,
      fetchProjectRows: fetchRows,
      // workspaceItems / createWorkspace 缺席 → 整段禁用。
    })
    await settle()
    expect(fetchRows).not.toHaveBeenCalled()
    stop()
  })

  it('单项目注册失败：warn 跳过，下一项目继续（下轮重试缺失者）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const sink = recordingSink()
      const timer = fakeTimer()
      const created: string[] = []
      const stop = startProjectSync({
        fetchProjects: async () => ['bad', 'good'],
        sink,
        intervalMs: 5_000,
        timer,
        fetchProjectRows: async () => ({
          projects: [
            { name: 'bad', path: '/r/bad', exists: true },
            { name: 'good', path: '/r/good', exists: true },
          ],
        }),
        workspaceItems: () => [],
        createWorkspace: async (input) => {
          created.push(input.path)
          if (input.path === '/r/bad') throw new Error('create boom')
          return { workspaceId: 'w-good' }
        },
      })
      await settle()
      // 首项目失败不阻断后续项目。
      expect(created).toEqual(['/r/bad', '/r/good'])
      const messages = warn.mock.calls.map((call) => String(call[0]))
      expect(messages.some((message) => message.includes('对齐注册失败') && message.includes('bad'))).toBe(true)
      stop()
    } finally {
      warn.mockRestore()
    }
  })
})

describe('projectGroupStore（名称导航数据源契约）', () => {
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

  it('setProjectRows 整体替换 + 幂等（无变化零通知）；setProjects 不动 rows 段', () => {
    projectGroupStore.reset() // reset 先于订阅（reset 自身也 emit）
    const seen: number[] = []
    const unsubscribe = projectGroupStore.subscribe(() => {
      seen.push(1)
    })
    projectGroupStore.setProjects(['a']) // 通知 1
    projectGroupStore.setProjectRows([{ name: 'a', path: '/r/a' }]) // 通知 2
    expect(projectGroupStore.getSnapshot().projectRows).toEqual([{ name: 'a', path: '/r/a' }])
    projectGroupStore.setProjectRows([{ name: 'a', path: '/r/a' }]) // 同 rows：零通知
    expect(seen).toHaveLength(2)
    projectGroupStore.setProjectRows([{ name: 'a', path: '/r/a2' }]) // 通知 3
    expect(seen).toHaveLength(3)
    expect(projectGroupStore.getSnapshot().projectRows).toEqual([{ name: 'a', path: '/r/a2' }])
    // setProjects 只换 projects 段，rows 保留（滞后容忍）。
    projectGroupStore.setProjects(['b']) // 通知 4
    expect(seen).toHaveLength(4)
    expect(projectGroupStore.getSnapshot().projectRows).toEqual([{ name: 'a', path: '/r/a2' }])
    expect(projectGroupStore.getSnapshot().projects).toEqual(['b'])
    unsubscribe()
  })

  it('同步驱动共享数据源：sink 落 store（projects 排序 + rows 按 names 序沉淀）', async () => {
    projectGroupStore.reset()
    const sink: ProjectEntrySink = {
      addProject() {},
      removeProject() {},
      setProjects(names) {
        projectGroupStore.setProjects(names)
      },
      setProjectRows(rows) {
        projectGroupStore.setProjectRows(rows)
      },
    }
    const timer = fakeTimer()
    const stop = startProjectSync({
      fetchProjects: async () => ['fenixd', 'dsh-plugins'],
      sink,
      intervalMs: 5_000,
      timer,
      fetchProjectRows: async () => ({
        projects: [
          { name: 'fenixd', path: '/r/fenixd', exists: true },
          { name: 'dsh-plugins', path: '/r/dsh-plugins', exists: true },
        ],
      }),
      workspaceItems: () => [],
      createWorkspace: async ({ path }) => ({ workspaceId: `w-${path}` }),
    })
    await settle()
    expect(projectGroupStore.getSnapshot().projects).toEqual(['dsh-plugins', 'fenixd'])
    // rows 保持 names 序（消费方 buildProjectRowMap 自行按名查路径，序无关紧要，
    // 但 store 幂等判据按逐位比较——序稳定是零通知的前提）。
    expect(projectGroupStore.getSnapshot().projectRows).toEqual([
      { name: 'fenixd', path: '/r/fenixd' },
      { name: 'dsh-plugins', path: '/r/dsh-plugins' },
    ])
    stop()
  })
})
