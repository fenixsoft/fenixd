# Tasks: add-project-detail-tabs

## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SessionPanel.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/components/SessionModal.tsx
  kind: delete
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/`（前端构建产物，被 `.gitignore` 的 `dist/` 排除）
> 不入库，由框架在合并后自动重建，属 `reference` 非交付物；本变更只需保证
> `npm run build` 通过。

## 1. 会话面板组件（Modal → 内联）

- [ ] 1.1 新建 `core/dashboard/static/src/pages/projects/components/SessionPanel.tsx`：
  从 `SessionModal.tsx` 迁移全部会话逻辑（`getSession` 全量拉取、`EventSource('/api/stream')`
  hello 分支注册 watch、`seenUuidsRef` 去重、`handleStart` / `handleSend` / `handleStop`、
  `truncated` / `ended` / `error` 状态），**不改**任何会话行为契约
  - **迁移源禁令（MUST）**：以主树最新版 `SessionModal.tsx` 为基（当前 HEAD 版本），
    并逐项核对上游 `add-dashboard-live-session` 未合并 fix 分支
    `fenix/add-dashboard-live-session-1789738352`（commit `5f5d5846`）。该修复含两处
    本 SPEC MUST 保留的形态：
    (a) **`afterHello` 不得无条件注册 watch**——先 `getSession` 确认 `data.session`
    存在，仅有会话时才 `registerSessionWatch`，注册后再重拉一次；无会话直接设空态。
    （主树 HEAD 版本仍是「无条件注册 → 无会话项目 404 + `console.error`」的旧形态，
    照抄会复活 BUG-01，直接打破所有 web 场景的 `no_console_error` 断言；
    证据：`spec/changes/add-dashboard-live-session/verification-report.md:24-30`）
    (b) `cidRef` 初值必须为 `null`（挂载当帧不得预置自造 cid，否则发 `DELETE
    /api/session/watch` → 404，见 `SessionModal.tsx:55-60` 注释与 commit `bb2e73ce`）
- [ ] 1.2 `SessionPanel` props 定义为 `{ project: string; active: boolean }`（替换原
  `{ project; open; onClose }`）：`active` 表示「会话」分面是否被选中；
  原 `if (!open || !project) return;` 改为 `if (!active || !project) return;`，
  原 `!open` 清理 effect（注销 watch + 清空本地状态）改为对 `!active` 生效——
  切离分面即释放订阅且 MUST NOT 终止会话进程
- [ ] 1.3 渲染体去掉 `<Modal>` 外壳与标题行，改为内联容器：外层 `div` 用 flex 纵向布局，
  消息区 `flex:1` 可滚动，高度 MUST 同时给下界与上界（`minHeight` + `maxHeight`，
  或分面内显式定高）——**MUST NOT 只给 `minHeight` 不给上界**：`ClaudeMessageList`
  的自滚动容器是 `flex-1 overflow-y-auto`（`ClaudeMessageList.tsx:76`），Modal 形态
  靠 `body.height: 82vh`（`SessionModal.tsx:265`）提供确定高度，只给下界时长会话会把
  消息区拉穿、输入区被推出视口
  loading / error / 空态（「尚未接入会话」+「开始会话」按钮）/ 已启动（消息区 + 输入区）
  四个分支原样保留
- [ ] 1.4 会话进程未启动时不隐式启动：`active` 为 true 只做全量拉取与订阅，
  启动仍须用户点击「开始会话」（调 `startSession`）——保持既有语义
- [ ] 1.5 **终态文案改写（唯一允许改的既有文案）**：原
  「会话已结束，如需新会话请关闭后重新打开。」（`SessionModal.tsx:343`）引用 Modal 的
  「关闭 / 重新打开」，内联分面下这两个操作不存在，照抄即指向不存在的 UI。MUST 改写为
  分面语境文案（如「会话已结束。切离本分面再切回可开始新会话。」），且仍 MUST 是明确
  终态提示（输入区禁用），MUST NOT 静默无响应。其余文案（「尚未接入会话」「开始会话」
  「发送」「停止会话」「更早的消息已省略」等）MUST 逐字保留
- [ ] 1.6 **切离分面的状态清空**：`active` 由 true→false 时除注销 watch 外，MUST 清空
  本地面板状态（`sessionId` / `ended` / `sending` / `text`，按原 `!open` 分支逻辑）；
  `events` / `started` MUST 在切回分面重新执行 `loadAll()` 时被重置——MUST NOT 在分面内
  残留上一会话的消息或终态（会话可能已因空闲超时被回收，残留旧消息属误导）

## 2. 项目页三分面 Tabs（list.tsx）

- [ ] 2.1 `list.tsx` 新增 `const [activeTab, setActiveTab] = useState('dev')`（值域
  `'dev' | 'quality' | 'session'`，**不写入 URL**），并新增 `SessionPanel` 的 import、
  删除 `SessionModal` 的 import
- [ ] 2.2 在 `PageContainer` 正文区渲染 `<Tabs activeKey={activeTab}
  onChange={setActiveTab} items={tabItems} />`，`tabItems` 三项：
  `{ key: 'dev', label: '开发' }`、`{ key: 'quality', label: '质量' }`、
  `{ key: 'session', label: '会话' }`（顺序固定）
- [ ] 2.3 「开发」分面 children = 现有内容整体下沉：error `Alert` + 包裹搜索/筛选条与
  列表（`isMobile` 分支的 `SpecCardList` / `Table`）的 `<Card>`；该分面渲染与交互 MUST
  与改造前逐位一致（零回归）
- [ ] 2.4 「质量」分面 children = 空态占位：antd `Empty`（`description` 含「建设中」语义
  文案，如「质量视图建设中」）；MUST NOT 发起任何数据请求
- [ ] 2.5 「会话」分面 children = `<SessionPanel project={name} active={activeTab === 'session'} />`；
  MUST NOT 在未选中该分面时产生 `/api/session*` 请求或注册 SSE watch
- [ ] 2.6 移除标题栏右侧的「接入会话」按钮容器（原 `list.tsx` 中
  `<div style={{ marginLeft: 'auto', flexShrink: 0 }}>…</div>`），header title 恢复为
  左侧 `<Space>`（项目名 + `共 N 个 SPEC`）；若 `MessageOutlined` 无其它引用则一并
  移除其 import
- [ ] 2.7 移除页面底部的 `<SessionModal>` 挂载与 `sessionOpen` 状态；其余 Modal
  （`SpecDocModal` / `AdminInvokeModal` / 优先级 / 拾取时间 / `SpecStatusModal`）
  MUST 保持在 **Tabs 之外**的页面顶层，避免切换分面时被卸载

## 3. 删除旧 Modal 与引用清零

- [ ] 3.1 删除 `core/dashboard/static/src/pages/projects/components/SessionModal.tsx`
- [ ] 3.2 全局搜索确认 `SessionModal` 引用清零（`grep -rn "SessionModal"
  core/dashboard/static/src/` 仅剩 `.umi` 构建缓存命中时可忽略，源码零命中）

## 4. 构建与冒烟

- [ ] 4.1 在 `core/dashboard/static` 运行 `npm run build`（`max build`）成功，
  产物落 `dist/`，控制台无 error 级编译告警
- [ ] 4.2 验证产物含三分面文案：`grep -o "开发\|质量\|会话" dist/*.js | sort -u`
  命中三项（或按实际产物文件名等价断言）
- [ ] 4.3 静态自检（不依赖真实浏览器进程）：确认 `list.tsx` 中「接入会话」按钮文案
  已不存在、`SessionPanel` 已 import、`activeTab` 门控已接线
  （`grep -n "接入会话" list.tsx` 无命中）。注意：该断言**只作用于 `list.tsx`**，
  `SessionPanel.tsx` 中空态的「尚未接入会话」（`SessionModal.tsx:291`）MUST 保留，
  MUST NOT 为凑 grep 而改写

## 5. 合并顺序与跨 SPEC 交接（design「Depends On」）

- [ ] 5.1 确认 `add-dashboard-live-session` 的 fix 分支
  （`fenix/add-dashboard-live-session-1789738352`，commit `5f5d5846`）**已合入 main**
  后再合并本变更；未合入时 MUST NOT 合并（本变更改的是它的产物文件，且迁移源依赖其
  BUG-01 修复形态）
- [ ] 5.2 交接登记：把本变更对 `dashboard-live-session` 承载形态的改写（标题栏入口
  移除、Modal → 内联分面）记入 `add-dashboard-live-session` 的后续/回归轮待办，使该
  SPEC 的 5 条 Modal 形态 web 场景（`web-entry-button-visible` / `web-modal-title-project` /
  `web-open-modal-empty-state` / `web-reopen-modal-reconnect` / `web-stop-session`，
  见 `.fenix/verify-progress/add-dashboard-live-session/scenarios.json`）被**改道**为新形态
  断言或标 superseded，而非原样重跑
- [ ] 5.3 实现期若发现 `SessionModal.tsx` 与迁移基版本存在未预期差异（上游又有新 fix），
  MUST 逐段比对并逐项搬运，MUST NOT 以「删除+新建」覆盖未合并的修复
