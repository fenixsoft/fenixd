## ADDED Requirements

### Requirement: 项目级自由会话的创建与复用

系统 SHALL 为每个受管项目维护至多**一个**自由 Claude 会话，会话进程的工作目录
MUST 是该项目的注册根路径（`registry` 中该项目的 `path`），MUST NOT 采用请求中
传入的任意目录。

会话进程 MUST 以「流式输入」模式启动，其命令行 MUST 等价于：

```
claude -p --input-format stream-json --output-format stream-json --verbose \
       --permission-mode bypassPermissions --replay-user-messages
```

- `-p` 与 `--input-format stream-json` 的组合 MUST 使进程在读入一行 stdin JSON
  后执行一轮但**不退出**，从而支持多轮对话。
- `--verbose` MUST 存在（`--print` 与 `--output-format stream-json` 的硬性要求）。
- `--replay-user-messages` MUST 存在：CLI 在无该标志时**不回显**用户输入，
  服务端缓冲将丢失全部用户轮次（重开界面接回后只剩 assistant 侧）。携带该标志后
  每轮输入 MUST 以 `{"type":"user","isReplay":true,…}` 事件出现在事件流中，
  且 MUST 携带 `uuid`（前端去重依赖）。
- 进程环境 MUST 由 dashboard 进程环境复制（`os.environ.copy()`）后覆盖，
  MUST NOT 从 `.fenix/config.yaml` 读取 provider 配置。

同一项目再次请求会话时 MUST 复用既有会话（若其进程仍存活），MUST NOT 新建第二个。

#### Scenario: 首次为项目创建会话

- **WHEN** 客户端显式请求创建项目 `A` 的会话且当前无 `A` 的会话
- **THEN** 系统 MUST 以 `A` 的注册根路径为 cwd 启动一个流式输入模式的 `claude` 进程，
  并返回该会话的句柄

#### Scenario: 回读端点不隐式启动进程

- **WHEN** 客户端对项目 `A` 回读会话状态，而当前无 `A` 的会话
- **THEN** 系统 MUST 返回「无会话」响应，MUST NOT 借此启动任何会话进程

#### Scenario: 用户输入在事件流中可见

- **WHEN** 客户端向存活会话发送文本 `"列一下这个目录"` 并随后重新回读该会话缓冲
- **THEN** 事件流中 MUST 含该轮输入对应的 `user` 事件（`isReplay: true`），
  MUST NOT 只保留 assistant 侧输出

#### Scenario: 重复请求复用同一会话

- **WHEN** 项目 `A` 已有存活会话语句柄 `S`，客户端再次请求 `A` 的会话
- **THEN** 系统 MUST 返回 `S`，MUST NOT 启动新进程

#### Scenario: 会话进程已退出时重建

- **WHEN** 项目 `A` 的会话进程已退出（读线程已观测 EOF 并移除该会话），
  客户端再次请求 `A` 的会话
- **THEN** 系统 MUST 为该会话清理既有登记并新建一个会话进程

#### Scenario: 拒绝非注册根目录作为 cwd

- **WHEN** 客户端请求的项目名在 registry 中不存在，或对应路径不存在
- **THEN** 系统 MUST NOT 启动任何进程，并 MUST 返回错误响应

### Requirement: 一轮输入的发送与工具执行

系统 SHALL 接受客户端发送的一轮用户文本，并 MUST 以如下形态写入会话进程的
stdin（单行 JSON + 换行，UTF-8）：

```json
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"<用户输入>"}]}}
```

- 写入 MUST 在会话级锁保护下进行，MUST NOT 与并发的另一次发送交错。
- 会话进程的**工具调用**（`tool_use`）与**工具结果**（`tool_result`）MUST 原样
  出现在事件流中，MUST NOT 被过滤或改写；权限 MUST NOT 产生交互式询问
  （由 `bypassPermissions` 保证）。
- 发送时 MUST 刷新该会话的 `last_activity`。

#### Scenario: 写入触发一轮对话

- **WHEN** 客户端向存活会话发送文本 `"列一下这个目录"`
- **THEN** 系统 MUST 向该会话 stdin 写入一条上述结构的 JSON 行，且会话进程
  MUST 在事件流中产出对应的 assistant 事件

#### Scenario: 工具调用往返可见

