# Design: env-attribution-evidence-gate

## Context

judge（planner-judge 角色）在验证链中对场景失败做失败归因（env/product/flaky 等），归因产物为 judge_attribution.json（core/verify_engine/judge_files.py 写出与读取），由提示词模板 agents/planner-judge.md 约定判定标准，分类逻辑在 core/agent_runner/prompt_builder.py `_scenario_classified`（约 :3247，词表 :3242）。现状对 env 归因只要求 evidence 非空。

## Goals / Non-Goals

- Goals：env 归因的 accept 需要量测 + 窗外对照双证据；缺证降级 inconclusive 并接既有 recheck；产物 schema 可承载证据引用。
- Non-Goals：不改变 env-blocked 握手语义；不新建告警通道（复用 inconclusive_loop）；不涉及具体量测的采集实现（量测由 judge 在转录中引用现有观测）。

## Design

1. **提示词模板（agents/planner-judge.md:65-66）**：env 定义段改为要求「可复核环境量测（具体数值+来源）+ 验证窗口外对照样本」双要件，并给出反例说明（两轮同窗自测数值不构成对照）。
2. **分类门（core/agent_runner/prompt_builder.py `_scenario_classified`）**：当归因类别为 env 且结论为 accept 时，对 evidence 做证据校验：检查是否含量测数值模式与对照样本引用（对照样本 = 窗口外轮次/历史轮次引用）；校验不过则把该条归因改写为 inconclusive（status=inconclusive，附缺失项说明），不落 accept。
3. **schema（core/verify_engine/judge_files.py）**：条目新增可选字段 measurement_refs（量测引用列表）与 control_samples（对照样本引用列表）；写出侧随 accept 条目填充，读取侧缺失字段按空处理（向后兼容）。
4. **降级接线**：inconclusive 归因复用 core/alert_lifecycle.py:89,164 与 core/event_bus.py:433 `_handle_env_blocked_inconclusive` 的既有通道——归因条目 status=inconclusive 时走 recheck，不进入豁免握手分支。

## Risks / Trade-offs

- 证据校验为模式匹配（数值+引用存在性），可能漏判极端措辞——保守方向：宁降级不误 accept。
- recheck 通道复用既有 inconclusive_loop，需要确认其触发频次上限避免循环——沿用其现有配额/退避。

## Migration

无破坏性迁移：schema 新增字段可选，旧 judge_attribution.json 可读；提示词模板变更即时生效于新 run。