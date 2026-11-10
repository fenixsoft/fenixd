# dsh 侧栏工作区行项目导航

<!-- knowledge: capability=fenix-dash-bridge-workspace-nav rev=2
     sources=spec/changes/move-project-nav-to-workspace-rows,spec/changes/add-workspace-row-project-tooltip -->

dashboard-bridge 插件在 dsh web 侧栏官方工作区列表上的项目导航与概况预览能力：项目导航收敛进官方工作区行，行内分流「名称点击=打开项目详情、行首图标点击=原生展开/收缩」；名称悬停显示项目富提示深卡（简介、运行态、SPEC 状态、任务、活跃 Agent），并随项目同步周期自动对齐工作区注册。侧栏无独立「项目」入口与内嵌项目分区。

## 规则

- **名称点击 = 项目详情导航**：fenixd 项目对应的工作区行，名称文本区点击将主面板切换为该项目 iframe（`main` keyed 面板 `fenix-project-<name>`，src 深链 `#/projects/<encodeURIComponent(name)>`），不触发行展开/收缩。行首图标为官方 hover folder→chevron CSS 交换形态，其点击维持原生展开/收缩，插件不改其点击语义。
- **行-项目匹配判据路径优先**：工作区注册路径与项目路径归一化（统一分隔符、去尾斜杠）后字符串相等优先命中；工作区标题与项目名精确相等回落。client 运行于浏览器无 fs.realpath，路径比对只做字符串归一化，不承诺 symlink 别名归并（此类行由标题回落覆盖）。该优先序刻意与插件内既有 `resolveWorkspaceIdForProject`（标题优先、basename 回落）相反——同名标题下路径命中的才是真项目行，标题命中可能是用户自建同名工作区。工作区枚举复用 `ui.workspaces.list.getSnapshot().items`（workspaceId/title/path）。
- **拦截层基于语义锚点**：名称导航与悬停富提示共用同一拦截层——挂在命中行的名称文本元素（`span.projectText`）上方的透明命中区（`data-fenix-wsnav` 锚属性，尺寸取名称文本 rect），`stopPropagation` + `preventDefault` 后调项目面板切换；行首图标区（`slot.folder`/`slot.chevron`）不遮挡。定位锚点链：`data-row-key` 前缀 `workspace:` 的行元素 → 行内名称文本按文本内容比对项目名；MUST NOT 依赖 CSS module 哈希类名作唯一判据。
- **锚点漂移静默降级**：锚点不可达或结构漂移时该行不装拦截层（无导航、无富提示，原生整行折叠兜底），不产生未处理异常，不做破坏性兜底。拦截层是插件命令式外挂 DOM，宿主 React 重渲染可致失挂或 rect 漂移——订阅 `ui.workspaces.list` store 变更或在侧栏工作区区域挂 MutationObserver 触发重扫；重扫前校验锚点与既有拦截层存活，缺失才补挂，补挂路径同样 warn-only。
- **拦截不外溢**：行尾省略号菜单、新会话按钮、右键菜单、拖拽排序等官方交互全部照常；拦截层仅覆盖名称文本 rect。
- **非 fenix 工作区行零侵入**：不命中匹配判据的行，点击与悬停行为与插件介入前完全一致（原生展开/收缩 + dsh 原生 tooltip），无导航、无富提示、无额外 DOM 注入。
- **名称悬停富提示**：fenix 项目工作区行名称（拦截层锚）悬停约 500ms（对齐 dsh 原生 tooltip delayMs）后，行侧浮出插件自渲染富提示深卡——portal 挂 body、`position:fixed`、`pointer-events:none`、固定宽 300px，自上而下含：项目名标题 + 运行态/自动发现胶囊、路径、简介一行、非零 SPEC 状态胶囊组、`任务 x/y 个 · 活跃 Agent n 个` 统计行。视觉规格逐值取 dsh 原生 tooltip 实测：底 `#2C2C2E`、圆角 16px、内距 12px 16px、标题 `#fff` 14px/20px、次文本 `#cfd3d6` 12px/16px、三层阴影、无箭头。
- **富卡浮层视觉归属宿主语言**：该浮层寄居 dsh web 宿主侧栏，视觉跟随宿主原生 tooltip 深卡语言，不取 dashboard DESIGN.md 宪法 token；此豁免仅限 dsh 宿主内插件浮层，不外溢至 dashboard 任何页面、不改宪法 token 表。
- **内容空口径「不伪装」**：简介缺失或为空显示「暂无简介」（弱化色相位，与概览台账口径一致）；非空超长仅显示一行（white-space/overflow/text-overflow ellipsis 三件套）。任务与活跃 Agent 数值 null 或缺失显示「—」不伪装 0，字段为真实 0 照显；统计行数值 tabular-nums。运行态胶囊判定：running+managed=「运行中」good、running+unmanaged=「运行中·未托管」warning、stopped=「未运行」warning；daemon 缺失或其它健康值不渲染胶囊。`discovered:true` 附「自动发现」muted 胶囊；path 缺失不渲染路径行。富卡 DOM 一律 textContent 注入、零 innerHTML（项目名/简介 XSS 面封死）。
- **状态胶囊组真值单源**：状态→tone 映射、中文标签与暗面派生色为插件侧钉值常量（srcContract 钉值防漂移），映射与 fenixd 概览台账 STATUS_META 逐键一致并含阻塞分相扩展（repairing=修复中 info / queued=排队中 warning）；未知状态回退 muted。派生色文字取同相亮化、底同相 16%~22% 透明（info `#7aa2ff` / warning `#f0ac54` / critical `#ff8080` / good `#5fce8f` / aqua `#45c1dc` / muted `#a9b4c0`）。胶囊仅渲染非零状态，序取状态标签表键序（确定序防端点 dict 序漂移，未知状态码点序殿后）；非零超过 4 个折叠为前 4 枚 + `+N` muted 摘要胶囊（不带计数）；全零或字段缺失整段不渲染。
- **富提示数据面=精简投影**：插件项目同步周期（60s）把 `GET <prefix>/api/projects` 响应解析为精简 ProjectSummary 投影 `{name, path, description, daemon, hosting, exists, discovered, status_counts, task_done, task_total, active_runs}`，供行匹配与富提示共用；不保留全量响应对象（problems 等本能力不需要的字段不落内存）。数值字段缺失以 null 承载，`exists`/`error` 为降级标记。fenixd 后端零改动。
- **数据失效回退原生**：投影缺失（undefined）、`exists:false` 或 `error` 非空的行不渲染富提示（不渲染残缺卡），悬停回退 dsh 原生三行提示；名称点击导航链不受数据降级影响（拦截层照常装挂）。`/api/projects` 拉取失败时投影为空、全部行走原生回退，60s 后自愈。
- **原生提示互斥（插件侧消解）**：fenix 行富提示激活期间，该行 dsh 原生三行提示不得同时可见；互斥由两层插件侧手段承担、不改宿主原生 tooltip primitive：① 拦截层 mouse 事件（mouseover/out/move）stopPropagation 吞噬；② 富提示激活期间监听 body 直子新增浮层，含该行项目名文本且非本富卡节点予以隐藏（命中 warn 一次，leave 时恢复其 display；不含项目名的节点不误伤）。宿主机制致两手段均无法消解时按静默降级纪律 warn-only 收场，富提示自身显隐不受影响、不破坏原生提示。
- **静态渲染红线与即收**：富卡显隐纯 display 切换，零 CSS animation/transition（srcContract 钉值断言）；mouseleave、任意容器滚动（capture 链滚动守卫）、行卸载即收。定位锚定拦截层 rect 右侧（水平间距 12px、纵向偏移 -5px），视口越界时水平翻转到锚左侧并纵向 clamp；行瞬窗（宿主重渲染替换中 rect 归零）不显示残卡。
- **富卡不吞点击**：富卡 `pointer-events:none`，悬停激活期间点击行名称仍走既有导航链（`fenix-project-<name>` 深链）。
- **侧栏固定条目收敛 5 项**：概览/指挥中心/配置/运维/帮助；无「项目」条目、无内嵌项目分区（常驻内嵌、锚点漂移浮层降级、窄轨计数徽标、分区标题折叠拦截层等形态均不存在）。`#panel=fenix-projects` 深链键未注册，由既有 deepLinkPanels 未注册吞语义兜底，无异常。
- **每项目主面板注册保留**：`fenix-project-<name>` 主 keyed 面板注册与项目同步 add/remove 契约不变（名称导航目标即它），反复切换不重复注册、不泄漏；`sidebar.workspaces` 槽位不被抢占。
- **官方列表滚动条注入维持**：`PROJECT_ROW_CSS` 保留官方工作区列表滚动条规则——选择器 `[class*="_regionArea"] [class*="_list"]` 属性包含匹配（类名哈希前缀随构建变、`_regionArea`/`_list` 语义段稳定），6px 宽、thumb 取官方变量色（`--dsh-scrollbar-thumb`）、track 透明、button display:none；`*="_list"` 并命中 `_listArea` 外层容器，其 overflow 规则闲置无害。
- **项目工作区自动对齐**：项目列表同步周期（60s）内，对 `parseProjectPath` 过滤 `exists:true` 的项目与工作区快照求差（同匹配判据），缺失者经 `workspaces.create({path})` 自动注册为 dsh 工作区（basename 为标题，MUST NOT 自动开会话）。对齐只增不改不删：不移除项目被删后遗留的工作区，也不触碰任何非 fenixd 项目工作区。项目列表拉取失败或超时（10s 判据）时跳过整轮对齐（不建不删），仅 warn、无未处理异常。
- **删除项目回退原生**：项目从上游列表移除后，其工作区行保留不删；该行不再命中匹配判据，名称点击不导航、悬停无富提示，整行回退原生展开/收缩与原生提示。

