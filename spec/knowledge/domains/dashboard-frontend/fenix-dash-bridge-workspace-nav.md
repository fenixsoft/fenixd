# dsh 侧栏工作区行项目导航

<!-- knowledge: capability=fenix-dash-bridge-workspace-nav rev=1
     sources=spec/changes/move-project-nav-to-workspace-rows -->

dashboard-bridge 插件在 dsh web 侧栏官方工作区列表上的项目导航能力：项目导航收敛进官方工作区行，行内分流「名称点击=打开项目详情、行首图标点击=原生展开/收缩」，并随项目同步周期自动对齐工作区注册。侧栏无独立「项目」入口与内嵌项目分区。

## 规则

- **名称点击 = 项目详情导航**：fenixd 项目对应的工作区行，名称文本区点击将主面板切换为该项目 iframe（`main` keyed 面板 `fenix-project-<name>`，src 深链 `#/projects/<encodeURIComponent(name)>`），不触发行展开/收缩。行首图标为官方 hover folder→chevron CSS 交换形态，其点击维持原生展开/收缩，插件不改其点击语义。
- **行-项目匹配判据路径优先**：工作区注册路径与项目路径归一化（统一分隔符、去尾斜杠）后字符串相等优先命中；工作区标题与项目名精确相等回落。client 运行于浏览器无 fs.realpath，路径比对只做字符串归一化，不承诺 symlink 别名归并（此类行由标题回落覆盖）。该优先序刻意与插件内既有 `resolveWorkspaceIdForProject`（标题优先、basename 回落）相反——同名标题下路径命中的才是真项目行，标题命中可能是用户自建同名工作区。工作区枚举复用 `ui.workspaces.list.getSnapshot().items`（workspaceId/title/path）。
- **拦截层基于语义锚点**：名称导航拦截层挂在命中行的名称文本元素（`span.projectText`）上方（透明命中区，尺寸取名称文本 rect），`stopPropagation` + `preventDefault` 后调项目面板切换；行首图标区（`slot.folder`/`slot.chevron`）不遮挡。定位锚点链：`data-row-key` 前缀 `workspace:` 的行元素 → 行内名称文本按文本内容比对项目名；MUST NOT 依赖 CSS module 哈希类名作唯一判据。
- **锚点漂移静默降级**：锚点不可达或结构漂移时该行不装拦截层（原生整行折叠兜底），不产生未处理异常，不做破坏性兜底。拦截层是插件命令式外挂 DOM，宿主 React 重渲染可致失挂或 rect 漂移——订阅 `ui.workspaces.list` store 变更或在侧栏工作区区域挂 MutationObserver 触发重扫；重扫前校验锚点与既有拦截层存活，缺失才补挂，补挂路径同样 warn-only。
- **拦截不外溢**：行尾省略号菜单、新会话按钮、右键菜单、拖拽排序等官方交互全部照常；拦截层仅覆盖名称文本 rect。
- **非 fenix 工作区行零侵入**：不命中匹配判据的行，整行点击行为与插件介入前完全一致（原生展开/收缩），无导航发生。
- **侧栏固定条目收敛 5 项**：概览/指挥中心/配置/运维/帮助；无「项目」条目、无内嵌项目分区（常驻内嵌、锚点漂移浮层降级、窄轨计数徽标、分区标题折叠拦截层等形态均不存在）。`#panel=fenix-projects` 深链键未注册，由既有 deepLinkPanels 未注册吞语义兜底，无异常。
- **每项目主面板注册保留**：`fenix-project-<name>` 主 keyed 面板注册与项目同步 add/remove 契约不变（名称导航目标即它），反复切换不重复注册、不泄漏；`sidebar.workspaces` 槽位不被抢占。
- **官方列表滚动条注入维持**：`PROJECT_ROW_CSS` 保留官方工作区列表滚动条规则——选择器 `[class*="_regionArea"] [class*="_list"]` 属性包含匹配（类名哈希前缀随构建变、`_regionArea`/`_list` 语义段稳定），6px 宽、thumb 取官方变量色（`--dsh-scrollbar-thumb`）、track 透明、button display:none；`*="_list"` 并命中 `_listArea` 外层容器，其 overflow 规则闲置无害。
- **项目工作区自动对齐**：项目列表同步周期（60s）内，对 `parseProjectPath` 过滤 `exists:true` 的项目与工作区快照求差（同匹配判据），缺失者经 `workspaces.create({path})` 自动注册为 dsh 工作区（basename 为标题，MUST NOT 自动开会话）。对齐只增不改不删：不移除项目被删后遗留的工作区，也不触碰任何非 fenixd 项目工作区。项目列表拉取失败或超时（10s 判据）时跳过整轮对齐（不建不删），仅 warn、无未处理异常。
- **删除项目回退原生**：项目从上游列表移除后，其工作区行保留不删；该行不再命中匹配判据，名称点击不导航，整行回退原生展开/收缩。

## 关键行为

- 实现与部署在宿主仓 dsh-plugins（跨仓）：改 `fenix-dsh-dashboard-bridge` 源码 → `pnpm build`（tsdown，lib/ 产物经 symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取新 token URL 重登 → playwright 命名会话（`-s` 隔离）逐场景实拍，截图落 `.history/`。fenixd 侧交付物为 SPEC 目录 `plugin-patch/` 补丁镜像（基线快照 → 宿主改后状态的 unified diff + BASELINE.md），供评审与守卫对账；宿主主树不做任何 git 操作，宿主既有未提交改动不回退、不混入补丁。
- 验证门：插件仓 vitest 全量绿（`srcContract.test.ts` 钉侧栏固定条目集合 5 与深链契约钉值）；滚动条验证以规则注入 + 占宽几何为证（headless 截图不渲染滚动条本体）。

## 代码锚点

主实现与守卫测试在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 主实现：`fenix-dsh-dashboard-bridge/src/client/index.ts`（项目同步与工作区对齐步、`projectEntrySink` 面板注册、`projectPanelSelector`）、`fenix-dsh-dashboard-bridge/src/client/panels.tsx`（工作区行拦截层与重挂载）、`fenix-dsh-dashboard-bridge/src/client/projectSync.ts`
- 守卫测试：`fenix-dsh-dashboard-bridge/tests/srcContract.test.ts`（条目集合 5、深链契约）、`fenix-dsh-dashboard-bridge/tests/projectSync.test.ts`（对齐判据）

## 溯源

- 2026-11-09 move-project-nav-to-workspace-rows（spec/changes/move-project-nav-to-workspace-rows/） — 新建本页：侧栏「项目」菜单行+内嵌项目分区整体退役（该面既有规则随能力页 dsh-bridge-projects-section 删除收口，官方列表滚动条注入规则移入本页），确立工作区行名称导航/图标折叠分流、路径优先匹配判据、语义锚点拦截与静默降级、60s 自动对齐、删除项目回退原生；跨仓交付形态=基线快照+宿主直改+补丁镜像（ADR-339）
