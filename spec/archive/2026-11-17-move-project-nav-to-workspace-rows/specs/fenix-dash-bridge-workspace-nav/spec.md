# fenix-dash-bridge-workspace-nav — dsh 侧栏工作区行项目导航

## ADDED Requirements

### Requirement: 工作区行项目名称导航

Client 半 SHALL 在官方工作区列表中，对 fenixd 项目对应的工作区行启用「名称点击=打开项目详情」：主面板 SHALL 切换为该项目 iframe（`main` keyed 面板 `fenix-project-<name>`，src 深链 `#/projects/<encodeURIComponent(name)>` 契约不变），且 MUST NOT 触发该行展开/收缩。行首图标（官方 hover folder→chevron 交换）点击 SHALL 维持原生展开/收缩，插件 MUST NOT 改变其点击语义。行-项目匹配判据 SHALL 路径身份优先：工作区注册路径与项目路径归一化后（统一分隔符、去尾斜杠；client 运行于浏览器无 fs.realpath，MUST NOT 依赖 fs 规范化）字符串相等优先命中，工作区标题与项目名精确相等回落。该优先序刻意不同于既有 `resolveWorkspaceIdForProject`（其实现为标题优先、basename 回落，见 dsh-plugins `src/client/index.ts`），路径优先以消除同名标题工作区误判；工作区枚举 SHALL 复用既有 `ui.workspaces.list.getSnapshot().items` 通道。拦截定位 MUST 基于语义锚点（`data-row-key` 前缀 `workspace:` 的行元素及其名称文本），MUST NOT 依赖 CSS module 哈希类名作唯一判据；锚点不可达或结构漂移时 SHALL 静默不拦截（原生行为兜底），MUST NOT 产生控制台未处理异常。

#### Scenario: 名称点击打开项目详情

- **WHEN** 用户点击 fenixd 项目对应工作区行的名称「fenixd」
- **THEN** 主面板切换为该项目 iframe（src 深链 `#/projects/fenixd`），该行展开/收缩状态不变，无控制台未处理异常

#### Scenario: 行首图标点击展开收缩

- **WHEN** 用户 hover 行首图标（呈箭头形态）并点击
- **THEN** 该行按原生行为展开或收缩其会话列表，主面板不切换

#### Scenario: 非 fenix 工作区行零侵入

- **WHEN** 用户点击非 fenixd 项目工作区行的任意区域（含名称）
- **THEN** 行为与插件改动前完全一致（整行点击展开/收缩），无导航发生

#### Scenario: 拦截不外溢

- **WHEN** 用户对 fenixd 项目工作区行使用行尾省略号菜单、新会话按钮、右键菜单或拖拽排序
- **THEN** 上述官方操作全部照常工作，名称导航拦截不捕获这些交互

#### Scenario: 锚点漂移静默降级

- **WHEN** dsh 升级导致工作区行 DOM 结构变化（`data-row-key` 或名称子元素定位失败）
- **THEN** 名称导航不生效，工作区行全部维持原生行为，无未处理异常；不做任何破坏性兜底

### Requirement: 侧栏项目入口退役

Client 半 SHALL 移除侧栏「项目」固定条目（`fenix-projects`）及内嵌项目分区全部形态：常驻内嵌 Portal 分区、锚点漂移浮层降级路径、窄轨计数徽标、分区标题折叠拦截层、分区专属样式中的失效选择器。固定条目集合 SHALL 收敛为 5 项（概览/指挥中心/配置/运维/帮助）。`main` keyed 面板注册 SHALL 保留每项目面板 `fenix-project-<name>`（项目同步 add/remove 契约不变）并移除 `fenix-projects` 主面板注册；`#panel=fenix-projects` 旧深链随未注册语义静默吞。`sidebar.workspaces` 槽位 MUST NOT 被抢占；官方工作区列表滚动条注入（既有 polish）SHALL 维持。

#### Scenario: 条目移除无残留

- **WHEN** 插件生效后展开 dsh web 侧栏
- **THEN** 固定条目区仅呈现 5 项（无「项目」），条目列表与工作区区域之间无插件注入分区，窄轨态无项目计数徽标

#### Scenario: 旧深链键静默退役

- **WHEN** 用户以 `#panel=fenix-projects` 打开 dsh web
- **THEN** 无未处理异常，界面落在既有兜底行为（未注册 id 吞，同既有 deepLinkPanels 语义）

#### Scenario: 每项目主面板注册保留

- **WHEN** 名称导航把主面板切到某项目后，上游项目列表轮询返回该项目仍存在
- **THEN** 该项目 `fenix-project-<name>` 主面板保持注册可用，反复切换不产生重复注册或泄漏

### Requirement: 项目工作区自动对齐

Client 半 SHALL 在项目列表同步周期（60s）内对齐工作区注册：上游项目存在且路径可达（`parseProjectPath` 仅收 `exists:true` 判据）而无对应工作区时，SHALL 经 `workspaces.create({path})` 自动注册（MUST NOT 自动开会话）；项目从上游列表移除后，其工作区 SHALL 保留不删，且该行因不再命中匹配判据而失去名称导航（回退原生整行折叠）。项目列表拉取失败时 SHALL 跳过本轮对齐（不建不删），仅按既有纪律 warn。对齐 MUST NOT 移除或改写任何非 fenixd 项目工作区。

#### Scenario: 新项目自动出现

- **WHEN** fenixd 侧新建项目（扫描发现，`.fenix/STATE.md` 判据）且路径存在，同步周期到期
- **THEN** dsh web 工作区列表自动出现该项目行（basename 为标题），无会话被自动创建

#### Scenario: 删除项目行保留且不跳转

- **WHEN** 上游项目列表移除某项目后，用户点击其遗留工作区行名称
- **THEN** 不发生导航，行维持原生展开/收缩行为；工作区行不被插件删除

#### Scenario: 拉取失败不误伤

- **WHEN** 项目列表 API 不可达或超时（10s 超时判据不变）
- **THEN** 本轮对齐整体跳过，既有工作区与侧栏状态无任何变化，控制台仅 warn 无未处理异常
