# Design: add-cost-observability

## Context

run 的原始 usage 已落在 `.fenix/runs/*.jsonl`（stream-json 的 result.usage），但只在文件里；agent_runner 收工时有 result 对象在内存（含 usage），是最廉价的采集点。STATE.md 内部字段（`_` 前缀）机制由 add-inplace-bug-repair 落地（state_machine 写回），累计字段可复用同机制。Dashboard 已展示 `_verify_fail_rounds` 等内部字段（治理区），token 展示挂同一数据管道。成本字段 $0.00 是网关（cc-switch）不回传 total_cost_usd 所致。

## Goals / Non-Goals

- Goals：收工时零成本采集、STATE 持久、Dashboard/报告可见、80%/100% 预算告警（不自动冻结）
- Non-Goals：不做实时流式计量（收工采集足够）；不做跨 spec 汇总报表；不做预算自动熔断（人工决策）；不改网关

## Decisions

### D1 采集点：agent_runner 收工处
`_run_agent_worker` 拿到 result 后（is_success 或失败分支统一）提取 `result.usage`（含 cache 分项），累加写 STATE（`_tokens_in` = input + cache_creation + cache_read；`_tokens_out` = output）。jsonl 不再是唯一事实源但保持不动（审计用）。run 异常无 usage → 0 + DEBUG 日志。

### D2 展示层挂既有管道
STATE 内部字段 → dashboard/data.py 已有读取机制 → SPEC 详情治理区新增一行（M 输入 / M 输出，超 1000 展示 G？——不，token 场景 M 封顶即可，>1000M 显示 G）。验证报告由 verify_report.py 合成器在汇总表加一行「本链增量 token」（从 verify-progress 侧车读取，见 D3）。

### D3 验证链增量统计：verify-progress 侧车
`.fenix/verify-progress/<spec>/tokens.json` 记录每轮验证各 LLM run（planner/judge）的 usage；报告合成时求和。场景执行为 Python 无 LLM，不计。

### D4 告警幂等：阈值越过标记
`_token_warn_80` / `_token_alert_100` 布尔内部字段做一次性标记，收工检查处触发后置位；不重复发。预算 0=关闭（跳过检查）。告警走 `_send_human_escalation_alert`（提醒级用现有 severity 分级）。

### D5 配置键 + 界面
`agents.token_budget_millions` 缺省 50；Dashboard config 页数值输入（0-1000，0 提示=关闭），保存走热更新链路——满足配置键必须带界面的铁律。

## Risks / Trade-offs

- usage 缺失的 run 少计 → 与 jsonl 考古一致偏差，可接受；异常早夭的 run 本身消耗小
- 100% 告警不冻结可能显得弱 → 有意为之：冻结是重处置（需人工解冻），而预算线更多是「注意力触发器」；若实测后想收紧，后续可加配置开关
- cache_read 计入 input 会放大数字（缓存读便宜但不为零）→ 保守计入（宁可高估），分项在详情 tooltip 展示

## Migration Plan

1. agent_runner 采集 + STATE 字段 + Dashboard 展示（一次提交）
2. verify-progress 侧车 + 报告小节
3. 预算配置 + 告警 + config 页入口
存量 spec 从 0 起算（不回填历史 jsonl——历史总量已知，回填会污染预算语义）。

## Open Questions

（无）
