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
- [ ] 1.2 `SessionPanel` props 定义为 `{ project: string; active: boolean }`（替换原
  `{ project; open; onClose }`）：`active` 表示「会话」分面是否被选中；
  原 `if (!open || !project) return;` 改为 `if (!active || !project) return;`，
  原 `!open` 清理 effect（注销 watch + 清空本地状态）改为对 `!active` 生效——
  切离分面即释放订阅且 MUST NOT 终止会话进程
- [ ] 1.3 渲染体去掉 `<Modal>` 外壳与标题行，改为内联容器：外层 `div` 用 flex 纵向布局，
  消息区 `flex:1` 可滚动，高度用 `minHeight`（如 `minHeight: 420`）而非固定 `100vh`；
  loading / error / 空态（「尚未接入会话」+「开始会话」按钮）/ 已启动（消息区 + 输入区）
  四个分支原样保留，文案不删改
- [ ] 1.4 会话进程未启动时不隐式启动：`active` 为 true 只做全量拉取与订阅，
  启动仍须用户点击「开始会话」（调 `startSession`）——保持既有语义

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
  （`grep -n "接入会话" list.tsx` 无命中）
