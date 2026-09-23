## Context

项目页 `core/dashboard/static/src/pages/projects/list.tsx` 当前是单一页面结构：`PageContainer` 的 header 标题栏左侧是「项目名 · 共 N 个 SPEC」，右侧是「接入会话」按钮（`dashboard-live-session` D7 引入）；正文是一张 SPEC 列表卡片（搜索/筛选条 + 桌面 `Table` / 移动端 `SpecCardList`），页面底部挂若干 Modal（文档、Admin 介入、优先级、拾取时间、状态、以及会话 Modal）。

需求：把项目页改成三分面 Tabs（开发 / 质量 / 会话），会话界面从 Modal 迁到「会话」分面内联呈现，「质量」暂空。

约束：
- 会话后端（`session_manager`、`/api/session/*`、SSE 事件契约）不动，本变更是纯前端改造。
- 前端构建产物 `core/dashboard/static/dist/` 不入库，验证靠「建 dist + 起 dashboard + 浏览器 E2E」。
- 项目历史同源改动（`add-dashboard-live-session`）走 full 模式；本变更影响面小（单页 + 一个组件迁移），按用户确认走 fast-track。

## Goals / Non-Goals

**Goals**
- 项目名称下方引入 `Tabs`，三分面「开发」「质量」「会话」，默认「开发」。
- 会话界面由全屏 Modal 改为「会话」分面内联面板，交互语义（手动开始、复用、发送、终止提示）不变。
- 移除标题栏「接入会话」按钮。
- 「开发」分面 = 现有 SPEC 列表，零回归。

**Non-Goals**
- 不实现「质量」分面内容（仅空态）。
- 不新增会话功能，不改会话后端/契约。
- 不做 Tab 状态持久化 / 深链接。
- 不改 `detail.tsx`（单个 SPEC 详情页）——本变更是项目层级页面。

## Decisions

### D1：Tabs 位置与形态

用 antd `Tabs`（`items` 形态，与 `detail.tsx:1763` 的既有用法一致；`settings/index.tsx` 用的是 `Menu` 而非 `Tabs`，不属同类用法），放在 `PageContainer` 的正文区、**项目名称（header）下方**。

- header 保持现有左侧 `Space`（项目名 + 计数），**移除**右侧会话按钮容器（D4）。
- 正文区结构改为：`<Tabs items={tabItems} />`，其中「开发」分面的 children 即现有 `<Card>` 包裹的搜索/筛选条 + 列表（含 error Alert）。
- 选中态：`const [activeTab, setActiveTab] = useState('dev')`，**不写入 URL**（用户确认不持久化）。刷新回默认「开发」。
- 移动端：`Tabs` 本身在两种视口都渲染；「开发」分面内部的 `isMobile` 分支（卡片 vs 表格）保持不变。

**为什么用 antd Tabs 而非 ProLayout 的页签/Menu**：项目页是单路由页面，Tabs 是「同一页面内的内容分面」，语义正确且改动最小；Menu 更适合多路由导航（settings 页用 Menu 是因为其分面独立成块、且要横向滚动，项目页无此需求）。

### D2：会话界面组件迁移（Modal → Panel）

`SessionModal.tsx` 内部逻辑（拉全量、SSE 注册 watch、uuid 去重、开始/发送/停止、终态）**整体保留**，仅把最外层 `<Modal>` 外壳换成内联容器。

- 新建 `components/SessionPanel.tsx`：props 由 `{ project, open, onClose }` 改为 `{ project, active }`（`active` = 该分面是否被选中）。
- 原 `useEffect(..., [open, project])` 的挂载条件由 `if (!open || !project) return;` 改为 `if (!active || !project) return;`——「打开 Modal」等价于「分面被选中」。原 `!open` 分支里注销 watch + 清空本地状态的 `useEffect` 逻辑改为对 `!active` 生效，从而**切离分面即释放订阅**（满足 `project-page-tabs` 的「切离分面释放订阅」Requirement，且不终止进程）。
- 渲染体：去掉 `Modal`、去掉 `title` 里的「接入会话」标题行；内容区高度改为占满分面（如 `height: calc(100vh - 320px)` 或 `minHeight` + flex），其余渲染分支（loading / error / 空态开始 / 消息区 + 输入区）原样搬入。
- 空态、发送/停止按钮等文案不变。**唯一必须改写的文案是终态提示行**：原文案
  「会话已结束，如需新会话请关闭后重新打开。」（`SessionModal.tsx:343`）引用的是
  Modal 的「关闭 / 重新打开」操作，迁到内联分面后这两个操作都不复存在，照抄即
  指向不存在的 UI。MUST 改写为分面语境（例如「会话已结束。切离本分面再切回可
  开始新会话。」），且仍 MUST 是明确的终态提示，MUST NOT 静默无响应。
