# Tasks: fix-graceful-shutdown-agents

## 1. agent_runner 关闭语义改造

- [x] 1.1 重写 `agent_runner.wait_for_running_agents`：关闭时对所有在跑 agent 立即 SIGTERM（不做逐 agent 300s 串行等待），随后统一等待 ≤`AGENT_TERMINATE_GRACE_SECONDS`（10s）缓冲，窗口内未退出的 agent 用 SIGKILL 兜底；总时长不随 agent 数线性增长
- [x] 1.2 新增常量 `AGENT_TERMINATE_GRACE_SECONDS = 10`（模块级，测试可注入），确保缓冲窗口可被测试覆写
- [x] 1.3 被终止的每个 agent 在 SIGTERM 后立即向 run 文件追加 interrupted 记录：`{"type": "interrupted", "reason": "daemon shutdown", "by": "agent_runner"}`（复用 `append_run_line`，单行原子追加）
- [x] 1.4 确认 `fenixd.py` shutdown 调用点（`agent_runner.wait_for_running_agents(timeout=300)`）语义适配新行为；shutdown 期间禁止派发新 agent 的既有逻辑（`pm_engine.shutting_down`）保持有效，无需改动

## 2. AdminMonitor 孤儿检测识别 interrupted

- [x] 2.1 `_recover_orphaned_dispositions` 在 pending 超时判定升级前，增加 run 文件检查：读取 `.fenix/runs/<admin_run_id>.jsonl`，检测是否含 `type == "interrupted"` 记录（runs 目录路径从 agent_runner 的既有约定解析，必要时注入 `runs_dir`）
- [x] 2.2 run 含 interrupted 标记：追加 final disposition 记录（`status="interrupted"`）终结该 run，且**不**产生人工升级告警（复用 73f0fb6 的"终结即 final"机制，保证下轮巡检跳过）
- [x] 2.3 run 文件不存在或读不到 interrupted 标记：维持现有"疑似 daemon 崩溃"升级兜底，升级同时追加终结记录（保持防循环告警行为）

## 3. 测试

- [x] 3.1 `test_agent_runner` 新增：shutdown 时在跑 agent 收到 SIGTERM、10s 缓冲内未退者被 SIGKILL、run 文件写入 interrupted 标记、已完成 agent run 不写标记、多 agent 并行终止（缓冲区注入短值避免真实等待）
- [x] 3.2 `test_admin` 新增：run 含 interrupted + pending 超时 → 终结且无升级告警；run 无标记/repo 文件缺失 + pending 超时 → 升级兜底；升级伴随终结记录（无重复升级）
- [x] 3.3 运行全量测试套件（`pytest` 至少覆盖 `tests/test_agent_runner.py` 与 `tests/test_admin.py`）全部通过

## 4. 集成验证

- [x] 4.1 在模拟场景验证关闭链路：存在在跑 agent 时触发 daemon 优雅退出（如写 `.fenix/restart_request` 走 supervisor，或在测试目录手动 SIGTERM daemon），确认 agent 被终止、run 文件含 interrupted 标记、关闭总耗时 < 60s（不触发 supervisor SIGKILL）
- [x] 4.2 确认 supervisor 行为不变（未修改 `bin/fenixd_supervisor.py`），60s 窗口保持，清理 `.fenix/restart_request` 流程正常