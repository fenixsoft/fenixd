## Why

2026-09-21 `add-freeze-stop-inflight-agents` 的收尾阶段，Dashboard 的 SPEC 运行时间轴呈现为**一串
绿色的「开发 Agent」节点**——每个节点都显示 `status: done`、无任何原因文本，看起来像开发 Agent 在
一次次「顺利收工」。真相是这 7 个节点全部是**产物硬门 `impl-code-review-gate` 判失败后的原地退避
重试**，每次失败的完整归因（`exit 0 但收尾审查报告缺失（impl-code-review-gate）: ...`）**只写进了
daemon 日志与 STATE.md**，run jsonl 里一处都没有。

实测事实（两个子代理独立取证一致）：

- 门禁失败时 `_handle_artifact_gate_retry`（`core/agent_runner/runner.py:2653`）只往 run jsonl 写
  `{"type":"transient_retry", …, "reason":"artifact_gate"}` 与 `{"type":"superseded", …}`——**两者都不含
  错误文案**；错误文案只经 `self.logger.warning(...)` 进 daemon log、经 `AgentRunResult.error` 进
  STATE.md `error` 字段。
- 读侧 `_run_tail_insights`（`core/dashboard/data/runs.py:531`）只从**终态事件**的 `error`/`reason`
  字段取 `reason`；`superseded` 虽在 `_RUN_TERMINAL_STATUS_MAP` 内却无这些字段 → `reason=""`；
  `transient_retry` 不在映射内 → 完全被忽略。
- 预算耗尽后的 attempt 层最终失败**不写任何 run jsonl 事件**，末行仍是 CLI 自带的
  `result`（`is_error:false`）→ `classify_run` 判 `done` → 前端绿色。
- 前端 `detail.tsx` 对 `superseded` 无专属分支 → 落绿色兜底；`reason` 为空 → 原因行不渲染。
- 唯一把门禁错误送达 UI 的通道是 SPEC 详情页**顶部的 info Alert**（`summary.error`），**不在时间轴上**。

结果：用户看时间轴完全无法察觉门禁在连续拒绝，误以为「Agent 反复声明自己顺利通过」。

## What Changes

- **写侧（run jsonl）**：门禁失败在 run jsonl 留痕时**带上错误文案**——
  `transient_retry` 与 `superseded` 事件各增 `error` 字段（门禁归因全文）；原地重试预算耗尽 / 让位等
  终止本次 attempt 文件的分支，追加一个**新的终态事件** `{"type":"gate-blocked","error":…,"reason":…}`，
  使该 attempt 产物末行为终态且携带门禁归因。
- **读侧（时间轴数据）**：`_RUN_TERMINAL_STATUS_MAP` 增 `gate-blocked` 终态映射（自动并入可归档集合）；
  `_run_tail_insights` 继续从终态事件取 `reason`（`superseded` / `gate-blocked` 自此带上原因），
  时间轴 run 节点据此下发 `reason` 与终态 `status`。
- **前端（节点渲染）**：`detail.tsx` run 节点增 `gate-blocked` 状态专属渲染（红点 +「门禁拒绝」Tag +
  「门禁拒绝：<文案>」原因行）；`superseded` 节点在有原因时以中性色显示「原地重试：<文案>」原因行
  （圆点仍为绿色——它是被弃置的中间产物，失败归因由紧随其后的 `gate-blocked` 节点承担，避免同一次
  失败出现两个红节点；据此**不再**呈现为「无原因绿点」）。
- **写侧终态类型两侧同步**：新终态 `gate-blocked` 必须同时登记进读侧映射
  `_RUN_TERMINAL_STATUS_MAP` 与写侧终态集合 `RUN_TERMINAL_EVENT_TYPES`（`liveness.py`）——缺后者会
  让刚被门禁拦下的 SPEC 在「在跑判定」里被判为有进行中的运行，删除/归档被误拦。

## Capabilities

### New Capabilities

- `timeline-gate-failure-display`: 门禁失败在 run 产物与 Dashboard 时间轴上的可见性——写侧带错误文案的
  事件、读侧终态映射与原因提取、前端 Agent 节点上的门禁错误展示。

## Impact

- 受影响代码：`core/agent_runner/runner.py`、`core/dashboard/data/runs.py`、
  `core/agent_runner/liveness.py`、`core/dashboard/static/src/pages/projects/detail.tsx`（+ 构建产物）。
- 受影响测试：`tests/test_agent_runner_gate.py`、`tests/test_dashboard_data.py`、
  `tests/test_freeze_stop_inflight_agents.py`。
- 行为影响面：新增一个终态状态枚举 `gate-blocked`。所有消费 `_RUN_TERMINAL_STATUS_MAP` 的读侧
  （归档判定、活跃计数、预算计数、在跑判定、code-review 进度）需同步核对——本 SPEC 明确要求逐处
  复核，MUST NOT 让门禁失败被误判为「死亡 run」而绕过实现预算，也 MUST NOT 被误判为「在跑」而拦下
  删除/归档（明细见 design D4）。
- 非目标：不改门禁判据本身；不引入新的配置项；不改 `_retry_count` 语义（原地门禁重试次数不并入
  该计数，另见 design 非目标）。
