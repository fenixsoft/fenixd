# Proposal: add-judge-artifact-gate

## Why

2026-09-08 `add-draft-promotion-gate` 验证裁决事故：planner-judge（deepseek-v4-flash @ inferaiapi 网关）调查 27 分钟后遭遇网关流截断（同 message id 重复出现、文本句中截断、`stop_reason: end_turn`），CLI 以 exit 0 退出被框架判为成功，但 report.json 增强与结果文件**双缺失**。`validate_report` 兜底发现 10 项不合规后触发「重试 judge 一次」，重试恰被 frozen 旗标拦截，被误计为二次失败 → spec blocked + critical 告警（verdict_evidence_invalid），人工裁决成本高。

统计：当天该 spec 共 4 次 planner-judge run，2 次同签名挂掉（宣布「现在增强 report.json」后会话即止 / 调查完成后流截断）。根因是**成功判定只看进程退出码，不校验产物存在性**——「exit 0 但零产物」滑过所有防线，直到下游 validate_report 才以「产物不合规」的面目出现，浪费了失败重试预算与裁决语义。

## What Changes

1. **结果文件硬门（fail-closed）**：`agent_runner` 对 `planner-judge` 与 `planner-plan` run 的成功判定从「进程 exit 0」升级为「exit 0 **且**结果文件落盘且非空」。无产物 → 判瞬态失败，走既有原地退避重试通道（fix-provider-transient-backoff），**不**进入 `validate_report` 的「重试一次」预算（该预算专用于「产物存在但不合规」）。
2. **judge 逐场景增量写盘**：planner-judge prompt（agents/planner-judge.md）步骤 4 改为**逐场景 checkpoint**——每归类完一个非 PASS 场景立即原子写回 report.json（覆盖写），流截断时已归因场景不丢失；步骤顺序调整为「先完成全部场景增强落盘，再做调查/复现」，明确「先落盘再深入」纪律。

## Capabilities

### New Capabilities

（无——加固既有验证裁决链，不新增能力）

### Modified Capabilities

- `verdict-evidence-taxonomy`（spec/archive/…/add-verdict-evidence-taxonomy）：裁决证据链的产物存在性由下游 validate_report 兜底前移为 runner 侧硬门；judge 产物写盘从一次性覆盖改为逐场景 checkpoint。

## Impact

- `core/agent_runner/runner.py`（成功判定处按 agent_type 追加结果文件校验；复用瞬态退避重试通道）
- `agents/planner-judge.md`（步骤 4 逐场景 checkpoint 化、步骤顺序调整）
- `core/agent_runner/prompt_builder.py`（如需把 result_path 校验规则同步注入 prompt 契约段）
- `tests/test_agent_runner_gate.py`（新增：exit 0 无产物 → 瞬态重试判定；截断部分产物 → 已归因场景保留）
- 风险面：planner-plan 同受硬门约束——plan 阶段产物契约（test_scenarios.json）在冻结复用轮不重写，硬门需对「冻结复用跳过出题」的轮次豁免（复用轮 planner-plan 不派发，天然无影响，实现时确认派发条件即可）。
