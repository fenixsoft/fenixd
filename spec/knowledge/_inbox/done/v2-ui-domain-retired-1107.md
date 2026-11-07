# v2 商业化界面域整体退役（2026-11-07 用户指令「移除所有v2版本的页面，只保留原版」）

- pages/v2/ 目录（overview / projectDetail / specDetail / settings / help / ops 六页 +
  theme.tsx + v2.less + shared.tsx + AlertList.tsx）与 config/routes.ts 全部 /v2/* 路由
  已删除；原版页面恢复为唯一界面。存量 /v2/* 深链由 routes.ts 底部 '*' 兜底重定向回
  /overview（hash 路由，服务端仍 200 出壳、客户端路由跳转）。
- 随删除清理的死代码与死守卫：
  - `combineSpecSubtitle`（specTitle.ts，唯一消费方 v2/specDetail）删除，四分支测试同删；
  - tests/v2TitleBarGuard.test.mjs、tests/v2RoutesGuard.test.mjs（守卫对象已不存在）删除；
  - specTitleSubtitle.test.mjs 两节 v2 源码扫描测试删除；pageChrome.test.mjs 12px 圆角
    测试去 v2 theme/v2.less 直读（保留 .ov-bento 断言）。
- **镜像纪律注释已收口**：一般域五处「源 = pages/v2/theme.tsx 两处同改」同步指令
  （detail.tsx / list.tsx / ProjectTable.tsx / SpecTimeline.tsx / command-center/shared.ts）
  与 global.less 七处，已改为「色值取自当日的 v2 域 token 表——该域 2026-11-07 已退役，
  独立存量」历史注记；样式值全部保留不变。
- **知识层已同步退役（同日用户确认，无需再蒸馏折叠）**：dashboard-frontend 十个
  v2-* 能力页删除；v3-* 四页经用户确认去前缀改名（v3-spec-detail-page→spec-detail-page、
  v3-activities-page→activities-page、v3-settings-page→settings-page；v3-spec-doc-view
  与 spec-doc-view 为同一文档弹窗能力的两代分层，按「同能力只留最终态」并入
  spec-doc-view rev=3，空态文案按代码实况定稿「无此文档」）；unified-page-title-bar
  （rev=13）去 v2 六页条款、详情下方行收敛单页口径；dashboard-spec-table /
  spec-detail-bento-skin / quality-gates-progress / dashboard-overview /
  project-ledger-bounded-scroll / command-center-console-ui /
  mobile-regression-actions-stacking 七页「镜像 v2」现行口径改历史出处；ADR-327/328 退役翻状态待
  add-knowledge-anchor-lint-and-prune SPEC 执行（retired 状态词汇表扩展随 SPEC 落地，
  现校验器 _ADR_STATUS_RE 仅认 accepted|superseded）；_domain.md 与 index.md 导航层同步（能力数 54→43）。九月的
  dashboard-platform v2-shell 五页（amis 壳）此前已自带退役注记，未动；
  verify-pipeline/v2-devserver-lifecycle 为现役测试服务基建，未动。
- DESIGN.md：例外域 v2 节改退役墓碑（条款不再赘述，指 git 历史）；12px 圆角通用条款
  去 v2 单源指针（规则本身继续生效，实现单源收窄为 global.less）；Radio 黑底白字条款
  去副源标注。两个 SPEC 目录（redesign-dashboard-v2-ui / -mobile，均已带
  verification-report）留在 spec/changes/ 待走归档流程，未手工删除。
- 判别锚点：`core/v2_dev_server.py` 与 pages/v2 无关（worktree 测试服务基建，
  add-worktree-test-server 命名撞车），未动；docs/help 中 `stateDiagram-v2`（mermaid
  语法）与「契约版本 v2」（verify_contract 版本戳）均为同名无关物，未动。
- 验证口径：npm test 402 全绿；`max build` 成功；dist 无 v2 chunk；活站 8787 供新
  bundle（指纹比对 umi.317d3179.js 一致），浏览器 reload 一次生效（hash 路由纪律）。
