# planner 出题产物硬门（planready-artifact-gate）

<!-- knowledge: capability=planready-artifact-gate rev=1
     sources=spec/archive/2026-09-16-add-planready-artifact-gate -->

planner-plan run 的产物硬门：出题轮只有同时交付场景文件与 plan-ready 结果文件才算成功，缺件即按瞬态失败重试。

## 规则

- runner 产物硬门 `_check_agent_result_artifact` 对 `agent_type == "planner-plan"` 的校验由两段叠加：
  - test_scenarios.json：存在、非空、mtime 新鲜、合法 JSON；
  - `.fenix-run-result.json`：存在、非空、合法 JSON、顶层为对象且 `status` 取值 ∈ `planner_result_status_whitelist`。
- 任一段不满足 → 硬门返回失败归因（含具体文件路径与缺失语义），调用方抛 `AgentArtifactGateError`，run 复用瞬态退避重试通道；不引入独立重试机制，不消耗 validate_report 裁决重试预算。
- `.fenix-run-result.json` 路径经 `planner_result_path(project_root, spec_name, "planner-judge")` 同源计算，与 pm_engine 读侧 primary 路径一致，不落盘 worktree 相对路径。
- 新鲜度守卫覆盖结果文件：`.fenix-run-result.json` mtime 早于本轮 attempt 启动时刻减宽限期（上一轮陈旧残留）→ 按「本轮零产物（陈旧残留）」失败，与场景文件同规则。
- 硬门失败归因必须可诊断：文案指明失败的具体文件与原因类别（缺失/为空/非法 JSON/顶层非对象/status 白名单外/陈旧残留）；status 白名单外时文案包含实际读到的取值，不丢弃真实值、不以 None 替代。

## 关键行为

- planner-plan exit 0 但结果文件缺失 → run 不标记 succeeded，抛 `AgentArtifactGateError` 进瞬态退避重试。
- 结果文件 status 为白名单外取值（如 implementer 共享文件残留的 `"success"`）→ 同样拦截并重试。
- 双产物齐备（场景文件新鲜落盘 + status=`"plan-ready"`）→ 硬门通过，run 标记 succeeded，pm_engine 读侧读到 plan-ready 进入场景验收。

## 溯源

- [2026-09-16 2026-09-16-add-planready-artifact-gate](spec/archive/2026-09-16-add-planready-artifact-gate/) — 新增 planner-plan 分支的 `.fenix-run-result.json` 硬门校验（status 白名单、新鲜度守卫、读侧同源路径）与可诊断归因要求。
