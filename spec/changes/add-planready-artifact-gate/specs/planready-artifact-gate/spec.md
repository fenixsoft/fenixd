# planready-artifact-gate Specification

## ADDED Requirements

### Requirement: planner-plan 产物硬门校验 plan-ready 契约文件

runner 产物硬门（`_check_agent_result_artifact`）对 `agent_type == "planner-plan"` 的校验 SHALL 为 test_scenarios.json 既有校验（存在/非空/mtime 新鲜/合法 JSON）**叠加** `.fenix-run-result.json` 校验：文件存在、非空、合法 JSON、顶层为对象且 `status` 字段取值 ∈ `planner_result_status_whitelist`。任一不满足 SHALL 返回失败归因文案（含具体文件路径与缺失语义），由调用方抛 `AgentArtifactGateError` 走既有瞬态退避重试通道——不新增重试机制、不消耗 validate_report 裁决重试预算。`.fenix-run-result.json` 路径 SHALL 经 `planner_result_path(project_root, spec_name, "planner-judge")` 同源计算（与 pm_engine 读侧 primary 路径一致，防双实现漂移）；不落盘到 worktree 相对路径。

#### Scenario: planner 未写结果文件被硬门拦截并重试

- **WHEN** planner-plan run 进程 exit 0 且 test_scenarios.json 合法落盘，但 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 不存在（模拟 2026-09-09 白烧事故：planner 只写场景文件未写结果文件）
- **THEN** 硬门返回失败归因（含「结果文件缺失」语义与 primary 路径），run 不被标记 succeeded，抛 `AgentArtifactGateError` 进入瞬态退避重试通道

#### Scenario: 结果文件 status 白名单外被拦截

- **WHEN** planner-plan run 进程 exit 0 且 `.fenix-run-result.json` 存在且合法 JSON，但顶层 status 为白名单外取值（如 `"success"`——implementer 共享文件残留的语义错位取值）
- **THEN** 硬门返回失败归因（含 `status='success' 不在白名单`），run 不被标记 succeeded，走退避重试

#### Scenario: 健康轮次双产物齐备放行

- **WHEN** planner-plan run 进程 exit 0，test_scenarios.json 合法落盘且 mtime 新鲜，`.fenix-run-result.json` 合法 JSON 且 status=`"plan-ready"`
- **THEN** 硬门返回 None（通过），run 标记 succeeded，pm_engine 读侧读到 plan-ready 正常进入场景验收

#### Scenario: 新鲜度守卫覆盖结果文件

- **WHEN** planner-plan run 进程 exit 0，但 `.fenix-run-result.json` mtime 早于本轮 attempt 启动时刻减宽限期（上一轮陈旧残留）
- **THEN** 硬门按「本轮零产物（陈旧残留）」返回失败归因，run 不被标记 succeeded（与 test_scenarios.json 的新鲜度校验同规则）

### Requirement: 硬门归因可诊断

硬门失败文案 SHALL 指明失败的具体文件与原因类别（缺失/为空/非法 JSON/顶层非对象/status 白名单外/陈旧残留），使重试后的 planner 轮次（若有 REPLAN_FEEDBACK 类反馈通道）与人工排查能直接定位——不得复现 2026-09-09「日志同时报读到 'success' 与 status=None」的自相矛盾归因。

#### Scenario: 归因含真实 status 值

- **WHEN** 硬门因 status 白名单外失败
- **THEN** 失败文案包含实际读到的 status 取值（如 `status='success'`），不丢弃真实值、不以 None 替代
