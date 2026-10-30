## Why

add-command-center 事故（2026-10-26）：planner-plan run 被 supersede 后，worktree_manager 的内存 spec 锁（`spec:agent_type`）不释放，7169s 后重出题派发按「adaptive backoff early give-up」0.013s 秒败 → 新验证流程**静默降级 legacy verifier**（日志仅第 2 次降级提示）→ legacy 通道 verdict 协议失配，间接触发 39 分钟验证两轮作废。锁泄漏把「一次性失败」放大为「验证通道静默劣化」。

## What Changes

- **run 终态释放锁**：run 到达失败类终态（框架终态单源 `RUN_TERMINAL_EVENT_TYPES`：非成功 result / error / interrupted / cancelled / frozen-terminated / gate-blocked）时释放其持有的 `spec:agent_type` 内存锁，锁记录增 owner run 归属；原地重试中间弃置件 superseded 不在此列（由陈锁清扫兜底，见下条）
- **陈锁存活清扫**：acquire 因「already active」早退前核对持锁 run 存活性，持锁主已确认死亡（run 记录末行属死亡判据集 ∪ superseded 弃置件 / 记录缺失且窗口已过）则清扫陈锁并放行本次派发
- **legacy 降级前置门**：同一 spec 新验证流程连续第 2 次失败降级时不再自动派发 legacy verifier，改 blocked + 升级告警（附降级原因链），杜绝连续静默劣化

## Capabilities

### New Capabilities
- `worktree-lock-terminal-release`: run 终态释放 worktree spec 锁与陈锁存活清扫——supersede/终止后的同 agent_type 重派不再被陈锁秒败
- `legacy-degrade-prerequisite-gate`: 新验证流程连续降级熔断——同一 spec 第 2 次降级转人工，不自动重降

### Modified Capabilities

## Impact

- `core/worktree_manager/lifecycle.py`：锁记录结构（owner run）、终态释放 API（扩展既有 `release_spec_lock`）、acquire 早退段存活清扫
- `core/worktree_manager/locks.py`：`_register_spec_locks` 登记写点 owner 适配
- `core/pm_engine/engine.py`：降级决策点（新验证流程失败 → 降级段，约 ：2893-2936）加连续降级熔断
- `core/agent_runner/runner.py`：run 终态收尾链（终态落账收口段）挂释放调用、`create()` 调用点传 owner run_id
- `core/state_machine.py`：unfreeze_spec 清零集扩展（熔断计数清零）
- 新增 `tests/test_worktree_lock_terminal_release.py`；`tests/` 既有 worktree/降级相关用例回归
