## Why

2026-09-24 实证事故（add-code-review-concurrency-and-429-resilience）：implementer 收尾把
`.fenix/verify-progress/<spec>/quality-gates.json` 写成顶层平铺形态（漏了契约要求的
`{"gates": {...}}` 包裹层），读侧 `parse_quality_gates` 取 `file_data.get("gates")` 落空后把两项
**实际已通过**的 run 自查门判成 pending（detail 恒空串），UI 呈现「只过 4/6 且未过项零解释」；
宽松对账守卫当场发现了形态违规（daemon 日志 WARNING 两条）但按软约束设计只记日志放行，
人工全程无感。同一形态错误同时具备「结论丢失」「零解释」「无人看见」三个后果，需要机制面治理。

## What Changes

- 读侧平铺形态容错：`core/dashboard/data/quality_gates.py` 的 `parse_quality_gates` 在顶层缺
  `gates` 键、但顶层各值本身形似合法 gate 条目（值为 dict 且 `status` ∈ 枚举）时，按平铺形态
  采信——杜绝「写歪 = 结论全丢」。
- pending/unknown 兜底解释文案：六道门合成结果中 status 为 pending/unknown 且 detail 为空串的
  项，统一填充固定归因文案，UI 不再出现无解释的未勾选项（前端零改动，detail 透传即生效）。
- 宽松对账告警接入人工告警面：`core/agent_runner/result_gate.py` 的 `_check_quality_gates_soft`
  对三类形态违规（顶层缺 gates / 契约外 gate-id / status 枚举外，含 JSON 无法解析）在保留既有
  WARNING 日志的同时写 admin_alerts，dashboard 人工告警面板可见。**不改变「宽松对账 MUST NOT
  打回/不产生失败终态」的软约束边界，只加可见性不加强度。**

## Capabilities

### New Capabilities

- `quality-gates-form-tolerance`：quality-gates.json 平铺形态读侧容错（含形态判定边界与
  「文件损坏」语义的区分）。
- `quality-gates-explainability`：pending/unknown 门的兜底归因文案契约。
- `quality-gates-soft-gate-alerts`：宽松对账形态违规的人工告警可见性（可见性增强，不加强度）。

### Modified Capabilities

- `quality-gates-progress`（add-quality-gates-visibility，已归档）：读侧合成与落盘契约的
  容错性扩展；落盘契约本身（嵌套形态为唯一合法写法）不变，仅新增读侧兼容与可解释性。

## Impact

- 受影响代码：`core/dashboard/data/quality_gates.py`（读侧合成）、
  `core/agent_runner/result_gate.py`（对账告警）、`core/admin_store.py` 或 admin_alerts 写入
  通道（如需注册 signal_type）、对应测试文件（`tests/test_quality_gates_progress.py`、
  `tests/test_agent_runner_gate.py`）。
- 前端零改动：detail 文案由后端填充，经既有 `gateDetailText` 透传。
- 数据修复已人工完成（涉事文件已包层修复并验证 6/6），本 SPEC 只管机制面。
- 不改变：落盘契约（嵌套形态仍是唯一合法写法）、宽松对账不打回的软约束边界、
  六道门合成顺序与 done 计数口径。
