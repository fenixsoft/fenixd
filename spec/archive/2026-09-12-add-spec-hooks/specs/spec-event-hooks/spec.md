# Spec Event Hooks Spec

## ADDED Requirements

### Requirement: SPEC 状态变化自动发布事件
SPEC 进入任何状态（drafted/ready/implementing/implemented/testing/verified/bug-found/blocked/done/pushed）后，系统 SHALL 在下一个观察周期内（≤5 秒）发布一次对应事件。事件 SHALL 携带：spec 名、from_status、to_status、error（若有）、frozen 标志、时间戳。事件发布 MUST 由 daemon 进程内唯一的全局状态观察者驱动，从而覆盖包括 dashboard 进程写入（admin 处置/人工恢复）与人工冻结直写在内的所有跨进程状态变化路径。

#### Scenario: 状态转换发布事件
- **WHEN** 某个 SPEC 的状态由 verified 转换为 done
- **THEN** ≤5 秒内系统产生一条 done 事件，其字段含 spec 名、from_status=verified、to_status=done

#### Scenario: 跨进程写入同样触发事件
- **WHEN** dashboard 进程（而非 daemon 进程）对某 SPEC 写入状态变化（如 admin 处置引起的转换）
- **THEN** daemon 的状态观察者在 ≤5 秒内同样发布该事件，hook 链路被触发

#### Scenario: 人工冻结触发 blocked 事件
- **WHEN** 用户通过人工冻结把某 SPEC 置为 blocked（冻结直写路径，不经 transition()）
- **THEN** 系统发布 blocked 事件且事件携带 frozen=true 标志

### Requirement: 两级 hook 订阅与多消费者匹配
hook 配置分两级：全局 hooks（设置页配置，对**所有** SPEC 生效）与 spec 级 hooks（spec 详情页配置，仅对**该** SPEC 生效）。事件 `(spec, event_type)` SHALL 命中「events 列表包含该事件类型的全部全局 hooks」加「该 SPEC 的 spec 级 hooks 中 events 包含该事件类型的全部条目」，每个命中的 hook 都是独立消费者 SHALL 各自执行；一个事件可触发多个消费者。

#### Scenario: 全局 hook 对所有 spec 生效
- **WHEN** 存在一条全局 hook 订阅 done 事件，任意 SPEC（如 A 与 B）先后进入 done
- **THEN** 两个 SPEC 的 done 事件均触发该全局 hook 执行

#### Scenario: spec 级 hook 仅对该 spec 生效
- **WHEN** 仅存在一条 spec 级 hook 挂在 SPEC A 上订阅 done 事件，SPEC B 进入 done
- **THEN** 该 hook 不执行；SPEC A 进入 done 时该 hook 执行

#### Scenario: 一个事件触发多个消费者
- **WHEN** 一条全局 hook 与一条 SPEC A 的 spec 级 hook 均订阅 done 事件，SPEC A 进入 done
- **THEN** 两个 hook 均被触发执行，且互不阻塞（各自的成败互不影响对方执行）

#### Scenario: 未订阅的事件不触发
- **WHEN** 某 hook 的 events 列表仅含 done，该 hook 对应范围内某 SPEC 进入 blocked
- **THEN** 该 hook 不执行

### Requirement: enabled 开关
每条 hook 配置 SHALL 含 `enabled` 布尔字段；`enabled=false` 的 hook 在事件匹配时被有意跳过（不执行动作、不告警），审计记录状态为 `skipped`。

#### Scenario: 停用的 hook 不执行动作
- **WHEN** 某 SPEC 进入某 hook 订阅的事件状态，但该 hook 的 enabled=false
- **THEN** 该 hook 的动作不执行，审计日志出现一条 status=skipped 的记录，且不产生失败告警

### Requirement: 动作 restart-daemon（优雅重启 daemon）
动作 `restart-daemon` SHALL 通过创建 `.fenix/restart_request` 请求文件复用现有 supervisor 优雅重启协议（supervisor 检测到请求文件后 SIGTERM daemon、等待退出、重启并清除请求）。请求文件创建成功即视为动作成功，MUST NOT 由 hook 执行器直接杀灭 daemon 进程。

