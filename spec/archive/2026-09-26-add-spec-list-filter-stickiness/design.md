# Context

`pages/projects/list.tsx`（路由 `/projects/:name`）当前 5 项易失状态（list.tsx 行号以主树 HEAD 为准）：

- 搜索：`q`（:542，输入框即时值）、`debouncedQ`（:544，300ms 防抖后参与过滤）
- 状态多选：`statusList`（:545）
- 类型：`type`（:546，`TypeFilter = '' | 'active' | 'completed'`）
- 归档：`archivedOnly`（:548）
- 页签：`activeTab`（:579，`'dev' | 'quality' | 'regression' | 'session'`，Tabs `activeKey` :1172）

进入 spec 详情（`/projects/:name/:spec`）或刷新都会卸载重建本组件，上述状态全部归零。过滤条 UI（:1194-1238）在桌面/移动端共用，`filtered` 口径（:713-728）由 `debouncedQ/statusList/type/archivedOnly` 派生。三个次级页签组件（`QualityTab`/`RegressionTab`/`SessionPanel`）以 `active` prop 门控按需拉取。

前端栈 `@umijs/max` v4.7.3，`useSearchParams` 为其内置导出（react-router v6 语义）。项目前端测试仅覆盖纯函数模块，组件级交互验证走浏览器 E2E 场景。

# Goals / Non-Goals

- **Goals**：从 spec 详情返回、页面刷新、带参链接直达三条路径下，4 个过滤条件 + 页签选中态完整恢复；URL 始终是合法、可分享、自解释的视图快照。
- **Non-Goals**：分页页码、树形展开状态不持久化；不引入 localStorage；不改任何既有过滤口径/防抖时长/页签门控语义。

# Decisions

## D1. URL 是持久化介质，不是唯一真源（mount 读一次 + 变更写回，不监听 popstate）

组件挂载时用 `useState` 惰性初始化从 URL 读参恢复；此后 UI 仍由 state 驱动，状态变更通过 effect 写回 URL。**不做**「URL 变化 → state 跟随」的双向绑定。

理由：写侧统一用 `replace` 语义后，过滤操作不产生历史条目，同页历史栈内不会出现「同一页面的不同过滤形态」，浏览器返回必然跨页（详情 → 列表）触发 remount，mount 读参已完整覆盖恢复场景；popstate 同步只在 push 语义下才有意义。单向流避免与 SSE 流式刷新（30s 心跳重拉、增量 patch）、搜索防抖等既有异步逻辑纠缠。

## D2. 参数白名单与缺省约定

| 参数 | 合法值 | 缺省（不写参） | 承载 state |
|------|--------|----------------|------------|
| `tab` | `dev`/`quality`/`regression`/`session` | `dev` | `activeTab` |
| `q` | 任意 URL 编码文本（trim 后空串视为无参） | 空 | `q` + `debouncedQ` |
| `status` | 11 个状态枚举的逗号分隔子集 | 空 | `statusList` |
| `type` | `active`/`completed` | 空（全部） | `type` |
| `archived` | `1` | 未归档 | `archivedOnly` |

状态枚举合法集与过滤下拉选项同源：`drafted, ready, reviewing, implementing, implemented, testing, verified, bug-found, blocked, done, pushed`。缺省值不写参，保证默认视图下 URL 与现状完全一致（零回归、可分享干净链接）。

## D3. fail-safe 白名单解析（读侧对脏参数免疫）

解析集中在单一纯函数（如 `parseListFilters(searchParams)`），逐项白名单校验：非法 `tab`/`type` 整体忽略回默认；`status` 按合法集过滤，逐个丢弃非法枚举（全非法视为无参）；`archived` 仅 `1` 为真。解析即消毒——mount 后写回 effect 首跑会把脏 URL（如 `?tab=hack&status=xxx,type`）自动清洗为干净形态，无 console error、无崩溃。纯函数形态便于纳入既有前端单测（项目测试当前覆盖纯函数模块）。

## D4. 搜索词按防抖节拍写 URL，恢复时直达

`q` 输入框即时值仍只走本地 state；`debouncedQ` 到期后才随既有防抖 effect 落 URL（replace）。避免逐字符 `setSearchParams` 的无谓替换。恢复方向：URL `q` 同时灌入 `q`（输入框回显）与 `debouncedQ`（立即过滤），不出现「先闪全量列表、300ms 后才过滤」的抖动。

## D5. 页签恢复与按需加载门控相容

URL 带 `tab=quality|regression|session` 打开时，恢复的 `activeTab` 使对应组件 `active` prop 为 true，既有按需拉取逻辑自然触发——与用户手动点击页签行为完全一致。关键约束不变：仍**不隐式启动会话进程**（`SessionPanel` 拉取状态后未启动则显示「开始会话」空态），未选中分面仍零请求。

# Risks / Trade-offs

- **URL 可被手工改坏** → D3 白名单解析兜底，脏参数静默回默认。
- **分享链接携带过期过滤**（对方项目无匹配 spec）→ 列表空态呈现「所见即所得」，可接受；不加参数有效性校验（无谓复杂度）。
- **存量书签/无参链接** → 行为与现状逐位一致，零回归。
- **交互行为无法静态断言**（grep 只能证代码在场，证不了「返回后恢复」）→ 验证走 web E2E 场景（浏览器操作：设过滤 → 进详情 → 返回 → 断言恢复）；本 SPEC spec.md 的 Scenario 均按 web 可验证口径编写。