## 关键行为

- 实现与部署在宿主仓 dsh-plugins（跨仓）：改 `fenix-dsh-dashboard-bridge` 源码 → `pnpm build`（tsdown，lib/ 产物经 symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取新 token URL 重登 → playwright 命名会话（`-s` 隔离）逐场景实拍，截图落 `.history/`。fenixd 侧交付物为 SPEC 目录 `plugin-patch/` 补丁镜像（基线快照 → 宿主改后状态的 unified diff + BASELINE.md），供评审与守卫对账；宿主主树不做任何 git 操作，宿主既有未提交改动不回退、不混入补丁。
- 验证门：插件仓 vitest 全量绿——`srcContract.test.ts` 钉侧栏固定条目集合 5、深链契约与富提示契约面（锚属性 `data-fenix-wstip`、testid `fenix-wstip-card`、延迟 500ms、宽 300、胶囊折叠上限 4、状态→tone 映射与暗面派生色钉值、深卡样式逐值含零动画红线、富提示回退三分支、内容规格与折叠判定）；`projectSync.test.ts` 钉投影解析（正常摘要/缺 description/exists:false 降级/null 口径四类 fixture）与对齐判据。滚动条验证以规则注入 + 占宽几何为证（headless 截图不渲染滚动条本体）；富提示实测走 playwright 驱动真实 dsh web（route 层 mock 仅限本浏览器上下文）。

