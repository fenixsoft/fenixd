# Tasks: redesign-dashboard-v2-ui-mobile

## Deliverables

```yaml
- path: core/dashboard/static/src/pages/v2/theme.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/overview.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/projectDetail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/specDetail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/settings.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/help.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/ops.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 断点基建

- [x] 1.1 theme.tsx 增量：移动断点 token（<768）与形态判定 hook 复用（useIsMobile），六页统一消费，断点 token 与 hooks/useIsMobile.ts 现产阈值 767.98 两轨同界（CSS 媒体查询与 JS 判定对齐，见知识 mobile-breakpoint-unification），MUST NOT 散落断点魔法数

## 2. 六页移动形态（UI 真相源 = prototype/m-*.html，实现前必读）

- [x] 2.1 扩展既有 `src/pages/v2/overview.tsx` 移动分支：KPI 2×2、告警摘要+双按钮、项目卡流（prototype/m-overview.html）
- [x] 2.2 扩展既有 `src/pages/v2/projectDetail.tsx` 移动分支：筛选双下拉、SPEC 卡片流、无新建按钮（prototype/m-project-detail.html）
- [x] 2.3 扩展既有 `src/pages/v2/specDetail.tsx` 移动分支：标题收纳、无状态转移按钮、项目信息单列、页签短标签（prototype/m-spec-detail.html）
- [x] 2.4 扩展既有 `src/pages/v2/settings.tsx` 移动分支：横向滑动胶囊菜单、Provider 堆叠卡（prototype/m-settings.html）
- [x] 2.5 扩展既有 `src/pages/v2/help.tsx` 移动分支：目录 Drawer、无搜索、正文单列（prototype/m-help.html）
- [x] 2.6 扩展既有 `src/pages/v2/ops.tsx` 移动分支：统计 chips、告警堆叠卡含全宽裁决 Select（prototype/m-ops.html）

## 3. 验证

- [x] 3.1 390px 视口六页渲染冒烟：无横向越界、长文本换行完整、断点两形态切换互不污染
- [x] 3.2 桌面形态零回归：≥768px 六页对照 redesign-dashboard-v2-ui prototype/ 不变