#### Scenario: done 事件触发 daemon 优雅重启请求
- **WHEN** 某 hook 订阅 done 事件且动作为 restart-daemon，某 SPEC 进入 done
- **THEN** `.fenix/restart_request` 请求文件被创建，动作记为成功，daemon 由 supervisor 按既有协议优雅重启

### Requirement: 动作 restart-dashboard（优雅重启 dashboard）
动作 `restart-dashboard` SHALL 重启 dashboard 的 tmux 会话（会话名取条目可选参数 `target`，缺省 `fenix-dashboard`）：以 `tmux respawn-window -k` 形式执行固化后的原启动命令，命令 MUST 满足 `env -u CLAUDE_PID`（防 claude-watchdog 绑会话自杀）且保持 8787 端口与原工作目录。重启后 SHALL 探测目标端口恢复可服务，探测成功记成功、探测超时记失败。

#### Scenario: 重启命令按协议构造并执行
- **WHEN** 某 hook 的动作为 restart-dashboard 且目标为测试沙箱会话
- **THEN** 执行的重启命令包含 `env -u CLAUDE_PID` 与该会话名，且以 tmux respawn 方式重启该会话

#### Scenario: 重启后端口恢复可服务则成功
- **WHEN** restart-dashboard 动作执行且目标端口在探测超时窗口内恢复 HTTP 可服务
- **THEN** 该动作审计记录为 success

#### Scenario: 端口未恢复则失败并告警
- **WHEN** restart-dashboard 动作执行后目标端口在探测超时窗口内不可服务
- **THEN** 该动作审计记录为 failure，且产生一条站内失败告警

### Requirement: 动作 commit / push / commit-push（提交与推送变更）
动作 `commit` SHALL 在项目仓库执行 `git add -A` 后以提交信息模板（变量 `{spec}`、`{event}`，缺省模板 `[fenix] hook: {spec} {event}`）执行 `git commit`；工作区无变更时 SHALL 视为 no-op 成功（审计记 `noop`，不告警）。动作 `push` SHALL 执行 `git push`（跟随当前分支 upstream）。动作 `commit-push` SHALL 先执行 commit 再执行 push：commit 为 no-op 时仍执行 push；push 失败 MUST NOT 回滚已产生的本地提交。commit/push 动作 MUST NOT 提交或依赖 hook 自身产生的中间文件以外的东西——语义为提交项目仓库当前工作区变更。

#### Scenario: 有变更时提交成功且信息含 spec 与事件
- **WHEN** 项目仓库工作区存在变更，某 SPEC 进入已订阅事件状态触发 commit 动作（spec=A、event=done、使用缺省模板）
- **THEN** 仓库产生一条新提交，其提交信息包含 spec 名 A 与事件名 done

#### Scenario: 无变更时 no-op 成功
- **WHEN** 项目仓库工作区干净时触发 commit 动作
- **THEN** 不产生新提交，审计记录 status=noop，不产生失败告警

#### Scenario: commit-push 组合执行
- **WHEN** 工作区有变更且配置了指向本地 bare 仓库的 upstream，触发 commit-push 动作
- **THEN** 本地产生新提交且变更被推送到远端；若 push 失败，本地提交仍保留且审计记 failure

#### Scenario: push 推送当前分支
- **WHEN** 本地存在领先于 upstream 的提交，触发 push 动作
- **THEN** 当前分支被推送到其 upstream，审计记录 success

### Requirement: 动作 webhook（HTTP 通知，含审计）
动作 `webhook` SHALL 向条目配置的 `url` 发送一次 HTTP POST（`Content-Type: application/json`），body 为含 `event`/`spec`/`from_status`/`to_status`/`ts`/`error`/`frozen`/`hook_id`/`action`/`project` 字段的 JSON 对象。响应 2xx 视为成功；连接失败、非 2xx、超时（`timeout_seconds` 缺省 10）视为失败。webhook 调用 SHALL 写审计日志（含请求目标 URL、响应状态、耗时）。系统 MUST NOT 为 webhook 提供消息模板引擎（钉钉/飞书等特殊格式由用户经 shell 动作适配）。

#### Scenario: webhook 收到事件 JSON
- **WHEN** 某 hook 的动作为 webhook 且 url 指向验证环境启动的本地 HTTP 收集端点，某 SPEC 进入已订阅事件状态
- **THEN** 收集端点收到一次 POST，body 为合法 JSON 且包含正确的 spec、event、from_status、to_status 字段

