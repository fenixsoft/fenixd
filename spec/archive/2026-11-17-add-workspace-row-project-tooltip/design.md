## Context

dsh web 侧栏工作区行的项目名称导航由跨仓插件 `/root/dsh-plugins/fenix-dsh-dashboard-bridge` 的 `src/client/panels.tsx` `installWorkspaceNav(ctx, deps)` 实现：语义锚点拦截层（`span.projectText > span.title` 内透明覆盖层，`data-fenix-wsnav` 属性）承接点击进项目详情深链；`src/client/projectSync.ts` 每 60s 拉取 `GET <prefix>/api/projects`，当前仅解析项目名清单（`parseProjectNames`）。该端点（fenixd `core/dashboard/routes/project_routes.py` `_api_projects`）实际返回全量 ProjectSummary（`name/path/daemon/hosting/spec_count/status_counts/task_done/task_total/problems/active_runs/description/exists/discovered/...`，见 `core/dashboard/static/src/services/dashboard.ts:11`），信息被丢弃了。

dsh 原生 tooltip 实测规格（2026-11-10，活站提取）：深卡底 `#2C2C2E`、圆角 16px、内距 12px 16px、阴影 `rgba(0,0,0,.2) 0 0 1px 0, rgba(0,0,0,.02) 0 0 4px 0, rgba(0,0,0,.08) 0 12px 32px 0`、标题 `#fff` 14px/20px、次文本 `#cfd3d6` 12px/16px、无箭头、delayMs 500、portal 渲染、出现于行右侧。状态胶囊 tone 与状态映射取自概览台账单源：`STATUS_META`（dashboard.ts:1781）+ `OV_TONE`（ProjectTable.tsx:38）。

用户已批准确稿原型（方案B 暗面胶囊，2026-11-10）：`.history` 迭代环产物入库于 `prototype/`，深卡 + 状态胶囊取 tone 同相暗面派生色（文字亮化、底 16%~22% 透明）。

**设计约束以 DESIGN.md 为准**（界面设计宪法）：本变更不触及 dashboard 页面域，样式对象是 dsh web 宿主侧栏内的插件浮层——宪法偏离声明见 D4。

## Goals / Non-Goals

**Goals**

- fenix 项目工作区行名称悬停显示富提示（简介一行/运行态/状态胶囊/任务/活跃 Agent），方案B 原型定稿样式。
- 非 fenix 行与失效数据行回退原生提示，零侵入不回归。
- 点击导航行为与既有锚点降级纪律不变；fenixd 后端零改动。
- 跨仓交付照 ADR-339：宿主直改 + 本仓补丁镜像可评审可对账。

**Non-Goals**

- 不改 dsh 原生 tooltip primitive（label/side/align 机制）——富提示为插件自渲染浮层（原生 primitive 仅支持纯文本 label，承载不了胶囊组）。
- 不改 `/api/projects` 端点与 fenixd 后端；不动概览台账。
- 不做 tooltip 内可点击元素（纯展示）；不动移动端布局。

## Decisions

**D1 数据面——projectSync 保留精简投影**：`parseProjectNames` 升级为解析 ProjectSummary 投影 `{name, path, description, daemon, hosting, exists, discovered, status_counts, task_done, task_total, active_runs}`，60s 周期与容错纪律不变（单项目失败项 exists:false/error → 该行走原生回退）。不存全量对象（problems/scenario_count/updated 等本能力不需要，投影面收敛内存与泄漏面）。

**D2 渲染面——插件自渲染深卡浮层**：新建 tooltip 渲染（可落 `src/client/wsTooltip.ts`，实现者可按契约自行拆分），portal 挂 `document.body`，定位锚定拦截层 rect 右侧（对齐原生 card 相对行右缘浮出），复用原生实测规格值（D2 规格见 Context）。hover 目标 = 既有 `data-fenix-wsnav` 拦截层（与点击同一语义锚，天然只覆盖 fenix 行名称区，非 fenix 行自动零侵入）。show/hide 纯 display 切换，零动画；`mouseenter/mouseleave` + 500ms 定时器（对齐原生 delayMs），滚转/失焦/行卸载即收。富提示与原生三行提示互斥：既有拦截层不抑制原生提示（proposal 亦实测记录 fenix 行悬停原生提示照常触发），富提示激活期间须以插件侧手段消解原生提示（拦截层 pointer 事件吞噬或原生提示层悬停期隐藏，不改原生 primitive）；宿主机制致无法消解时按静默降级纪律 warn-only，不做破坏性兜底。

