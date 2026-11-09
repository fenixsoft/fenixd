# Proposal: move-project-nav-to-workspace-rows

## Why

dsh web 侧栏现有两条并列的项目导航：官方「工作区」列表（session-grouper 已把 fenix 项目根注册为工作区）与插件注入的「项目」菜单行+内嵌项目分区。两者信息重复、交互分叉（项目行 hover「新会话」、官方行另一套折叠/菜单操作），项目分区还常驻占用侧栏纵向空间。用户裁决（2026-11-09 立项原话，见 request.md）：取消「项目」入口与项目卡片，项目导航收敛进官方工作区列表——点项目名称直达该项目 SPEC 详情页，行首图标专职展开/收缩。

## What Changes

- **BREAKING（交互面退役）**：移除侧栏「项目」固定条目（`fenix-projects`）与内嵌项目分区全部形态（常驻内嵌、锚点漂移浮层降级、窄轨计数徽标、分区标题折叠拦截层）；`#panel=fenix-projects` 外层深链键退役（未注册 id 由既有 `deepLinkPanels` 语义静默吞，无异常）。
- **新增（名称导航分流）**：官方工作区列表中，fenixd 项目对应的工作区行获得「名称点击=打开项目详情」能力——主面板切换为该项目 iframe（`main` keyed 面板 `fenix-project-<name>`，src 深链 `#/projects/<encodeURIComponent(name)>`，契约不变），且不触发该行展开/收缩；行首图标（官方既有 hover folder→chevron 交换）点击维持原生展开/收缩。**非 fenix 工作区行零侵入**，整行点击维持现状。
- **新增（自动对齐）**：项目列表同步周期（60s）内，新项目自动经 `workspaces.create({path})` 注册为 dsh 工作区并出现在工作区列表（不自动开会话）；项目删除后其工作区行保留、名称点击不跳转（回退原生折叠行为）。
- **跨仓交付形态**：实现发生在 `/root/dsh-plugins` 仓 dashboard-bridge 插件（用户裁决落仓 fenixd）；fenixd 侧交付物=完整补丁镜像 `plugin-patch/`（基线快照→改后状态的 unified diff，可评审、守卫可对账），宿主主树直改+构建+部署+实拍验证沿用 `dsh-bridge-projects-section` 能力页既有部署链纪律。

## Capabilities

### New Capabilities

- `fenix-dash-bridge-workspace-nav`: dsh 侧栏「项目」入口退役后的工作区行项目导航能力——名称点击导航与图标折叠分流、新项目自动出现、非 fenix 行零侵入、删除项目回退、侧栏条目收敛。

### Modified Capabilities

（空——fenixd 仓无既有能力 spec 覆盖 dsh 面板桥侧栏面；已检索 `spec/changes/*/specs/` 与 `spec/archive/*/specs/` 无命中。dsh-plugins 仓的 `fenix-dash-bridge` 能力（bridge-projects-inline-section）属跨仓 spec 树，不在本仓 capability 全集内；其行为变化由本仓知识页 `dsh-bridge-projects-section` 于归档时回填更新。）

## Impact

- **跨仓实现面**：`/root/dsh-plugins/fenix-dsh-dashboard-bridge/src/client/{panels.tsx,index.ts,projectSync.ts}` 与 `tests/{srcContract.test.ts,projectSync.test.ts}`。宿主主树当前含未提交改动（2026-11-03 徽标改造已部署未提交，触及 panels.tsx/srcContract.test.ts）——补丁以「基线快照对比」生成，不得回退或混入既有未提交改动。
- **上游依赖（交互锚点）**：dsh-client-ui-workspace 官方 `ProjectRow` 结构——整行 `onClick=onToggle`、`data-row-key="workspace:<key>"`、子级 `slot.folder`/`slot.chevron`（hover CSS 交换为箭头）、`rowActions`（菜单/新会话按钮自带 stopPropagation）。插件名称导航拦截 MUST 基于语义锚点（`data-row-key` + 名称文本），MUST NOT 依赖 CSS module 哈希类名作唯一判据；上游升级致锚点漂移时名称导航静默失效（可接受降级，不产生未处理异常），原生行为不受影响。
- **部署与验证面**：`pnpm build`（tsdown）→ `systemctl restart dsh-web` → 新 token URL 重登 → playwright 命名会话（-s 隔离）实拍逐场景验证；vitest 全量绿（srcContract 钉值更新）。
- **本仓（fenixd）交付物**：`spec/changes/move-project-nav-to-workspace-rows/plugin-patch/` 补丁镜像；不触 fenixd 运行源码。
- **契约不变项**：`#/projects/<name>` iframe 深链、`#panel=fenix-project-<name>` 主 keyed 面板注册、`sidebar.workspaces` 槽位不抢占纪律、官方列表滚动条注入（既有 polish 维持）。