#### Scenario: webhook 不可达记失败
- **WHEN** webhook 动作的 url 指向不可达地址（连接拒绝或超时）
- **THEN** 审计记录 status=failure（含错误摘要），且产生一条站内失败告警

### Requirement: 动作 shell（自定义命令）
动作 `shell` SHALL 以 `bash -c <command>` 在项目根目录执行用户配置的 `command`，并注入事件上下文环境变量：`FENIX_HOOK_EVENT`、`FENIX_HOOK_SPEC`、`FENIX_HOOK_FROM_STATUS`、`FENIX_HOOK_TO_STATUS`、`FENIX_HOOK_ERROR`、`FENIX_HOOK_PROJECT_ROOT`。退出码 0 视为成功，非 0 或超时（`timeout_seconds` 缺省 60，超时强制终止）视为失败；stdout+stderr 尾部 ≤2KB SHALL 记入审计。

#### Scenario: shell 收到事件上下文环境变量
- **WHEN** 某 hook 的动作为 shell 且 command 为「将 `$FENIX_HOOK_SPEC|$FENIX_HOOK_EVENT|$FENIX_HOOK_TO_STATUS` 写入指定文件」，某 SPEC 进入已订阅事件状态
- **THEN** 指定文件内容为 `<spec 名>|<事件类型>|<目标状态>`

#### Scenario: shell 超时强制终止并记失败
- **WHEN** 某 shell 动作的 command 长时间阻塞且 timeout_seconds 已到
- **THEN** 命令进程被强制终止，审计记录 status=failure（含超时与输出摘要），且产生站内失败告警

### Requirement: 异步执行不阻塞状态机
hook 分发与动作执行 SHALL 在 daemon 进程的后台线程进行，MUST NOT 阻塞状态机写路径与其他 PM Engine 调度。单个 hook 的慢动作（如不可达的 webhook 等待超时）MUST NOT 延迟其他 hook 的执行，也 MUST NOT 阻塞后续状态转换事件的处理。

#### Scenario: 慢 hook 不阻塞状态转换
- **WHEN** 某 hook 的动作为指向不可达地址的 webhook（将等待超时），其后另一 SPEC 发生状态转换
- **THEN** 该状态转换照常被观察与处理（状态照常变化、对应事件照常产生），状态机不等待该 webhook 完成

### Requirement: 失败处理 = 审计 + 站内告警，不重试
任一动作执行失败（git 失败、webhook 失败、shell 非零/超时、dashboard 重启探测超时等）时，系统 SHALL：(1) 写入 status=failure 的审计记录；(2) 通过 admin_store 告警通道产生一条 `hook_failure` 站内告警（含 spec、事件、动作、错误摘要）。失败 MUST NOT 自动重试。告警 MUST NOT 做去重或降噪（hook 失败是真实信号，每次可见）。

#### Scenario: 失败产生告警
- **WHEN** 某 shell 动作以退出码 1 结束
- **THEN** 审计出现 status=failure 记录，且站内告警中出现一条 hook_failure 告警，内容含 spec 名、事件类型与动作类型

#### Scenario: 失败不重试
- **WHEN** 某 webhook 动作因目标不可达而失败，且该 spec 状态此后未再变化
- **THEN** 该 hook 不被再次自动执行（无重试轮询）

### Requirement: 审计日志
每次 hook 触发 SHALL 在 `.fenix/hook_audit.jsonl` 追加一条 JSON 记录，字段含：`ts`、`spec`、`event`、`from_status`、`to_status`、`hook_id`、`action`、`scope`（global/spec）、`status`（success/failure/noop/skipped）、`detail`（错误或输出摘要 ≤2KB）、`duration_ms`。审计文件为 append-only。系统 SHALL 提供 `GET /api/hooks/audit` 端点按 spec 过滤、按 limit（缺省 20）返回尾部倒序记录。

#### Scenario: 成功执行留下完整审计记录
- **WHEN** 某 hook 成功执行完毕
- **THEN** `.fenix/hook_audit.jsonl` 新增一条记录，status=success 且含 spec/event/action/scope/duration_ms 字段

