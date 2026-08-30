# Proposal: add-verdict-evidence-taxonomy

## Why

验证裁决的失败归类语义不清且证据不全：v2-config-page 第 2 轮验证 17 场景中 11 个 warning 既不算过也不算败、无收敛压力，且 failed 场景在 report.json 中没有结构化失败断言证据（assertion_results 为空），事后考古与自动处置都缺依据（复盘改进点 4）。噪音分流能力（improve-verify-adjudication 已有雏形）需要强制化与证据化。

## What Changes

- 裁决输出强制四分类：每个非 PASS 场景 MUST 归为 `product-bug`（产品缺陷）/ `test-defect`（测试用例自身错误）/ `flaky`（不稳定重试可过）/ `env`（环境问题）之一
- 每个非 PASS 分类 MUST 附结构化证据：失败断言（type/selector/期望/实际）、截图路径、关联场景步骤——写入 report.json 对应场景条目（现状为空的问题修复）
- warning 状态语义收敛：warning 仅允许 `flaky`/`env` 两类使用（不阻塞）；`product-bug`/`test-defect` 一律 failed
- 同一场景连续 2 轮 warning → 自动升级为 triage 告警（human-escalation-alerts，措辞含场景与轮次），不得继续悬置

## Capabilities

### New Capabilities
- `verdict-evidence-taxonomy`: 裁决分类强制化、结构化证据与 warning 收敛升级

### Modified Capabilities

（无——report.json 结构为字段扩展（场景条目增加 classification/evidence），parse_verdict 兼容读取为实施任务，非规格级变更）
