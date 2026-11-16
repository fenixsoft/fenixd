# Design: move-project-nav-to-workspace-rows

## Context

现状（2026-11-09 实测）：dsh web 侧栏并存两条项目导航——官方「工作区」列表（session-grouper 已把 `/root/fenixd`、`/root/dsh-plugins` 注册为工作区，registry 现有 6 个 workspaceIds）与 dashboard-bridge 插件注入的「项目」菜单行+内嵌分区（bridge-projects-inline-section 能力，dsh-plugins 仓）。官方 `ProjectRow`（dsh-client-ui-workspace/lib/client.js 编译源可读）结构：`div.projectRow` 整行 `onClick=onToggle`（`role=treeitem`、`aria-expanded`、`data-row-key="workspace:<key>"`）→ 子级 `span.slot.folder`（IconFolderOpen/Close）+ `span.slot.chevron`（IconTriangleRightFill，`arrowOpen` 展开态）+ `span.projectText > span.title` + `span.rowActions`（省略号菜单按钮 stopPropagation + 新会话 Tooltip 按钮）；官方源注释明示 **hover folder→chevron 交换是纯 CSS 既有行为**——「悬停变箭头」无需新增。bridge 现有机制：60s 轮询 `<prefix>api/projects`（超时 10s）→ `projectEntrySink` 注册每项目 `main` keyed 面板 `fenix-project-<name>`（src 深链 `#/projects/<encodeURIComponent(name)>`）；`projectSessionStarter` 已验证 `ui.workspaces.list.getSnapshot().items` 枚举（title/path）+ `workspaces.create({path})`（create 不开会话）。

**立项裁决（用户 2026-11-09）**：落仓 fenixd（明确接受跨仓实施）、完整模式 full、立即执行。fenixd daemon 无按 SPEC 跨仓派发机制（dispatch `project_root` 为项目级参数）；`declaration-premechanize` 知识页明示实现 Agent 对仓库外路径禁 new/modify/delete、物理不可达。宿主 `/root/dsh-plugins` 主树当前含**未提交**改动（2026-11-03 徽标改造已部署未提交：panels.tsx +34/-2、srcContract.test.ts、brand/chat-polish client.js）——属既有已部署工作区状态，不得回退、不得混入本 SPEC 补丁。

**设计约束以 DESIGN.md 为准**（界面设计宪法）：本变更零样式新增——移除插件注入样式只删不补，dsh 侧栏行基线条款（Menu 行高 36 + 选中冷灰，DESIGN.md L78）与工作区行官方样式不受触碰；本变更不偏离宪法任何条款，无需宪法修正案。

## Goals / Non-Goals

**Goals**
- 「项目」条目+分区整体退役（含浮层降级、窄轨徽标），固定条目收敛 5 项。
- fenix 项目工作区行：名称点击→项目详情（`#/projects/<name>` 深链契约不变），行首图标点击→原生展开/收缩；非 fenix 行零侵入。
- 新项目 60s 内自动出现在工作区列表（`workspaces.create({path})`，不开会话）；删除项目行保留且名称点击回退原生。
- 补丁镜像可评审、守卫可对账；宿主部署+实拍验证走既有链路。

**Non-Goals**
- 不改 session-grouper（其静态 `projects` 配置与迁移逻辑维持现状——工作区出现由 bridge client 对齐负责）。
- 不改 fenixd dashboard 前后端、不改 dsh 官方包、不改官方行样式与键盘语义（行 `role=treeitem` 无名称键盘焦点态，键盘维持官方行为，属官方面）。
- 不做工作区删除联动（项目删除不删工作区）；不做名称导航的 hover 卡片等增值交互。
- 不在 dsh-plugins 主树做任何 git 提交/回退操作。

## Decisions

