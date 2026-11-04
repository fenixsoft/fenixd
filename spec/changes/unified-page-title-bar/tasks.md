## Deliverables

```yaml
- path: core/dashboard/static/src/components/PageTitleBar.tsx
  kind: new
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/global.less
  kind: modify
- path: core/dashboard/static/src/pages/overview/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/help/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/chain/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/command-center/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/command-center/shared.ts
  kind: modify
- path: core/dashboard/static/src/utils/pageChrome.ts
  kind: modify
- path: core/dashboard/static/tests/commandCenter.test.mjs
  kind: modify
- path: core/dashboard/static/tests/pageTitleBar.test.mjs
  kind: new
- path: core/dashboard/static/tests/embedMount.test.mjs
  kind: modify
- path: core/dashboard/static/tests/pageChrome.test.mjs
  kind: modify
- path: core/dashboard/static/tests/helpPageScroll.test.mjs
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 统一标题栏控件与顶栏插槽

- [ ] 1.1 新建 `src/components/PageTitleBar.tsx`：四槽位 props（title ReactNode / subtitle / back / filters），壳位判定（`isEmbedMode() || 视口 <768` → 内容区首行 48px 行壳位；否则顶栏壳位）收敛在组件内，行壳位与顶栏壳位排布同构；形态逐项对照 `spec/changes/unified-page-title-bar/specs/unified-page-title-bar/prototype/`（standalone.html / embed.html；标题 18px/700、副标题 12px 三级灰基线随迁、计数 tabular-nums、过滤项 28px small 档、行壳位底缘 DSH_SPLIT 细线、主题只取 theme.ts 单源）
- [ ] 1.2 `src/app.tsx` 顶栏插槽改造：声明-注册-插槽桥接（context / `usePageTitleBar(meta)` 等价单源，注册随页面卸载清理、无注册渲染空、路由切换无上一页残留）；品牌区（HeaderTitle）之后追加标题区渲染（ProLayout header 插槽属性按实际 API 就地选型），过滤项渲染进 `actionsRender` 槽位；`HeaderCrumb` 组件、`crumbItems` 映射、`global-header-crumb` 样式锚点及 `global.less` 窄屏面包屑隐藏规则一并退役清理
- [ ] 1.3 新增 `tests/pageTitleBar.test.mjs`：壳位判定分支、注册/卸载清理、无注册渲染空、路由切换无残留四类守卫

## 2. 页面迁移与过滤收编（8 页）

- [ ] 2.1 概览 / 运维 / 帮助三页摘除 PageContainer 页头并声明控件：概览（副标题「监控 N 个项目」动态随迁）、运维（副标题「跨项目 Administrator 活动」）、帮助（无副标题无过滤）；`HELP_FRAME_OFFSET` 回校（standalone=顶栏 56；embed=标题行 48）并保注释口径链
- [ ] 2.2 设置 / 处置链两页摘除页头：settings「作用域：」标签 + Select 迁 filters 槽位；chain「全部项目」Select 迁 filters；`SETTINGS_FRAME_OFFSET` 回校（同 2.1 口径）并保注释口径链
- [ ] 2.3 项目列表 / SPEC 详情两页摘除页头：列表页返回箭头 + 「fenixd + 共 N 个 SPEC」整体迁 title 槽位（onBack 行为不变）；详情页返回箭头 + SPEC 名 + 模式/状态 Tag + 快速切换下拉作为富标题 ReactNode 整体迁入（快速切换下拉保持在 SPEC 名旁、切换行为不变，wrap 语义在行壳位内成立）
- [ ] 2.4 指挥中心摘除页头：Tabs `tabBarExtraContent` 的项目 + 时间窗双 Select 迁 filters 槽位（时间窗仅 org 屏显隐逻辑随迁），页签行 extra 区移除；`SCREEN_CHROME_OFFSET` 族（shared.ts 及各屏定高容器）按页头消失重算；同步更新 `tests/commandCenter.test.mjs` 定高单源断言（现钉死 `SCREEN_CHROME_OFFSET === 182`）为新口径
- [ ] 2.5 `src/utils/pageChrome.ts` 页框口径回校（PageContainer 页头占位移除），注释与新口径互指；grep 复核 8 常规页文件无残留 `PageContainer header=` 配置与 `header.extra` / `tabBarExtraContent` 过滤残留（`PagePlaceholder` 兜底占位页与脱壳大屏按 spec 豁免条款不在此列）

## 3. 测试更新与双形态实拍验证

- [ ] 3.1 更新 `tests/embedMount.test.mjs`（embed=1 断言改为统一标题行内嵌：行壳位承载标题/副标题/过滤项）、`tests/pageChrome.test.mjs` 与 `tests/helpPageScroll.test.mjs`（新偏移口径守卫：standalone 顶栏 56 / embed 行 48）
- [ ] 3.2 前端全量测试通过（`node --test tests/*.test.mjs`）+ 生产 rebuild；playwright 命名会话实拍验证（整页 reload 后取证）：standalone + `?embed=1` 两形态逐页对照 specs/unified-page-title-bar/prototype/，含 390px 移动端壳位降级（顶栏纯品牌、行壳位 wrap 不溢出）与 1440×900 定高页（settings/help）无第二滚动条；截图留 `.history/`