- 切离分面（`active` 由 true→false）时按原 `!open` 分支的逻辑清空本地状态
  （`sessionId` / `ended` / `sending` / `text`）；`events` 与 `started` 由切回分面时
  重新执行 `loadAll()` 重置——MUST NOT 在分面内残留上一会话的消息或终态。

**为什么新建 SessionPanel 而非原地改造 SessionModal**：Modal 外壳与内联面板的挂载/卸载语义不同（`open` 是受控显隐、`active` 是条件挂载），拆成新组件语义更清晰；`SessionModal` 随后删除，避免「同名却是 Panel」的误导。

### D3：会话分面的惰性激活

「会话」分面的会话请求/订阅只在**该分面被选中**时发生。实现方式二选一：

- **方案 A（选用）**：`SessionPanel` 始终挂载在 Tab `items` 里，但 `active` 为 false 时其 effect 直接 return，不拉取、不订阅；为 true 时才启动。这样组件常驻（保留 React 状态），切回时复用。
- **方案 B**：`Tabs` 的 `destroyInactiveTabPane` 语义——非选中分面的 children 不渲染。antd 新版 `Tabs` 默认即惰性渲染（首次不渲染未激活 pane），但切走是否销毁取决于 `destroyOnHidden`。

**选 A 的理由**：符合 Requirement「未被选中时 MUST NOT 发起请求/订阅」，且避免依赖 antd 版本的 `destroyOnHidden` 行为差异（项目 antd 版本固定，但语义显式化更稳）。会话状态（events 缓冲）在切离后按原 `!open` 逻辑清空、重开重新接回，与既有 Modal 重开语义一致。

**实测补充（本仓库 antd 6.6.2，`core/dashboard/static/package.json` 锁定 `^6.6.0`）**：antd `Tabs` 的 pane 默认**惰性渲染**（首次不渲染未激活 pane），且 `destroyOnHidden` 缺省为 `false`（`node_modules/antd/es/tabs/index.js:157`，非选中 pane 挂载后不销毁）。因此方案 A 不需要 `forceRender`——「会话」pane 在首次切入时挂载、`active` 初值即为 `true`，effect 正常激活；切离时不销毁、`active` 转 `false` 触发清理并释放订阅。实现 MUST NOT 使用 `destroyInactiveTabPane`（antd 6 已废弃，会告警）。

### D4：移除标题栏按钮

删除 `list.tsx` 中 header title 右侧的会话按钮 `<div style={{marginLeft:'auto'}}>...`，以及 `sessionOpen` 状态与页面底部的 `<SessionModal>` 挂载；`MessageOutlined` 图标 import 若无其它用途则一并移除。header title 简化为原来的 `<Space>`。

### D5：删除 SessionModal

`SessionModal.tsx` 的内容迁入 `SessionPanel.tsx` 后删除该文件（`kind: delete`）。删除前确认无其它引用（当前唯一引用点在 `list.tsx`）。

### D6：验证方式

前端无组件级单测框架（现有 `tests/*.test.mjs` 仅覆盖纯函数模块）。本变更的验证走**浏览器 E2E**（与 `add-dashboard-live-session` 同路）：建 dist → 起 dashboard → 打开项目页断言三分面、切分面、会话面板呈现、标题栏无按钮。验证契约由出题阶段生成（`verify.yaml`），本设计只约束实现侧交付物。

## Risks / Trade-offs

