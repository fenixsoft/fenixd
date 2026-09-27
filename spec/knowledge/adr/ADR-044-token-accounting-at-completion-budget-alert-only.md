# ADR-044：token 计量收工单点采集，预算线只告警不冻结

date: 2026-09-06
status: accepted

## Context

run 的原始 usage 已落 `.fenix/runs/*.jsonl`（stream-json result.usage）但仅存于文件，无累计视图与预算语义；成本字段恒 $0.00（网关不回传 total_cost_usd），token 是唯一可靠的成本代理。

## Decision

- 采集单点 = agent_runner 收工处（result 对象在内存，最廉价）：usage 含 cache 分项累加进 STATE 内部字段（`_tokens_in` = input + cache_creation + cache_read；`_tokens_out` = output）；jsonl 保持原样作为审计事实源；异常无 usage 记 0 + DEBUG 日志。
- 验证链 LLM 增量（planner/judge）记 verify-progress 侧车 tokens.json，报告合成时求和「本链增量 token」；场景执行为纯 Python 无 LLM，不计。
- 预算键 `agents.token_budget_millions`（缺省 50，0=关闭）带 Dashboard 界面；80%/100% 两级告警用布尔内部字段一次性标记保证幂等不重复发；预算线只告警不自动冻结——冻结是重处置（需人工解冻），预算线是注意力触发器，超限处置归人工。
- cache_read 计入 input（宁可高估），分项在详情展示；存量 spec 从 0 起算，不回填历史 jsonl（回填污染预算语义）。

## Consequences

- 零流式计量的低成本可见性：收工采集 + 既有 STATE/dashboard 管道复用，无新增后台机制。
- usage 缺失的 run 少计，与 jsonl 考古偏差一致，可接受；不冻结可能显得弱，是有意取舍，收紧留待实测后另立项。
