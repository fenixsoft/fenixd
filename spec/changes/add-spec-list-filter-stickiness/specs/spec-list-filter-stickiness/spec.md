# Spec: SPEC 开发列表过滤粘滞（URL 查询参数持久化）

项目页 SPEC 开发列表（路由 `/projects/:name`）的 4 个过滤条件（搜索关键词、状态多选、类型、归档切换）与页签选中态 SHALL 持久化到 URL 查询参数，使「从详情返回」「刷新页面」「带参链接直达」三条路径下视图完整恢复。

## ADDED Requirements

### Requirement: 过滤状态写回 URL

SPEC 开发列表页 SHALL 在过滤状态变更时将其同步写入 URL 查询参数，采用 replace 语义（MUST NOT 为过滤操作新增浏览器历史条目）。

- 参数白名单与承载关系 MUST 为：`tab`（页签）、`q`（搜索关键词）、`status`（状态多选，合法状态枚举逗号分隔）、`type`（类型过滤）、`archived`（归档切换）。
- 合法值域 MUST 为：`tab ∈ {dev, quality, regression, session}`；`status ⊆ {drafted, ready, reviewing, implementing, implemented, testing, verified, bug-found, blocked, done, pushed}`；`type ∈ {active, completed}`；`archived = 1`。
- 各参数处于缺省值时（`tab=dev`、`q` 为空、`status` 为空、`type` 为空即全部、`archived` 未归档）MUST NOT 写入该参数——默认视图下 URL 保持无参干净形态。
- 搜索关键词 MUST 按防抖节拍（既有 300ms 防抖）写入 URL，MUST NOT 逐字符同步；输入框回显与列表过滤的既有行为不变。
- 页面路由路径 MUST 保持 `/projects/:name` 不变，MUST NOT 因参数同步引发页面级刷新或导航。

#### Scenario: 过滤变更同步 URL

- **WHEN** 用户在 SPEC 开发列表设置状态过滤为「就绪（ready）」、类型为「进行中」
- **THEN** 浏览器地址 MUST 变为含 `status=ready&type=active` 的查询串，且页面不发生整页刷新

#### Scenario: 缺省值不污染 URL

- **WHEN** 用户清空全部过滤条件（搜索为空、状态清空、类型「全部」、未归档）且处于「开发」页签
- **THEN** 浏览器地址 MUST 不含 `tab`/`q`/`status`/`type`/`archived` 任何参数（与打开时无异）

#### Scenario: 搜索防抖后落 URL

- **WHEN** 用户在搜索框输入关键词后停顿超过防抖时长
- **THEN** URL 查询串 MUST 出现该关键词（`q=<关键词>`）；输入过程中的每个字符 MUST NOT 触发 URL 更新

### Requirement: 从 URL 恢复过滤状态

SPEC 开发列表页挂载时 SHALL 从 URL 查询参数读取并恢复 5 项状态（搜索关键词、状态多选、类型、归档切换、页签），使以下三条路径的视图恢复一致：从 SPEC 详情返回、浏览器刷新、带参 URL 直接打开。

- 恢复搜索关键词时 MUST 同时回填输入框（`q`）与生效过滤值（`debouncedQ`），MUST NOT 出现「先展示全量列表、防抖到期后才过滤」的中间态。
- 恢复页签时 MUST 复用既有分面 `active` 门控语义：仅被选中的分面发起自身数据拉取，未选中分面 MUST 保持零请求；恢复到「会话」分面 MUST NOT 隐式启动会话进程（未启动仍显示「开始会话」空态）。
- 无参数（或参数缺省）打开时行为 MUST 与引入本能力前完全一致（默认「开发」页签、全部状态、未归档）。

#### Scenario: 详情返回恢复过滤

- **WHEN** 用户设置搜索词、状态多选、类型过滤与归档切换后，点击任一 SPEC 进入详情页，再通过浏览器返回或导航回到列表
- **THEN** 4 个过滤条件 MUST 全部恢复为返回前的取值，列表数据 MUST 按该过滤口径渲染

#### Scenario: 刷新保持页签与过滤

- **WHEN** 用户切到「质量」页签并设置状态过滤后刷新页面
- **THEN** 页签 MUST 仍为「质量」且状态过滤恢复（不再是默认「开发」页签）

#### Scenario: 带参链接直达

- **WHEN** 用户以 `?tab=session&status=blocked` 直接打开项目页
- **THEN** 页面 MUST 停在「会话」页签且状态过滤为「阻塞（blocked）」；若会话未启动，MUST 显示「开始会话」空态而不自动启动会话进程

### Requirement: 非法参数 fail-safe

URL 查询参数解析 SHALL 采用白名单校验，任何非法参数值 MUST 被静默忽略并回退缺省值，MUST NOT 崩溃、MUST NOT 产生 console error、MUST NOT 将非法值传入过滤逻辑。

- 非法 `tab` / `type`（不在值域）MUST 整体忽略回默认；`status` 中非法枚举 MUST 逐个丢弃（全部非法时视为无参）；`archived` 仅 `1` 视为已归档。
- 解析即消毒：页面稳定后 URL 中的脏参数 MUST 被清洗（清洗后的合法形态写回或移除）。

#### Scenario: 非法参数回退默认不报错

- **WHEN** 用户以 `?tab=hack&status=not-a-status,ready&type=xxx&archived=9` 打开项目页
- **THEN** 页面 MUST 正常渲染：页签为「开发」、状态过滤仅保留合法项「就绪（ready）」（`not-a-status` 被丢弃）、类型为「全部」（`xxx` 被忽略）、归档为「未归档」（仅 `1` 为真）；控制台 MUST 无 error 级输出

#### Scenario: 脏参数被自动清洗

- **WHEN** 用户以 `?tab=hack` 打开项目页且页面完成挂载后的首次参数同步
- **THEN** URL 中 MUST 不再残留 `tab=hack`（脏参数被清洗为无参或合法形态）
