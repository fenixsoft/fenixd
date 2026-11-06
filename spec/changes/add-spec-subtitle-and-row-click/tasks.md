## Deliverables

```yaml
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/specDetail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/tests/specTitleSubtitle.test.mjs
  kind: modify
- path: core/dashboard/static/tests/specRowClick.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 详情标题栏中文副标题

- [ ] 1.1 `services/dashboard.ts` 的 `SpecDetail` 接口补 `title?: string | null`（注释标注 id/name 关系与详情 API 透传来源）。
- [ ] 1.2 v1 `pages/projects/detail.tsx`：PageTitleBar 增声明 `subtitle`（详情响应 `title`，null/空不声明；移动端隐藏由 SubtitleNode 既有 `!isMobile` 规则承担，零改动）。
- [ ] 1.3 v2 `pages/v2/specDetail.tsx`：subtitle 组合渲染「中文标题 · branch」（branch 空只显中文标题、title 空维持现状 branch 单独显示、双空不渲染）。

## 2. v1 列表整行点击进详情

- [ ] 2.1 `pages/projects/list.tsx` 的 `onRow` 增整行 onClick 导航（镜像 overview ProjectTable 范式：`history.push` + 整行 cursor pointer）；事件目标判定守卫——展开钮（`.ant-table-row-expand-icon`）与操作列交互控件命中不导航；既有选中行底色 style 逻辑不变。
- [ ] 2.2 行内既有交互零回归自检：fix-* 展开/收起、error 信息行展开与清除、操作列 ⋯ 菜单、名称链接、Why 悬浮提示行为与改动前一致。

## 3. 测试与收尾

- [ ] 3.1 扩展 `tests/specTitleSubtitle.test.mjs`：钉死 v1 详情 subtitle 渲染（有 title / 无 title）与 v2 组合形态（title+branch / 仅 branch / 仅 title / 双空）。
- [ ] 3.2 新增 `tests/specRowClick.test.mjs`：钉死整行点击导航与四类守卫（展开钮/操作列/展开行内容/名称链接不双跳）。
- [ ] 3.3 前端测试套件全过 + 生产 rebuild（`dist/index.html` 锚点刷新）；本地起服务对 v1 详情标题栏（有/无 title）与列表整行点击截图取证 `.history/`。
