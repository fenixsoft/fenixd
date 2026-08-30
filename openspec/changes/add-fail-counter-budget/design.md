# Design: add-fail-counter-budget

## Context

原地打回机制（add-inplace-bug-repair）的 `_verify_fail_rounds` 在打回重派路径上被隐式归零：修复轮完成走 ready→implementing 收工时，既有 `update_spec({"_retry_count": 0, ...})` 模式连带覆盖了计数语义（00:20 config 打回日志显示「第 1 轮失败」即为归零后重新计数）。3 轮闸门的意图是「连续修不好就找人工」，但实现把「修→验→修」的每个局部循环都当成了新一轮。run 级重试（max_retries=3）只约束单次派发的 attempt，跨修复轮无总量概念。

## Goals / Non-Goals

- Goals：计数只在 PASS 归零；per-spec 实现 run 总预算封顶；配置键带 Dashboard 界面（框架铁律）
- Non-Goals：不改 3 轮升级闸门本身的告警内容与解冻流程；不引入新状态机状态；不统计验证链 run 次数（验证成本由 scenario-freeze 控制）

## Decisions

### D1 归零点唯一化：验证 PASS 一处
全仓 grep `_verify_fail_rounds` 的写点，移除打回重派/修复收工路径上的归零（或显式排除），保留 PASS 推进处（verified 采纳）的单点归零。实现 run 收工处的 `_retry_count: 0` 保留（那是 run 级 attempt 计数，语义不同）——用字段级更新避免连带覆盖。

### D2 预算计数点：implementer 派发时递增
`_impl_run_budget_used` 在 `_run_agent_worker` implementer 分支启动时 +1 并持久化（跨重启有效）。检查点在重派决策处（打回重派、失败重试重派）：`used >= budget` → blocked + 告警（`signal_type="impl_budget_exhausted"`）。已启动的 run 正常跑完并 merge（沉没成本不浪费），只是不再自动开新一轮。

### D3 预算值配置化 + 界面同步
`agents.impl_run_budget` 缺省 4（配置读取走既有 `_get_config`）。Dashboard config 页在既有配置编辑区新增该键的数值输入（min 1 / max 10 校验），保存走既有写入 + 30s 热更新链路——满足「新增配置键必须带界面」铁律。

### D4 告警与解冻沿用既有闸门通道
预算耗尽与 3 轮冻结同构：blocked + `_send_human_escalation_alert`。人工处置（改计数/预算或直接推进状态）即可解冻，不新增人工流程。

## Risks / Trade-offs

- 复杂但合法的 spec 可能在 4 次内修不完 → 预算可配置（1-10），耗尽后人工可调大预算再解冻，代价可控
- 首次实现也计入预算，重灾 spec 的修复空间变 3 轮 → 与 3 轮验证闸门量级一致，故意的收敛压力
- 两个计数器（验证轮数 / 实现次数）并存增加心智负担 → 语义不同（修不好 vs 修不完），告警分别措辞，Dashboard 报告中分列展示

## Migration Plan

1. 计数归零点清理 + 预算字段/闸门 + 配置键（一次提交）
2. Dashboard config 页编辑入口（同提交或紧随）
3. 存量 spec 的 `_impl_run_budget_used` 从 0 起算（不回填历史）
无数据迁移。

## Open Questions

（无）