#### Scenario: 审计查询 API 按 spec 过滤
- **WHEN** 审计文件含 SPEC A 与 SPEC B 的执行记录，请求 `GET /api/hooks/audit?spec=A&limit=20`
- **THEN** 响应仅含 SPEC A 的记录且为时间倒序、不超过 20 条

### Requirement: hook 配置持久化与生效
hook 配置 SHALL 持久化于 `.fenix/config.yaml` 的 `hooks` 段（`hooks.global` 列表 + `hooks.specs.<spec名>` 列表），经现有配置热更新机制（30s mtime 轮询）生效。经 `POST /api/config` 保存时 SHALL 校验：`events` 非空且取值均在十状态枚举内、`action` 在七种动作枚举内、webhook 必填非空 `url`、shell 必填非空 `command`，违规返回 400。无 `hooks` 段或缺省配置 = 空订阅、零行为（完全向后兼容）。

#### Scenario: 配置保存后按新配置执行
- **WHEN** 用户经设置页保存一条新的全局 hook（订阅 done、动作 shell），≤30 秒后某 SPEC 进入 done
- **THEN** 该 hook 被触发执行（热更新已加载新配置）

#### Scenario: 非法配置被拒绝
- **WHEN** 经 `POST /api/config` 提交一条 action=webhook 但 url 为空的 hook
- **THEN** 请求返回 400，配置不被写入

#### Scenario: 无 hooks 段时零行为
- **WHEN** `.fenix/config.yaml` 不含 hooks 段，任意 SPEC 状态发生变化
- **THEN** 不触发任何 hook、不产生任何审计记录，系统其余行为不变

### Requirement: spec 详情页 Hook 页签
SPEC 详情页 SHALL 在「失败截图」页签之后提供「Hook」页签，包含三个区块：(1) 生效中的 Hooks——合并展示全局 hooks 与该 SPEC 的 spec 级 hooks，来源列标注「全局/本 spec」，含启停状态；(2) 本 spec 的 Hooks——spec 级 hooks 的新增/编辑/删除/启停，编辑表单含事件多选、动作选择与按动作类型显隐的参数字段（webhook 的 url、shell 的 command 与超时等）；(3) 最近执行——该 SPEC 的审计记录列表（时间/动作/结果/耗时/摘要）。

#### Scenario: 页签位置与生效列表
- **WHEN** 打开某 SPEC 详情页并切换到 Hook 页签
- **THEN** 页签位于「失败截图」页签之后；生效列表同时展示订阅中的全局 hooks（来源标「全局」）与该 SPEC 的 spec 级 hooks（来源标「本 spec」）

#### Scenario: 新增 spec 级 hook
- **WHEN** 用户在 Hook 页签为本 SPEC 新增一条 hook（选择事件 done、动作 webhook、填写 url）并保存
- **THEN** 配置写入 `.fenix/config.yaml` 的 `hooks.specs.<该spec>` 段，列表出现该条目，且后续该 SPEC 进入 done 时该 webhook 被触发

#### Scenario: 最近执行展示
- **WHEN** 某 SPEC 的 hook 有过执行（成功或失败），用户打开其 Hook 页签的「最近执行」区
- **THEN** 展示对应审计记录（时间、动作、结果、耗时），失败记录可见错误摘要

### Requirement: 设置页 Hook 面板（全局 hooks）
设置页 SHALL 新增「Hook」菜单项与面板，提供全局 hooks 的新增/编辑/删除/启停（表单结构同 spec 级：事件多选 + 动作 + 参数），并展示全局范围的最近执行记录（全部 spec 的审计尾部）。

#### Scenario: 新增全局 hook
- **WHEN** 用户在设置页 Hook 面板新增一条全局 hook（订阅 blocked、动作 shell、填写 command）并保存
- **THEN** 配置写入 `.fenix/config.yaml` 的 `hooks.global` 段，且后续任意 SPEC 进入 blocked 时该 shell 命令被触发执行

#### Scenario: 面板展示全局执行记录
- **WHEN** 多个 SPEC 的 hook 有过执行记录，用户打开设置页 Hook 面板的最近执行区
- **THEN** 展示跨 SPEC 的审计尾部记录（含 spec 列），不限于单个 SPEC
