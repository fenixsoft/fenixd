# Run 流事件降噪与语义化渲染
<!-- knowledge: capability=run-stream-noise-reduction rev=1
     sources=spec/archive/2026-09-27-add-run-record-readability -->

run 事件转聊天气泡时按事件类别分流：心跳类静默、信息类渲染为单行中文系统条、任务生命周期回填到工具卡片，替代 `[label]` 裸行兜底。

## 规则

- **心跳类事件静默渲染**：`tool_progress`、`background_tasks_changed`、`commands_changed`、`run_metrics`、`init`、`status`、`task_updated`、`timeout_extension`、非错误 `stderr`、`hook_started`、`hook_response` 不产生任何可见行。stderr 以错误关键词判定表（`error`/`Traceback`/`failed` 等）区分：非错误行不渲染，错误行仍渲染为系统行。被静默的事件不打断连续工具分组（等效不可见分隔符）。
- **kind 归一化判定**：事件类型取顶层 `type` 非 `system` 时的 `type`；`type` 为 `system` 时取 `subtype`（SDK 结构化事件均为 `type:"system", subtype:<名>` 形态，如 `system/init`）；按顶层 `type` 直配会使静默与语义化名单整体失效。
- **信息类事件语义化渲染**（单行中文系统条；载荷缺失时优雅降级为仅类型中文名，不渲染 `[label]` 裸行或空行）：
  - `provider_marker` → 模型路由条：`模型路由 <model> @ <provider>（第 <chain_index+1>/共 <chain_len> 棒）`；
  - `transient_retry` → 告警条：含 `reason`、`backoff_seconds`、`retry_number`、`error` 摘要；
  - `compact_boundary` → 压缩条：含 `compact_metadata.trigger`、`pre_tokens`、`post_tokens`（载荷整体嵌套于 `compact_metadata` 内）；
  - `vcs_state_changed`（`kind=commit`）→ 提交条：含分支名；无哈希字段时不渲染哈希（写侧补哈希后可附短哈希）。
- **任务生命周期回填工具卡片**：`task_started` 与 `task_notification` 凭 `tool_use_id`（与 `tool_use` 的 `id` 相等）回填对应 Task 类工具卡片，呈现 `description`（started 时）与最终 `status` 及 `summary`（notification 时）；不渲染独立行。`tool_use_id` 无匹配卡片（如卡片被分页窗口截断）时渲染单行系统条兜底，不静默丢失。
- **消费方行为兼容**：转换逻辑对全部四个消费入口（spec 详情时间轴内嵌、运行记录全屏弹窗、admin 派发弹窗、admin run 弹窗）无差异生效；不改变事件 jsonl 落盘格式与 `getRunTail` 既有返回结构（session_ended 三种 reason 的中文系统行行为不变）。

## 溯源

- 2026-09-27 2026-09-27-add-run-record-readability（spec/archive/2026-09-27-add-run-record-readability） — 新增心跳类静默名单与 kind 归一化判定、信息类事件语义化中文系统条、task 生命周期回填工具卡片，废止无字符串 content 一律落 `[label]` 裸行的兜底渲染。
