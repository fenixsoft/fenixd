## ADDED Requirements

### Requirement: 心跳类事件静默渲染

系统 SHALL 在 run 事件转聊天气泡时静默丢弃以下事件类型，使其不产生任何可见行：`tool_progress`、`background_tasks_changed`、`commands_changed`、`run_metrics`、`init`、非错误 `stderr`（`line` 不含错误标识）、`hook_started`、`hook_response`。

被静默的事件 MUST NOT 打断连续工具的分组判定（等效于不可见分隔符）。

#### Scenario: tool_progress 心跳不再渲染

- **WHEN** run 流中存在 74 条 `tool_progress` 事件（30 秒间隔存活心跳）穿插在工具调用之间
- **THEN** 渲染结果中不出现任何 `[tool_progress]` 行
- **THEN** 相邻的同名工具调用不再被心跳行隔断，可参与连续分组

#### Scenario: 非错误 stderr 静默而错误 stderr 保留

- **WHEN** run 流含 `{"type":"stderr","line":"[claude-code:unrecognized_model] ..."}` 与 `{"type":"stderr","line":"ECONNREFUSED ..."}`
- **THEN** 后者等含错误关键词（`error`/`Traceback`/`failed` 等，判定表在设计文档固化）的 stderr 行仍渲染为系统行
- **THEN** 非错误行不渲染

### Requirement: 信息类事件语义化渲染

系统 SHALL 将以下事件渲染为携带关键载荷的单行系统条（中文），替代 `[label]` 裸行：

- `provider_marker` → 模型路由条：`模型路由 <model> @ <provider>（第 <chain_index+1>/共 <chain_len> 棒）`
- `transient_retry` → 告警条：含 `reason`、`backoff_seconds`、`retry_number`、`error` 摘要
- `compact_boundary` → 压缩条：含 `compact_metadata.trigger`、`pre_tokens`、`post_tokens`
- `vcs_state_changed`（`kind=commit`）→ 提交条：含短哈希与分支名

载荷缺失时 MUST 优雅降级为仅类型中文名（如「模型路由」），MUST NOT 渲染 `[label]` 裸行或空行。

#### Scenario: provider_marker 渲染为路由条

- **WHEN** 事件为 `{"type":"provider_marker","provider":"bigmodel.cn","model":"glm-5.3-flash","chain_index":0,"chain_len":4}`
- **THEN** 渲染为单行系统条，可见文本含 `bigmodel.cn`、`glm-5.3-flash`、`1/4`
- **THEN** 不含文本 `[provider_marker]`

#### Scenario: transient_retry 渲染为告警条

- **WHEN** 事件为 `{"type":"transient_retry","reason":"artifact_gate","backoff_seconds":30,"retry_number":1,"error":"[artifact-structural] exit 0 但 ..."}`
- **THEN** 渲染为系统条，可见文本含 `artifact_gate`、`30`、`1`
- **THEN** 不含文本 `[transient_retry]`

#### Scenario: compact_boundary 渲染为压缩条

- **WHEN** 事件 `compact_boundary` 携带 `{"trigger":"auto","pre_tokens":166773,"post_tokens":8154}`
- **THEN** 渲染为系统条，可见文本含 `166773` 与 `8154`

#### Scenario: 载荷缺失时优雅降级

- **WHEN** `provider_marker` 事件缺失 `model`/`provider` 字段
- **THEN** 渲染为「模型路由」占位系统条，不渲染 `[provider_marker]`、不渲染空行

### Requirement: 任务生命周期回填工具卡片

系统 SHALL 将 `task_started` 与 `task_notification` 事件凭 `tool_use_id` 回填到对应 Task 类工具卡片（`tool_use` 的 `id` 与事件的 `tool_use_id` 相等），卡片上呈现：`description`（started 时）与最终 `status` 及 `summary`（notification 时）。

任务事件 MUST NOT 渲染为独立行。`tool_use_id` 无匹配卡片时（如卡片被分页窗口截断），SHALL 渲染为单行系统条兜底，不静默丢失。

#### Scenario: task_started/notification 回填 Task 卡片

- **WHEN** 某 `tool_use`（id=call_X，name=Task）之后依次到达 `task_started`（tool_use_id=call_X，description="Run dispatch tests"）与 `task_notification`（tool_use_id=call_X，status="completed"，summary="12 tests passed"）
- **THEN** 渲染结果中无独立 `[task_started]`/`[task_notification]` 行
- **THEN** call_X 对应的工具卡片携带该描述与完成状态

#### Scenario: 无匹配卡片时兜底为系统条

- **WHEN** `task_notification` 的 `tool_use_id` 在已加载事件中无对应 `tool_use`
- **THEN** 渲染为一行含 description/summary 的系统条，不静默丢弃

### Requirement: 消费方行为兼容

`runEventsToChatMessages` 的改造 MUST 对全部四个消费入口（spec 详情时间轴内嵌、运行记录全屏弹窗、admin 派发弹窗、admin run 弹窗）无差异生效，MUST NOT 改变事件 jsonl 落盘格式与 `getRunTail` 既有返回结构。

#### Scenario: 既有会话事件测试不回归

- **WHEN** 运行既有 `tests/sessionEvents.test.mjs` 全部用例
- **THEN** 全部通过（session_ended 三种 reason 的中文系统行行为不变）