**D3 状态胶囊真值单源**：状态→tone 映射与暗面派生色按原型定稿表硬编码于插件侧常量（并加 srcContract 钉值防漂移）：drafted=草稿 muted / ready=就绪 info / reviewing=评审中 aqua / implementing=实现中 warning / implemented=已实现 aqua / testing=验证中 info / verified=已验证 good / bug-found=有Bug critical / blocked=阻塞 critical / done=完成 good / pushed=已推送 good；repairing=修复中 info / queued=排队中 warning（阻塞分相）。派生色：info #7aa2ff / warning #f0ac54 / critical #ff8080 / good #5fce8f / aqua #45c1dc / muted #a9b4c0，底=同相 rgba 16%~22%。

**D4 DESIGN.md 对照结论与偏离声明**：宪法管辖 dashboard 页面域（浅色面、Bento 12px、胶囊软底浅色 token）；本浮层视觉采用 dsh web 宿主原生 tooltip 深卡语言（`#2C2C2E`/16px 圆角/暗面派生胶囊），非宪法 token 表值。

- **偏离条目**：浮层样式不取宪法 token（深色卡面、16px 圆角、暗面同相胶囊底），改用 dsh 原生 tooltip 实测规格 + 方案B 派生色。
- **理由**：组件寄居于 dsh web 宿主侧栏，须与宿主原生 tooltip 视觉连续（深卡是宿主既有语言）；暗面胶囊派生色为用户 2026-11-10 批注定稿（「胶囊风格采用方案B，定稿立项」）。
- **适用范围**：仅本 SPEC 的 dsh web 侧栏富提示浮层（含其状态胶囊）；不外溢至 dashboard 任何页面、不改动宪法 token 表。

**D5 跨仓交付形态（框架惯例偏离声明，照 move-project-nav-to-workspace-rows 先例）**：

- **偏离条目**：交付物不落本仓 merge-back 常规形态——实现面在 `/root/dsh-plugins` 宿主主树直改，本仓仅落补丁镜像（`kind: new` 硬校验）+ dsh-plugins 路径声明 `reference`（仅审计）。
- **理由**：fenixd daemon 无跨仓派发机制且仓库外路径禁 new/modify/delete（declaration-premechanize）；补丁镜像使改动可评审可追溯，宿主直改使改动即刻部署生效（既有部署链纪律）。
- **适用范围**：仅 `/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 的 `src/client/`（projectSync.ts、panels.tsx 及新 tooltip 模块）与 `tests/` 两文件 + 本 SPEC `plugin-patch/` 目录；不外溢至其他插件、不做 dsh-plugins 主树 git 操作。

实施序（同先例）：① 基线快照——把拟触达文件当前内容只读复制进本 SPEC `plugin-patch/baseline/fenix-dsh-dashboard-bridge/`，记录 `git -C /root/dsh-plugins rev-parse HEAD` 与 `status --porcelain`；② 宿主直改实现；③ 验证——vitest 全量绿 → `pnpm build`（tsdown，`lib/` symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取新 token URL 重登 → playwright 命名会话（`-s` 隔离）逐 Scenario 实拍截图落 `.history/`；④ 补丁镜像——`diff -ruN baseline/ 宿主现状`（仅拟触达文件）落 `plugin-patch/fenix-dsh-dashboard-bridge.patch` + `BASELINE.md`（HEAD、快照清单、宿主未提交态与恢复备忘）。

## Risks / Trade-offs

- [宿主官方升级改 ProjectRow/拦截层锚] → 富提示随既有导航同路径静默降级（不挂层即无 tooltip），原生提示不受影响；与既有降级纪律同构。
- [`/api/projects` 拉取失败] → 投影为空，该行走原生回退（Scenario 已钉）；60s 后自愈。
- [投影字段与端点演化脱钩] → srcContract 测试钉投影键集合；端点字段增删不破，键删除时测试红。
- [tooltip 数据过期（60s 窗口内台账变化）] → 接受 60s 陈旧窗口（与既有导航对齐周期一致），tooltip 非审计面。
- [宿主主树未提交态与本改动叠加] → 补丁以基线快照对比生成，BASELINE.md 记录恢复路径；风险同先例备忘缓解。