**D1 交互分流 = 名称区拦截层（语义锚点）**：对命中匹配判据的工作区行，在 `span.projectText`（名称文本）上方挂 absolute 拦截层（沿用既有整行拦截层 `panelGlyph` 手法：绝对定位 + `stopPropagation` + `preventDefault`），命中即调 `projectPanelSelector(ctx)(name)`（= `layout.selectPanel('fenix-project-<name>')` + hash 写向，既有函数复用）。行首图标区（`slot.folder`/`slot.chevron`）**不遮挡**——原生 `onToggle` 保留，hover 箭头为官方 CSS 既有形态。*备选*：改官方整行 onClick（否——侵入官方行为面）；hover 时换行渲染（否——重渲染抖动）。定位锚点链：行元素 `data-row-key` 前缀 `workspace:` → 行内名称文本子元素按**文本内容比对项目名**定位（不依赖 CSS 哈希类名）；行枚举经 `ui.workspaces.list.getSnapshot().items`（workspaceId/title/path）与 DOM 行按键对应；锚点不可达/文本不匹配 → 该行不装拦截层（静默降级，Scenario 锚点漂移）。拦截层样式零新增视觉（透明命中区，尺寸取名称文本 rect）。拦截层是插件命令式外挂 DOM，宿主 React 重渲染（工作区行挂载/卸载、列表增量更新、展开态切换）可能使其失挂或 rect 漂移——MUST 附带再挂载策略：订阅 `ui.workspaces.list` store 变更或在侧栏工作区区域挂 MutationObserver 触发重扫，重扫前先校验锚点与既有拦截层存活，缺失才补挂；补挂路径同样 warn-only、MUST NOT 产生未处理异常。

**D2 行-项目匹配判据（刻意严于既有 helper 防误伤）**：归一化路径相等优先——工作区 path 与项目 path 归一化（统一分隔符、去尾斜杠）后字符串相等命中，工作区 title == 项目名精确相等回落。*勘误（2026-11-09 评审实测）*：既有 `resolveWorkspaceIdForProject`（dsh-plugins index.ts:336-352）实为**标题优先、`basenameOf(path)==name` 回落**，且不含任何 realpath——本判据并非「与既有同序」，而是刻意反转优先序：同名标题下路径命中的才是真项目行，标题命中的可能是用户自建同名目录工作区（scenario 3 用户明说非 fenix 目录「不必跳转」；标题误判是最大回归风险）。client 运行于浏览器无 fs.realpath，路径比对以字符串归一化实现（不承诺 symlink 别名归并，此类行由标题回落覆盖，行为等同既有 helper）。路径优先同时满足 Scenario 非 fenix 零侵入与删除项目回退：项目消失 → 判据不命中 → 拦截层不装 → 原生行为。

**D3 自动对齐挂进既有同步周期**：`startProjectSync` 60s 回调内追加对齐步——拉取成功后，`parseProjectPath` 过滤 `exists:true` 项目 × `ui.workspaces.list` 快照求差（D2 同序判据），缺失者 `workspaces.create({path})`（官方 API，create 不开会话，`projectSessionStarter` 先例）；拉取失败/超时（10s 判据不变）跳过整轮（不建不删）；对齐只增不改不删（Scenario 删除项目行保留）。*备选*：session-grouper 动态注册（否——越 Non-Goals，其静态配置改动会牵动迁移语义）。

**D4 退役面清单（一次删净）**：`FIXED_ENTRIES` 6→5（`fenix-projects` 移除）；`projectSectionComponent`/`renderProjectGroup`/`projectRow` 工厂/`measureHeaderGeometry`/浮层定位 machinery/分区标题拦截层/窄轨计数徽标/`projectGroupStore.expanded`·`activeProject` 残余引用全清；`fenix-projects` 主面板注册移除（`#panel=fenix-projects` 旧深链由既有未注册吞语义兜底）；`PROJECT_ROW_CSS` 仅保留官方 regionArea 列表滚动条规则（既有 polish 维持）与仍被引用键，分区列表失效选择器删除。每项目主面板注册（`projectEntrySink`）与 `panelIdFromHash`/`deepLinkPanels` 契约**不动**（名称导航目标即它）。