- [会话分面惰性激活若实现成「始终拉取」，会在项目页首屏产生无谓的 `/api/session` 请求 + SSE watch 注册] → Requirement 已明确「未选中不订阅」，D3 显式用 `active` 门控；E2E 场景覆盖「停留在开发分面时无会话订阅」。
- [无会话项目切入「会话」分面必然产生 404 + console.error，污染 `no_console_error` 断言] → 这是 `add-dashboard-live-session` **已实证过**的缺陷（`spec/changes/add-dashboard-live-session/verification-report.md:24-30`，BUG-01：`afterHello` 在 SSE hello 分支无条件 `registerSessionWatch` → 服务端 `session_routes.py:163-166` 判无会话返回 404 → 前端 `console.error`）。迁移 SessionPanel 时 MUST 保留其修复形态（**先 `getSession` 确认会话存在，仅有会话时才注册 watch**），MUST NOT 迁回无条件注册的旧形态。
- [SessionPanel 高度用 `100vh` 计算，移动端可能溢出] → 用 `minHeight` + flex 而非固定 `100vh`，或按 `isMobile` 给不同高度；E2E 在桌面视口验证，移动端沿用既有 `useIsMobile` 分支。
- [消息流无界增高] → `ClaudeMessageList` 的自滚动容器是 `flex-1 overflow-y-auto`，**必须有确定高度的 flex 父链**才不失效（`ClaudeMessageList.tsx:76`）。Modal 形态靠 `body.height: 82vh` 提供（`SessionModal.tsx:265`），内联分面须改用 `maxHeight`（或分面内显式定高）提供；只给 `minHeight: 420` 而无上界时，长会话会把消息区拉穿、输入区被推到视口外。
- [删除 SessionModal 后遗留 import / 死代码导致构建告警] → 任务含「全局搜索 SessionModal 引用清零」与「`npm run build` 通过」。
- [「开发」分面下沉到 Tabs children 后，原有 Modal 挂载点（文档/Admin/…）若一并移入 children，切换分面会卸载它们] → 保持这些 Modal 挂在页面顶层（Tabs 之外），只有会话面板进「会话」分面内。

## Migration Plan

1. 新建 `SessionPanel.tsx`（从 SessionModal 迁移逻辑；**以主树最新版 `SessionModal.tsx`（含 BUG-01 修复）为迁移源**——`add-dashboard-live-session` 的修复分支 `fenix/add-dashboard-live-session-1789738352`（5f5d5846）尚未合入 main，主树文件里 `afterHello` 仍是无条件注册 watch 的旧形态，照抄即引入同一 404 缺陷）。
2. 改 `list.tsx`：引入 Tabs、会话面板入「会话」分面、移除标题栏按钮与 SessionModal 挂载与 `sessionOpen`。
3. 删除 `SessionModal.tsx`，清引用。
4. 构建 dist 并冒烟（三 Tab 渲染、切换、会话空态）。
5. 回滚：恢复 `list.tsx` + 重新引入 SessionModal 即可；会话后端无状态变更，无数据迁移。

## Depends On

本变更的交付物 `core/dashboard/static/src/pages/projects/list.tsx` + `components/` 与
`add-dashboard-live-session` **同文件**，且其修改的是该 SPEC 尚未合并的产物
（本项目 `git worktree list` 实测：`fenix/add-dashboard-live-session-1789738352`
 → `.claude/worktrees/impl-add-dashboard-live-session-1789738352` 仍活跃；
`git merge-base --is-ancestor 5f5d5846 HEAD` 为假，即其验证轮修复尚未入 main）。

- **合并顺序**：本变更 MUST 在 `add-dashboard-live-session` 合入 main 之后再合并
  （先删后改会让该 SPEC 的 fix 分支语义悬空）。SCHED 侧应以 `depends_on:
  add-dashboard-live-session` 串行（`depends_on` 的登记面在 `STATE.md` 条目，非本
  SPEC 文档——启动依赖由框架级操作者按本条结论登记）。
- **冲突消解（实现期强制）**：不得依赖「同锚点文本合并」自动成功。本 SPEC 的
  「迁移会话逻辑」若在 `SessionModal.tsx` 已被上游改动（BUG-01 修复：`afterHello`
  改为先 `getSession` 判存在再注册 watch、并在注册后重拉一次；另见 commit bb2e73ce
  的挂载帧 404 修复）之后才执行，则 MUST 逐段比对上游版本、逐项搬运，MUST NOT
  用「文件删除 + 新建」一气呵成地覆盖掉未合并的修复。
- **验证面同步**：`add-dashboard-live-session` 的冻结场景集
  （`.fenix/verify-progress/add-dashboard-live-session/scenarios.json`）含 5 条按
  Modal 形态与标题栏入口设计的 web 场景——`web-entry-button-visible`、
  `web-modal-title-project`、`web-open-modal-empty-state`、`web-reopen-modal-reconnect`、
  `web-stop-session`（以及 `web-start-session`）。本变更删掉按钮与 Modal 后：
  - 若这些场景在本变更合并前已归档（随 `add-dashboard-live-session` 入库），则新
    SPEC 的回归轮 MUST 对它们做**改道处理**（按本 SPEC 的 `dashboard-live-session`
    delta 重写断言或标为 superseded），MUST NOT 原样重跑（否则必然红）。
  - 若本变更先合并，则该 SPEC 的验证轮会打到无按钮无 Modal 的新形态——故上述
    合并顺序 MUST 优先保证。

## Open Questions

无（交互形态已与用户确认：内联面板、移除顶部按钮、质量空态 Empty、Tab 不持久化、手动开始会话）。
