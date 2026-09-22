# Tasks: add-spec-list-filter-stickiness

## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/` 为前端构建产物（gitignored），由框架合并后
> 重建，属 `reference` 非交付物；本变更需保证 `npm run build` 通过。

## 1. 读侧：URL 参数解析与状态恢复（list.tsx）

- [ ] 1.1 从 `@umijs/max` 追加引入 `useSearchParams`（与既有 `history, useParams`
  同源），新增纯函数 `parseListFilters(searchParams)`：按 design D2 白名单解析
  `tab`/`q`/`status`/`type`/`archived` 五参——`tab` 仅接受
  `dev|quality|regression|session`，`status` 逐项过滤非法枚举（合法集与过滤下拉
  11 项同源），`type` 仅接受 `active|completed`，`archived` 仅 `1` 为真，`q` trim
  后空串视为无参；非法值一律静默回默认，返回 `{tab, q, statusList, type,
  archivedOnly}` 解析结果
- [ ] 1.2 用 `useState` 惰性初始化把解析结果灌入 5 项状态：`activeTab`/`type`/
  `archivedOnly`/`statusList` 直接取解析值；搜索词同时回填 `q`（输入框回显）与
  `debouncedQ`（立即过滤，MUST NOT 出现「先闪全量列表、300ms 后才过滤」的中间态）；
  解析只在挂载时执行一次，MUST NOT 在后续渲染中反复读 URL 覆盖用户操作
- [ ] 1.3 为 `parseListFilters` 补充纯函数单测（项目前端测试仅覆盖纯函数模块，
  现有测试基建照用）：覆盖合法全参、空参、非法 tab/type、status 混合合法与非法
  枚举、`archived=9`、`q` 全空白等分支

## 2. 写侧：状态变更同步 URL（list.tsx）

- [ ] 2.1 新增写回 effect：`debouncedQ`/`statusList`/`type`/`archivedOnly`/
  `activeTab` 任一变化时以 replace 语义写回 URL（`setSearchParams(params,
  { replace: true })`）；缺省值不写参（`tab=dev`、`q` 空、`statusList` 空、
  `type` 空、未归档均移除对应参数），默认视图下 URL 恢复无参干净形态；挂载后
  首跑对脏参数的清洗即 design D3 的「解析即消毒」，无需额外逻辑
- [ ] 2.2 搜索词落 URL 挂在既有防抖 effect 之后（跟随 `debouncedQ` 节拍），
  MUST NOT 逐字符写 URL；既有 300ms 防抖时长、过滤口径（`filtered` useMemo）、
  本地表空回退后端的逻辑 MUST 零改动
- [ ] 2.3 路由路径 MUST 保持 `/projects/:name`：写回仅更新查询串，MUST NOT
  触发 history push、整页刷新或组件重挂载（否则恢复逻辑自我失效）

## 3. 行为零回归与既有语义保持

- [ ] 3.1 页签恢复复用既有 `active` 门控：URL 带 `tab=quality|regression|session`
  打开时仅该分面发起自身数据拉取，未选中分面零请求；「会话」分面仍 MUST NOT
  隐式启动会话进程（未启动显示「开始会话」空态）——`QualityTab`/`RegressionTab`/
  `SessionPanel` 的 props 与内部逻辑 MUST 零改动
- [ ] 3.2 无参数打开 URL 的行为与改造前逐位一致：默认「开发」页签、全部状态、
  全部类型、未归档、搜索为空；表格分页页码与树形展开状态（`expandedKeys`）不持久
  化，维持现状
- [ ] 3.3 过滤条 UI（搜索框/状态多选/类型单选/归档切换）与移动端卡片、桌面表格
  分支的既有交互 MUST 零改动（本变更只动状态来源与同步，不动控件）

## 4. 构建与静态自检

- [ ] 4.1 在 `core/dashboard/static` 运行 `npm run build`（`max build`）成功，
  产物落 `dist/`，控制台无 error 级编译告警
- [ ] 4.2 静态自检：`list.tsx` 中 `useSearchParams` 已引入、`parseListFilters`
  已定义并在惰性初始化中调用、写回 effect 含 `{ replace: true }`、`Q` 参数经
  `debouncedQ` 而非 `q` 写回；新增单测在既有测试命令下通过
