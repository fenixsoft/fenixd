# Tasks: redesign-dashboard-v2-ui

## Deliverables

```yaml
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/pages/v2/theme.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/overview.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/projectDetail.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/specDetail.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/settings.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/help.tsx
  kind: new
- path: core/dashboard/static/src/pages/v2/ops.tsx
  kind: new
- path: DESIGN.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 骨架与主题单源

- [ ] 1.1 新建 `src/pages/v2/theme.tsx`：Bento token 常量（页底/磁贴圆角阴影/黑主色/蓝链接/语义色/胶囊/阶段 ramp）+ v2ConfigProvider 组件（局部 ConfigProvider 包裹），零 import 现产 theme.ts 色值
- [ ] 1.2 `config/routes.ts` 追加 `/v2/*` 路由族（overview、projects/:name、projects/:name/:spec、settings、help、activities），既有条目逐字不动；v2 条目不写 name/icon，`app.tsx` menuDataRender 白名单零新增；新增 routes 快照守卫测试钉住既有条目与 menuDataRender 菜单逐字不变

## 2. 六页面实现（UI 真相源 = prototype/，实现前必读）

- [x] 2.1 新建 `src/pages/v2/overview.tsx` 实现 `/v2/overview`（prototype/variant-b-bento.html）：4 卡等宽 KPI（任务进度圆环/Token 静态 SVG 面积图/Agent 堆叠条）+ 告警横幅（多行明细+裁决选择题）+ 项目台账表格（fixed 布局/首列 14px/长注释换行）；消费 /api/overview 与 /api/alerts 真实数据
- [ ] 2.2 新建 `src/pages/v2/projectDetail.tsx` 实现 `/v2/projects/:name`（prototype/project-detail.html）：标题带 + 四页签（功能开发/代码审查/测试回归/会话接入，后三页签可先占位说明）；SPEC 表格真实列集（状态/模式/名称/优先级/创建时间/任务进度/验证/耗时/操作·仅三点）；消费 /api/specs 真实数据
- [ ] 2.3 新建 `src/pages/v2/specDetail.tsx` 实现 `/v2/projects/:name/:spec`（prototype/spec-detail.html）：标题带（模式/状态徽标+状态转移下拉）+ 项目信息 8 项 + 任务清单（大百分比+勾选任务）+ 五页签（时间轴含 run 元数据/场景结果/Bug/截图/Hook）；缺口字段显示「—」不伪装 0
- [ ] 2.4 新建 `src/pages/v2/settings.tsx` 实现 `/v2/settings`（prototype/settings.html）：左侧菜单 + 作用域切换 + LLM Provider 表格面板与开关行；消费既有配置端点
- [ ] 2.5 新建 `src/pages/v2/help.tsx` 实现 `/v2/help`（prototype/help.html）：分组目录 sticky + Markdown 正文双栏（复用 markdown-shared 渲染链）
- [ ] 2.6 新建 `src/pages/v2/ops.tsx` 实现 `/v2/activities`（prototype/ops.html）：头部统计条 + 三页签（人工告警含裁决选择题/处置链观测/自愈记录）；消费 /api/alerts 等既有端点

## 3. DESIGN.md 修正案

- [ ] 3.1 按 design.md「偏离声明」表在 DESIGN.md 例外域章节新增「例外域：v2 商业化界面域」小节（用途声明 + 域专属 token 表 + 偏离清单，出处标注本 SPEC 与 prototype/ 路径），既有条款文本零改动

## 4. 构建与验证

- [ ] 4.1 `npm run build` 通过；全部 v2 路由可达（#/v2/overview 等六页渲染冒烟）
- [ ] 4.2 既有页面回归断言：routes 快照守卫通过、`src/pages/` 既有页面组件文件零 diff、`#/overview` 等既有路由渲染不变
