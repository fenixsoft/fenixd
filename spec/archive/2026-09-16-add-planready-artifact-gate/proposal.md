# Proposal: add-planready-artifact-gate

## Why

2026-09-09 新验证流程（planner 出题→judge）首战白烧 7.5min/$2.28：planner-plan（deepseek-v4-flash）24 turns 只落盘 2/3 批场景、从未写 `.fenix-run-result.json`（status=plan-ready 契约文件，`agents/planner-plan.md` 第 4 步），exit 0 自然收工；runner 产物硬门对 planner-plan 只查 test_scenarios.json（注释明说「无 status 契约」）故放行 "succeeded"；pm_engine 读侧 primary 缺失回退主树共享文件撞 implementer 残留 status='success' → 旧码 return None 丢弃真实值 → ERROR「status=None」误归因降级 legacy verifier（再烧 12.6min/$2.48，报告框架合成）。fix-verdict-read-failclosed 已把读侧归因真实化（fail-closed），但**处置仍是降级、仍无出题重试**——planner 忘写 plan-ready 契约文件的结构缺口依然成立：该文件在硬门视野之外，planner 不写也能 "succeeded"。

## What Changes

- runner 产物硬门 `_check_agent_result_artifact`（`core/agent_runner/runner.py`）对 planner-plan **增加** `.fenix-run-result.json` 校验：存在/非空/合法 JSON/顶层 status ∈ 白名单（与 planner-judge 的 fix-verdict-read-failclosed D3 白名单校验同构，复用 `planner_result_status_whitelist`）；不满足抛 `AgentArtifactGateError`，自动落入既有瞬态退避重试通道（不新增重试机制，不消耗裁决重试预算）
- test_scenarios.json 的既有校验（存在/非空/mtime 新鲜/合法 JSON）保持不变，与新增校验**叠加生效**
- pm_engine 新验证流程降级 legacy verifier 时（`core/pm_engine/verification.py` 阶段1 判定点），降级原因与白烧代价（时长/成本）传入 legacy 链路，最终由 `core/verify_report.py` 在合成报告（及报告数据结构）中标注「本报告由框架合成（降级自新验证流程）+ 降级原因 + 被降级轮次的代价」，前端验证报告可见

## Capabilities

### New Capabilities
- `planready-artifact-gate`: planner-plan 产物硬门校验 plan-ready 契约文件——exit 0 但 `.fenix-run-result.json` 缺失/为空/非法 JSON/status 白名单外时，run 按瞬态失败走退避重试而非标记 succeeded
- `degrade-annotation`: 新验证流程降级 legacy verifier 后，框架合成报告必须标注降级原因与被降级轮次代价，不再静默合成

### Modified Capabilities

（无——judge 硬门与读侧 fail-closed 行为不变，本变更只扩展 planner-plan 分支与报告留痕）

## Impact

- `core/agent_runner/runner.py`：`_check_agent_result_artifact` planner-plan 分支扩展；`AgentArtifactGateError` 语义注释更新（plan 类型也含结果文件契约）
- `core/pm_engine/verification.py`：阶段1 降级判定点传递降级上下文（原因/时长/成本）
- `core/verify_report.py`：合成报告注入降级标注字段
- `core/dashboard/`（验证报告渲染侧）：降级标注字段透出（若报告结构新增字段，前端需兼容展示；无字段时降级标注随既有 summary 文本流动则零前端改动——以 design 决策为准）
- 测试：`tests/test_agent_runner*.py` / `tests/test_pm_engine*.py` / `tests/test_verify_report*.py` 对应分支覆盖
- 风险：硬门加严后，若 planner prompt 契约与硬门再次漂移（planner 被要求写 A、硬门查 B）会误拦健康轮次——以 `planner_result_path` 同源计算防漂移；重试通道预算上限既有机制兜底
