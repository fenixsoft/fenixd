# Design: env-attribution-evidence-gate

## Context

judge（planner-judge 角色）在验证链中对场景失败做失败归因（env/product/flaky 等），归因产物为 judge_attribution.json（core/verify_engine/judge_files.py 写出与读取），由提示词模板 agents/planner-judge.md 约定判定标准，分类逻辑在 core/agent_runner/prompt_builder.py `_scenario_classified`（约 :3247，词表 :3242）。现状对 env 归因只要求 evidence 非空。

## Goals / Non-Goals

- Goals：env 归因的 accept 需要量测 + 窗外对照双证据；缺证降级 inconclusive 并接既有 recheck；产物 schema 可承载证据引用。
- Non-Goals：不改变 env-blocked 握手语义；不新建告警通道（复用 inconclusive_loop）；不涉及具体量测的采集实现（量测由 judge 在转录中引用现有观测）。

## Design

1. **提示词模板（agents/planner-judge.md:65-66）**：env 定义段改为要求「可复核环境量测（具体数值+来源）+ 验证窗口外对照样本」双要件，并给出反例说明（两轮同窗自测数值不构成对照）。
2. **分类门（主门 core/pm_engine/verification/verdict_evidence.py `_handle_scenario_requeue` 条目构造；辅门 core/agent_runner/prompt_builder.py `_scenario_classified`）**：对将被置 accept 的 env 归因条目做证据校验——优先校验条目新增的 measurement_refs/control_samples 结构化字段非空（judge 按提示词模板填充），缺失时回退检查 attribution 文本是否含量测数值模式与窗口外对照引用；校验不过则不落 accept，条目按既有 requeue 状态落盘（ATTRIBUTION_STATUS_REQUEUE，词表仅 accept/requeue，不新增第三状态），缺失项写入条目注记字段。辅门同步收紧 `_scenario_classified`（prompt_builder.py:3303）：env 条目缺证据字段不视为「已归因存档」，截断恢复不沿用、重试 judge 重裁决。
3. **schema（core/verify_engine/judge_files.py）**：条目新增可选字段 measurement_refs（量测引用列表）与 control_samples（对照样本引用列表）；写出侧随 accept 条目填充，读取侧缺失字段按空处理（向后兼容）。
4. **降级接线**：降级条目以 requeue 状态落盘即自然进入既有回炉重检闭环（verdict_evidence `_handle_scenario_requeue` → build_requeue_manifest → 轻量重合成 judge run 只重做 requeue 子集 → 回灌完整校验链，递归上限 blocked + admin 升级）；blocked-env 全批 inconclusive 通道（core/pm_engine/verification/escalation.py:402 `_handle_env_blocked_inconclusive`，重验上限 inconclusive_max_attempts 缺省 2 + 失败签名提前升级停车；event_bus.py:679 `_inconclusive_paused` 暂停守卫）语义不变，豁免握手不被触发。

## Risks / Trade-offs

- 证据校验为模式匹配（数值+引用存在性），可能漏判极端措辞——保守方向：宁降级不误 accept。
- recheck 通道复用既有 inconclusive_loop，需要确认其触发频次上限避免循环——沿用其现有配额/退避。
- 迁移期一次性回炉成本：启用时跨轮裁决缓存/历史 checkpoint 中不带新字段的 env 条目会被证据门降级回炉一次（轻量重合成 judge run，不重跑 tester），成本有界（回炉预算 + 查重递归上限 + inconclusive 重验上限 2/升级阈值 4），方向保守正确（宁重检不误 accept）。

## Migration

无破坏性迁移：schema 新增字段可选，旧 judge_attribution.json 可读；提示词模板变更即时生效于新 run。