## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/tests/specInfoIcon.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 桌面表格信息图标

- [x] 1.1 状态列 render（`pages/projects/list.tsx` 状态列 Space 内、StatusWaitGroup 之后）增条件信息图标：`record.error` 非空时渲染 Popover（`trigger={['hover', 'click']}`）包裹的 `InfoCircleOutlined`（约 14px、`token.colorWarning`，紧随状态胶囊）；Popover 内容 = 完整 `record.error` 文本（`whiteSpace: 'pre-wrap'` 可换行不截断、maxWidth 限宽防超宽）+「清除」small 按钮（onClick `stopPropagation` 后调既有 `onClearError`，handler 本体与 `/api/spec-error-clear` 契约零改动）；`error` 为空/null 不渲染图标（无占位元素）。
- [x] 1.2 移除 `expandable` 的 `expandedRowRender` 与 `rowExpandable` 两键（保留 `columnWidth: 28` 与受控 `expandedRowKeys`/`onExpandedRowsChange`，树形展开零回归）；更新受控展开段（首次全展开/已见节点记忆/项目切换复位）与 `onRow` 守卫注释中指向已移除信息行的过时措辞（「error 信息行」表述收敛；闩锁代码本体与 `specRowClick.ts` 守卫不动）。

## 2. 移动端卡片

- [x] 2.1 移除 amber 软底信息行块（`spec-card-info-row`）；语义胶囊行状态 Pill 旁渲染与桌面同形态的信息图标（同 Popover：完整文本 + 清除；图标触发器与清除按钮 onClick `stopPropagation` 防触发行导航/卡片导航；外层点按目标不小于 32px，对齐 ⋮ 触控纪律）。

## 3. 测试与收尾

- [x] 3.1 新增 `tests/specInfoIcon.test.mjs`（node:test 零依赖习语，同 specRowClick.test.mjs）：源码扫描钉死——`expandedRowRender`/`rowExpandable` 不复现于列表表格、`spec-card-info-row` 信息行移除、Popover trigger 含 hover 与 click、`InfoCircleOutlined` 接线、清除按钮 stopPropagation + `onClearError` 复用（清除端点字符串不变）。
- [x] 3.2 前端测试套件全过（node --test 全绿）+ 生产 rebuild（`npm run build`，`dist/index.html` 锚点刷新）；本地起服务对桌面（有信息行：图标 + 悬浮弹层 + 清除后图标消失；无信息行：无图标；fix-\* 树形展开/收起正常；点图标不进详情；整行点击进详情）与移动端（卡片图标 + 点按弹层）截图取证存 `.history/`。