**D5 跨仓交付形态（偏离声明见下节）**：①**基线快照**——实施前把拟触达 5 文件当前内容（含未提交徽标态）只读复制进 worktree `plugin-patch/baseline/`，并记录 `git -C /root/dsh-plugins rev-parse HEAD` + `status --porcelain`；②**宿主主树直改**——实现 Agent（danger-full-access）直接编辑 `/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 源文件（该主树非 fenixd 主树，无 hook 拦截；不在 dsh-plugins 做任何 git 操作）；③**验证**——vitest 全量绿（更新 srcContract 钉值：条目集合 5、深链契约）→ `pnpm build`（tsdown，lib/ symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 取新 token URL 重登 → playwright 命名会话（-s 隔离）逐 Scenario 实拍，截图落 `.history/`；④**补丁镜像**——`diff -ruN baseline/ 宿主现状`（仅拟触达文件）落 `plugin-patch/fenix-dsh-dashboard-bridge.patch` + `BASELINE.md`（HEAD、快照清单、宿主未提交态与恢复备忘）入 fenixd worktree 提交（merge-back 可评审、守卫可对账）。

**D5 偏离声明（框架惯例偏离，非宪法偏离）**：
- **偏离条目**：交付物不落本仓 merge-back 常规形态——实现面在 `/root/dsh-plugins` 宿主主树直改，本仓仅落补丁镜像（`kind: new` 硬校验）+ dsh-plugins 路径声明 `reference`（仅审计）。
- **理由**：用户 2026-11-09 明确裁决落仓 fenixd（已知跨仓代价）；fenixd daemon 无跨仓派发机制且仓库外路径禁 new/modify/delete（declaration-premechanize 知识页）；补丁镜像使改动可评审可追溯，宿主直改使改动即刻部署生效（该部署链本就是 dsh-bridge-projects-section 能力页既有纪律）。
- **适用范围**：仅 `/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 的 src/client 三文件与 tests 两文件 + 本 SPEC `plugin-patch/` 目录；不外溢至 dsh-plugins 其他插件、不做其主树 git 操作。

**D6 DESIGN.md 对照结论**：零样式新增与零样式修改——删除的分区样式属插件自有注入（非宪法管辖的 dashboard 页面样式），保留的官方列表滚动条规则为既有 polish 不回退；侧栏行基线条款（Menu 行高 36/选中冷灰）作用于 dsh 官方行样式，本变更不触碰任何行样式。结论：不偏离宪法，无例外域申请。

## Risks / Trade-offs

- [官方升级改 ProjectRow 结构] → 名称导航静默失效（D1 降级路径），原生折叠不受影响；锚点链仅两步（行 + 名称文本），漂移面小。
- [宿主主树未提交态与本改动叠加] → 补丁以基线快照对比生成，不含既有徽标改动；BASELINE.md 记录恢复路径；风险=用户日后在 dsh-plugins `git checkout/restore` 会同时丢弃两者——以 BASELINE.md 备忘缓解。
- [拦截层遮挡名称区影响官方 hover 卡片] → 拦截层仅覆盖名称文本 rect；官方行 hover 行为（folder→chevron、rowActions 显隐）不在该 rect 内；实拍验证含 Scenario 拦截不外溢。
- [workspaces.create 对无效路径] → 判据前置 `exists:true`（parseProjectPath 既有过滤），失败路径 warn 跳过（projectSessionStarter 同纪律）。
- [restart dsh-web 打断用户在飞会话] → 部署步骤沿用既有链路（用户已知情立项）；restart 仅断 web 进程，CLI/daemon 会话不受影响（dsh-web-session-organization 知识页）。

## Migration Plan

无数据迁移。状态迁移：旧深链 `#panel=fenix-projects` → 未注册吞（既有语义）；已注册工作区不回收；用户书签/习惯路径「项目分区」→「工作区行名称点击」。

## Open Questions

（无——落仓/模式/时机均已获用户裁决；交互目标页 `#/projects/<name>` 沿既有项目卡深链契约。）
