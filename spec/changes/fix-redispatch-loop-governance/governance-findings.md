# Governance Findings — fix-redispatch-loop-governance

疑点清单：只记录、不修（tasks 1.5）。实现过程中新发现的疑点以追加方式登记；
收尾（tasks 5.3）时给出最终态（已解决 / 遗留）。

## 1. 静态清点阶段疑点（开盘）

### F-1：声明清单与仓库现实的路径偏差

tasks.md Deliverables 声明 `core/pm_engine/dispatch.py`（modify），但主树无此文件
——dispatch 实为**包**：`core/pm_engine/dispatch/`（`__init__.py` + queue.py /
fast_track.py / rollback.py / backoff.py / adjudication.py / repair_lane.py /
rollback.py）。本 SPEC 的 dispatch 改动全部落在包内文件。
**处置**：按实际正确路径实现，并在结果文件 findings 登记 `deliverable-dispute`。

### F-2：`retries >= max_r` 分支现行「清零 + 重派」空转

`_run_agent_worker` 通用失败重派分支（queue.py:1190-1206）在 `retries >= max_r`
时把 `_retry_count` 重置为 0 后立即 `_enqueue` 重派——`agents.max_retries: 3`
形同虚设，「All retries exhausted」只是一行日志（实测该 spec `_retry_count`
始终为 1 却跑了 4 轮）。fast-track `_handle_fast_track_failure`
（fast_track.py:781-794）同款。本 SPEC 3.4 修复。

### F-3：fast-track 车道诚实退出收敛是死路

`_run_fast_track_flow` 收敛判定通过后，后续 MUST 过 `_hard_check_fast_track`
（fast_track.py:514），它要求结果文件带合法 `verification` 段；而 `partial` +
`unattainable` 的结果文件必然没有 → 硬校验 fail-closed → 重派（design D2a 实证）。
**处置**：本 SPEC 2.4 按 D2a 方案 (a) 修复（降级完整模式补独立验证）。

### F-4：收敛点丢弃非法 `unattainable` 项

`_honest_exit_gap`（rollback.py:43）与 `_task_completion_blocker`
（engine.py:1208）丢弃 `parse_unattainable` 返回的 `_invalid`（合法 id 生效、
非法项静默忽略）。产物硬门正常时非法申报已被拦，但「只卡第一次」降级放行后
含非法条目的申报可在收敛点被部分采信——存在洗白窗口。**处置**：本 SPEC 2.5
改为对非空 `_invalid` fail-closed。

### F-5：`result_gate` 声称已引入 `gap_from_result`，实际未导入

design D4 表述「`core/agent_runner/result_gate.py` 已同时引入二者（gap_from_result
与 parse_unattainable），无新增依赖」——核查 `result_gate.py:32-37` 只导入
`parse_unattainable`，未导入 `gap_from_result`。**处置**：本 SPEC 4.2 在 runner
侧接入 keep 判定时按需导入 `gap_from_result`（同 `core.run_task_track` 模块导入，
非新增依赖模块）；本项不构成行为缺陷，仅 design 描述与代码轻微不符。

### F-6：design「须加进 serialize 显式键表」表述与代码不符

design 3.2 原文含「MUST 补『daemon 重启后两字段保持』」+「加进 state_machine
显式键表」的表述；核查 `StateMachine.serialize`（state_machine.py:389-395）已有
「`_` 前缀内部字段全量透传」分支，`_retry_count`/`_merge_fp`/`_merge_streak`
同走此路，新字段 `_redispatch_same_cause_streak`/`_redispatch_cause_fp`
自动透传，**无需**改显式键表（design 已自行更正，见 design.md「已更正」注）。
本项仅为表述澄清，重启保持性测试仍按 spec 要求补充。

### F-7：同因指纹归一化粒度

design Open Questions「归因指纹的归一化规则具体到什么粒度（剔除哪些段）」：
以「同缺口的连续 partial」（归因文案 =「实现者申报未完成（status=partial）：X」，
缺口相同则文案逐字节一致）与「同一 merge 错误」两个样本校准。实现采用
`_merge_fingerprint` 同族手法 + 显式剔除易变段（run_id / 9 位以上数字时间戳 /
worktree 路径）。**风险**：归一化过度会把不同原因判为同因 → 以「不同因不误熔断」
回归用例锁定边界。

## 2. 实现过程追加（占位，收尾时填最终态）