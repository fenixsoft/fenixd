# dashboard-live-session — 会话面板挂载与会话元数据端点(delta)

既有能力 `dashboard-live-session`(归档于 `spec/archive/2026-09-23-add-dashboard-live-session/specs/dashboard-live-session/spec.md`)的增量:输入区改由 session-composer 控件承载;新增两个只读元数据端点支撑补全。原「发送与终止」「事件流订阅」「权限与目录边界」等需求语义不变。

## ADDED Requirements

### Requirement: 输入区由 session-composer 控件承载

会话面板(SessionPanel)的输入区 SHALL 由 `session-composer` 控件承载,替换现行内联 antd TextArea 输入行。消息流渲染 MUST 继续复用 `claude-msg` 展示组件,MUST NOT 另写消息渲染;「开始会话」(`startSession`)与「停止会话」(`stopSession`)的调用点与语义 MUST 保持不变。

#### Scenario: 挂载替换且渲染不变

- **WHEN** 用户打开会话页签
- **THEN** 输入区为 session-composer 控件,消息流渲染仍走 `claude-msg` 既有组件形态(Markdown / 工具卡片 / thinking 折叠)

#### Scenario: 既有会话后端契约不回归

- **WHEN** 运行 `tests/test_dashboard_session.py` 全部用例
- **THEN** 既有 23 个用例全部通过,MUST NOT 出现行为回归

### Requirement: 会话文件列表只读端点

系统 SHALL 提供 `GET /api/session/files?project=<name>` 端点,返回该项目工作区文件相对路径列表,供 @ 提及补全:

- 实现 MUST 以项目 registry 注册路径为 cwd 执行 `git ls-files --cached --others --exclude-standard`(子进程调用,须带超时保护),返回扁平相对路径字符串数组。
- 返回条数 MUST 上限 5000 条(超出截断)。
- `project` 校验 MUST 复用既有 `_project_from_query`:非法/未注册项目返回 400。
- 合法项目但非 git 仓库(无 `.git`)时 MUST 返回 200 与空数组,MUST NOT 500。
- 端点 MUST 为只读,MUST NOT 修改任何文件或会话状态。

#### Scenario: 正常返回文件列表

- **WHEN** 对一个 git 仓库项目请求 `GET /api/session/files?project=A`
- **THEN** 返回 200,body 为相对路径字符串数组,包含 tracked 与未忽略 untracked 文件,条数 ≤5000

#### Scenario: 非 git 项目返回空数组

- **WHEN** 对一个合法注册但无 `.git` 的项目请求该端点
- **THEN** 返回 200 与空数组

#### Scenario: 非法项目返回 400

- **WHEN** `project` 参数不在 registry 中
- **THEN** 返回 400

### Requirement: 会话命令列表只读端点

系统 SHALL 提供 `GET /api/session/commands?project=<name>` 端点,返回该项目在飞会话可用的斜杠命令与 skill 列表,供 `/` 补全:

- 数据源 MUST 是 SessionManager 从会话进程 stdout `init` 事件缓存的 `slash_commands` 与 `skills` 数组,MUST NOT 自行扫描 `~/.claude/skills` 或项目 `.claude/skills` 目录(init 事件是 CLI 官方口径,反映该进程真实可用命令)。
- 无在飞会话或 init 事件未到达时 MUST 返回 200 与两个空数组。
- 端点 MUST 为只读。

#### Scenario: 有在飞会话返回命令列表

- **WHEN** 项目 A 的会话进程在飞且 init 事件已被缓存
- **THEN** `GET /api/session/commands?project=A` 返回 200,body 含 `slash_commands` 与 `skills` 数组,内容与 init 事件一致

#### Scenario: 无会话返回空列表

- **WHEN** 项目 B 无在飞会话
- **THEN** 返回 200 与空 `slash_commands`、空 `skills`

### Requirement: 会话进程 init 事件缓存

SessionManager SHALL 在 stdout 读线程解析 `type=system` 且 `subtype=init` 的事件,将其中的 `slash_commands` 与 `skills` 缓存到 Session 对象新字段;该缓存 MUST 随 Session 生命周期存亡(进程终止、会话被移除时缓存一并不可达),会话重启后 MUST 以新 init 事件内容覆盖。init 事件本身 MUST NOT 转发给 SSE 订阅者(维持既有 hook 噪音过滤口径,init 属系统事件)。

#### Scenario: init 到达即缓存

- **WHEN** 会话进程启动并在 stdout 输出 init 事件
- **THEN** SessionManager 缓存该事件中的 `slash_commands` 与 `skills`,commands 端点可读取

#### Scenario: 会话终止缓存消亡

- **WHEN** 会话进程被停止且 Session 被移除
- **THEN** commands 端点对该项目返回空数组,MUST NOT 返回陈旧缓存