## 代码锚点

主实现与守卫测试在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 主实现：`fenix-dsh-dashboard-bridge/src/client/index.ts`（项目同步与工作区对齐步、`projectEntrySink` 面板注册、`projectPanelSelector`）、`fenix-dsh-dashboard-bridge/src/client/panels.tsx`（工作区行拦截层与重挂载、富提示悬停接线）、`fenix-dsh-dashboard-bridge/src/client/projectSync.ts`（精简投影解析）、`fenix-dsh-dashboard-bridge/src/client/wsTooltip.ts`（富提示判定面、深卡 DOM、显隐控制器、原生提示消解观察器）
- 守卫测试：`fenix-dsh-dashboard-bridge/tests/srcContract.test.ts`（条目集合 5、深链契约、富提示契约面）、`fenix-dsh-dashboard-bridge/tests/projectSync.test.ts`（投影解析与对齐判据）

## 溯源

- 2026-11-09 move-project-nav-to-workspace-rows（spec/changes/move-project-nav-to-workspace-rows/） — 新建本页：侧栏「项目」菜单行+内嵌项目分区整体退役（该面既有规则随能力页 dsh-bridge-projects-section 删除收口，官方列表滚动条注入规则移入本页），确立工作区行名称导航/图标折叠分流、路径优先匹配判据、语义锚点拦截与静默降级、60s 自动对齐、删除项目回退原生；跨仓交付形态=基线快照+宿主直改+补丁镜像（ADR-339）
- 2026-11-10 add-workspace-row-project-tooltip（spec/changes/add-workspace-row-project-tooltip/） — 新增名称悬停富提示族规则：插件自渲染深卡浮层（视觉归属 dsh 宿主原生语言、宪法豁免限定插件浮层面）、projectSync 精简 ProjectSummary 投影数据面、状态胶囊组钉值单源与 +N 折叠、空口径「不伪装」、数据失效回退原生、原生提示互斥两层插件侧消解、静态渲染红线与滚动即收、富卡不吞点击；既有导航/对齐/降级/滚动条规则不变