- **WHEN** 会话进程执行了一个 `Bash` 工具调用
- **THEN** 事件流中 MUST 出现含 `name`/`input` 的 `tool_use` 块，且随后 MUST
  出现携带同一 `tool_use_id` 的 `tool_result` 块

#### Scenario: 空文本被拒绝

- **WHEN** 客户端发送的文本为空或仅空白字符
- **THEN** 系统 MUST 返回错误响应，MUST NOT 向 stdin 写入任何内容

#### Scenario: 会话不存在时发送

- **WHEN** 客户端向一个不存在或已终止的会话发送文本
- **THEN** 系统 MUST 返回错误响应，MUST NOT 造成服务端异常

### Requirement: 事件流的增量订阅与全量回读

系统 SHALL 将每个会话进程的 stdout 事件按行解析并缓冲，并通过既有 SSE 通道以
定向订阅的方式推送给订阅了该会话的连接。

- stdout MUST 由**每会话一条**守护线程逐行读取；解析失败的行 MUST 以
  `{"type":"stderr","line":"<原文>"}` 形态兜底，MUST NOT 中断解析或丢弃该行。
- `type == "system"` 且 `subtype` 以 `hook_` 开头的 CLI hook 噪音事件 MUST 被
  丢弃，MUST NOT 进入缓冲或推送给客户端；其余事件（含 `system/init`）MUST 保留。
  该过滤 MUST 只作用于会话路径，MUST NOT 改变 fenixd run 产物的落盘行为。
- 推送事件 MUST 形如 `{"type":"session_events","session_id":"<id>","events":[...]}`，
  且 MUST 只投递给订阅了该 `session_id` 的连接。
- 全量回读端点 MUST 返回该会话当前事件缓冲的全量；若缓冲曾因上限丢弃最旧事件，
  响应 MUST 携带 `truncated: true`。
- 事件缓冲 MUST 有界（模块常量），MUST NOT 无界增长。

#### Scenario: 订阅后收到增量

- **WHEN** 客户端完成会话订阅后，会话进程产出新的 assistant 事件
- **THEN** 该客户端 MUST 通过 SSE 收到含该事件的 `session_events` 消息

#### Scenario: 未订阅的连接不收到该会话事件

- **WHEN** 一条 SSE 连接订阅了会话 `S1`，而会话 `S2` 产出事件
- **THEN** 该连接 MUST NOT 收到 `S2` 的事件

#### Scenario: 非 JSON 脏行不中断流

- **WHEN** 会话进程的 stdout 出现一行不可解析为 JSON 的文本
- **THEN** 系统 MUST 以 `stderr` 事件形态缓冲该行，且后续 JSON 行 MUST 正常解析与推送

#### Scenario: hook 噪音事件被过滤

- **WHEN** 会话进程产出 `{"type":"system","subtype":"hook_response",…}` 事件
- **THEN** 该事件 MUST NOT 进入事件缓冲，MUST NOT 被推送给客户端；同一流中的
  `assistant` / `system/init` 事件 MUST 照常保留与推送

#### Scenario: 缓冲截断被显式标记

- **WHEN** 会话事件数超过缓冲上限致使最旧事件被丢弃
- **THEN** 全量回读响应 MUST 携带 `truncated: true`

#### Scenario: 重开界面接回既有会话

- **WHEN** 客户端关闭界面后重新打开同一项目的会话
- **THEN** 系统 MUST 返回该会话既有缓冲的事件全量，MUST NOT 重启会话进程

### Requirement: 会话的终止与空闲回收

系统 SHALL 提供显式的会话终止能力，并 SHALL 在会话空闲超过阈值时自动终止之。

- 终止 MUST 先关闭 stdin，等待 `SESSION_TERMINATE_GRACE_SECONDS` 后仍存活则 `kill`。
- 会话 stdout 读线程观测到 EOF 时 MUST 判定进程已退出，追加
  `{"type":"session_ended","session_id":"<id>","reason":"process_exit"}` 事件，
  并从会话登记中移除该会话。
- 空闲回收线程 MUST 按 `SESSION_IDLE_TIMEOUT_SECONDS` 扫描，超时会话 MUST 走
  与显式终止相同的路径，并广播 `reason: "idle"` 的 `session_ended` 事件。
