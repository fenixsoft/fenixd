## Why

daemon 优雅退出时 `wait_for_running_agents(timeout=300)` 会对每个在跑 agent 最多等待 300s（fenixd.py:249），而 supervisor 的 SIGTERM→SIGKILL 窗口固定 60s（fenixd_supervisor.py:81-85）。两者不匹配导致：只要重启瞬间有 agent 在跑，daemon 必被 `kill -9`，在跑 agent 的 run 丢失最终结果。对 admin agent 而言，被中断后 disposition 停留在 pending，AdminMonitor 孤儿检测将其升级为"疑似 daemon 崩溃"的人工告警——improve-dashboard-sections 事件因同一 run 反复升级 3 次（13:21/14:47/17:34）即根源于此（supervisor.log 中 60s SIGKILL 模式已出现 5 次）。

修复方向：不是让 supervisor 等更久，而是让 daemon 不再等待——优雅退出时主动终止在跑 agent 并向 run 文件写入 interrupted 标记，快速退出；同时孤儿检测识别 interrupted 标记，将"已知中断"与"疑似崩溃"区分开。

## What Changes

- **agent_runner 关闭语义变更**：`wait_for_running_agents` 从"每 agent 等待 ≤300s"改为"terminate 流程"：对所有在跑 agent 发 SIGTERM → 同步向各自 run 文件追加 interrupted 标记 → 等待 ≤10s 优雅缓冲 → 未退出的 SIGKILL。daemon 优雅退出总耗时压至秒级（≪ supervisor 60s 窗口）。
- **run 文件 interrupted 标记**：被终止的 run 在 `.fenix/runs/<run_id>.jsonl` 末尾追加 `{"type": "interrupted", "reason": "daemon shutdown", "by": "agent_runner"}`，供后续巡检/诊断区分"被打断"与"异常/崩溃"。
- **AdminMonitor 孤儿检测降噪**：`_recover_orphaned_dispositions` 检测 pending 超时前，先查对应 run 文件是否含 interrupted 标记；含标记 → 判定已知中断，直接终结 pending disposition 且不产生人工升级；无标记且 pending 超时 → 维持现有升级兜底（疑似崩溃）。
- **supervisor 不改**：60s 窗口保持，daemon 快速退出后窗口足够宽裕。
- 附带的诊断收益：被打断的普通 agent（impl/verify/planner）run 也有 interrupted 标记，后续调试免去"run 无结果=异常"的猜测。

## Capabilities

### New Capabilities
- `agent-shutdown-interrupt`: daemon 优雅退出时对在跑 agent 的中断语义——SIGTERM 主动终止、10s 缓冲、SIGKILL 兜底、run 文件写入 interrupted 标记，保证重启不丢不确定结果、不拖慢退出。

### Modified Capabilities
- `human-escalation-alerts`: 孤儿检测产生人工升级告警的条件收窄——pending disposition 对应的 run 文件含 interrupted 标记（已知中断）不再升级；仅"无标记 + 超时"按疑似崩溃升级。

## Impact

- `core/agent_runner.py`：`wait_for_running_agents` 重写为 terminate 流程；新增 interrupted 标记写入（append_run_line 复用）。
- `core/admin_monitor.py`：`_recover_orphaned_dispositions` 增加 run 文件状态读取与判定；可能需传入 runs_dir 路径。
- `tests/`：`test_agent_runner.py`（shutdown terminate 行为）、`test_admin.py`（interrupted 识别与兜底升级）新增用例。
- 行为影响面：daemon 每次重启不再有最长 300s 的关停等待（重启更快）；被打断 agent 的 run 文件多一条 interrupted 记录（JSONL 兼容，既有读取不受影响）。