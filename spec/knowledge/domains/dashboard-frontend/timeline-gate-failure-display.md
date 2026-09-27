<!-- knowledge: capability=timeline-gate-failure-display rev=1 sources=spec/archive/2026-09-25-add-timeline-gate-failure-display -->

# 时间轴门禁失败展示

门禁失败全程可见化：run 产物带归因、独立终态事件 `gate-blocked` 与时间轴红色失败渲染。

## 现行规则

- 重试与弃置事件带归因：产物硬门（`AgentArtifactGateError`）失败时的原地退避重试路径把门禁归因文案写入 run jsonl（而非仅写 daemon log）——`transient_retry` 事件（门禁路径）与 `superseded` 事件（门禁路径）均含 `error` 字段，截断至 ≤1024 字符（UTF-8 编码后 ≤4096 字节）；归因文案保留门禁名称与目标路径（截断不得使其不可判）。
- 独立终态事件：门禁失败导致本次 attempt 终止时，向该 attempt 的 run jsonl 追加终态事件 `{"type": "gate-blocked", "spec", "provider", "reason", "error", "timestamp"}`，且为文件末行（维持终态后置不变量）；`reason` 按终止分支取值，不一律填同一值——结构类（产物硬门）原地退避预算耗尽为 `artifact_gate`；任务完成度类（`[task-gate]`）终止本 attempt 为 `task_gate`。
- 让位分支不误标：门禁失败后进入原地退避、退避期间 spec 被接管（让位）时，不追加 `gate-blocked` 事件——该文件终态为已写入的 `superseded`（含 error），把「被接管」标成「门禁拒绝」属误标。
- 收工不变量：上述场景（除让位外）的 attempt 文件不以 `type == "result"` 收尾（否则读侧会将其判为成功）。
- 终态两侧同步登记：写侧终态事件类型 `gate-blocked` 同时登记进两处终态真源——读侧映射 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP`（`classify_run` 返回 `gate-blocked` 而非 running，且属于可归档状态集合）与写侧终态集合 `core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES`（末行 gate-blocked 的运行不被「在跑判定」永远判为在跑）；缺一即产生半接入事故。
- 预算与在跑口径：`_run_file_died` 实现预算对账不计末行 gate-blocked 的 run 为死亡（仍计入已耗预算）；`running_run_ids_for_spec` 不返回 gate-blocked 终态 run，软删除不因「有进行中的运行」被拒。
- 时间轴与前端：时间轴 run 节点在门禁失败时下发非空 `reason`（取自终态事件的 error/reason 字段），不依赖展开运行记录；`detail.tsx` 对 `status == "gate-blocked"` 给出可辨识失败渲染——圆点与状态 Tag 为失败色（红）、Tag 文案表达「门禁拒绝」、reason 非空时渲染「门禁拒绝：<原因>」行，不落入成功（绿色）兜底；`superseded` 且 reason 非空渲染「原地重试：<原因>」行，不呈现为无原因节点。

## 溯源

- 2026-09-25 add-timeline-gate-failure-display — 建立门禁失败可见化全链：transient_retry/superseded 事件带归因、gate-blocked 独立终态事件与读写两侧同步登记、时间轴节点带原因与前端红色失败渲染