- dashboard 进程退出时 MUST 终止全部会话进程（`serve()` 的收尾路径）。

#### Scenario: 显式终止

- **WHEN** 客户端请求终止项目 `A` 的会话
- **THEN** 系统 MUST 关闭该进程 stdin 并在宽限期后确保进程不再存活

#### Scenario: 空闲超时自动终止

- **WHEN** 会话的 `last_activity` 距当前时间超过 `SESSION_IDLE_TIMEOUT_SECONDS`
- **THEN** 系统 MUST 终止该会话并广播 `reason: "idle"` 的 `session_ended` 事件

#### Scenario: 进程被外部杀死时前端收到终态

- **WHEN** 会话进程在系统外部被杀死
- **THEN** 读线程 MUST 观测到 EOF，缓冲一条 `reason: "process_exit"` 的
  `session_ended` 事件，并从登记中移除该会话

#### Scenario: dashboard 退出时不留会话进程

- **WHEN** dashboard 服务进程正常退出
- **THEN** 全部会话子进程 MUST 被终止，MUST NOT 残留为孤儿进程

### Requirement: 前端会话界面的入口与呈现

系统 SHALL 在 SPEC 列表页**标题栏**提供「接入会话」入口，其位置 MUST 在
`共 N 个 SPEC` 文案之后且**靠右对齐**。

- 该入口 MUST NOT 出现在单行 SPEC 的操作菜单（「更多」）中 —— 会话是**项目级**
  语义，不与任何 SPEC 绑定。
- 点击入口 MUST 打开一个界面（Modal），其中 MUST 包含：消息流区（复用既有
  `claude-msg` 展示控件）与输入区（多行输入 + 发送）。
- 消息流 MUST 由既有 `runEventsToChatMessages()` 将事件转换为消息；MUST NOT
  另写一套消息渲染。
- 发送中 MUST 有明确的进行中指示，且 MUST NOT 允许并发重复发送同一轮。
- 会话终止事件 MUST 以明确的终态提示呈现给用户，MUST NOT 表现为静默无响应。

#### Scenario: 入口位置

- **WHEN** 用户打开项目 `A` 的 SPEC 列表页
- **THEN** 标题栏 MUST 显示「接入会话」按钮，位置在 `共 N 个 SPEC` 之后且靠右

#### Scenario: 操作菜单不含会话入口

- **WHEN** 用户展开任一 SPEC 行的「更多」菜单
- **THEN** 菜单中 MUST NOT 出现会话相关项

#### Scenario: 发送一轮并看到回复

- **WHEN** 用户在会话界面输入文本并发送
- **THEN** 该轮输入 MUST 出现在消息流中，且随后显示的 assistant 回复 MUST 使用
  与 run 输出面板相同的渲染形态（Markdown / 工具卡片 / thinking 折叠）

#### Scenario: 会话终止有明确提示

- **WHEN** 会话因空闲超时或进程退出而结束
- **THEN** 界面 MUST 显示明确的会话已结束提示，且输入区 MUST 不再接受发送

### Requirement: 会话能力不产生 fenixd 产物

会话 MUST 与 fenixd 的 SPEC 生命周期完全隔离：MUST NOT 读写 `.fenix/STATE.md`、
MUST NOT 在 `.fenix/runs/` 下产生 run 产物文件、MUST NOT 改变任何 SPEC 的状态或
任务进度。

#### Scenario: 会话不写 run 产物

- **WHEN** 用户在项目 `A` 完成任意轮次的会话
- **THEN** `.fenix/runs/` 下 MUST NOT 新增任何文件

#### Scenario: 会话不改 SPEC 状态

- **WHEN** 用户在项目 `A` 进行会话
- **THEN** `.fenix/STATE.md` 的内容 MUST 保持不变

### Requirement: 会话进程的权限与目录边界

会话进程 MUST 以 `bypassPermissions` 运行，即在该项目根目录内不产生交互式权限
询问。为避免借此越界，会话进程的工作目录 MUST 严格取自 registry 中该项目的
注册路径，MUST NOT 由请求参数决定。

#### Scenario: cwd 恒为注册根

- **WHEN** 为项目 `A`（注册路径 `/x/y`）创建会话
- **THEN** 会话进程的 cwd MUST 为 `/x/y`，与任何请求参数无关
