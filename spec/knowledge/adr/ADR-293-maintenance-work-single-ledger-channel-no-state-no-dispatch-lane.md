# ADR-293：框架外工作记账走独立登记台账单通道——STATE 准入不扩展、登记型 run 不建执行车道

date: 2026-10-30
status: accepted

## Context

框架流水线只有 spec 全流程一种记账形态：spec done 后的延伸/维护型工作与散件没有认领出口。实证（2026-10-08 复核）：延伸提交 6f1042e（82 文件，含 19326 行中性化补丁）无任何 run 认领、STATE 未动；散件 `.fenix/bin/analyze_run_latency.py` 未跟踪且无归因——散件从产生即无主，告警无法路由认领、记账不可见、证据滞留。同时 STATE.md 写者是全量重写语义（`_admit_entry` 丢弃非 spec 条目），非 spec 记录混入 STATE 必被下个写者抹掉；未识别前缀的 run 一律落泛型「无主 agent」，告警归因与盘点视图均不可见。

## Decision

框架外工作的记账收口为单一登记通道，边界有三：

- 载体是项目级独立追加型文件（`.fenix/maintenance_log.jsonl`，`core/maintenance_ledger.py`），STATE.md 准入语义不扩展——凡「非 spec 生命周期的记录」一律不进 STATE，后续任何想让 STATE 承载非 spec 数据的诉求同型驳回，放宽须显式 supersede。
- 登记型 run 只做前缀识别与归因（真源表 `RUN_ID_AGENT_PREFIXES` + `admin_monitor` 消费表同步，遵循 ADR-129 双表语义分离），不派生实现/验证车道——台账型 run 是登记事实，不是可派发任务。
- 台账条目以可选 `run_id` 字段关联登记型 run，构成告警归因→台账复盘的引用闭环。

## Consequences

延伸/维护工作与散件从产生即有主：一行登记落账、run 可识别、告警可路由、复盘可反查。代价：台账在消费视图补齐前会退化为纯留痕（本裁定先保前缀归因闭环，盘点/消费视图按需扩展）；登记入口的 CLI/dashboard 挂接不在通道内，属后续按需扩展。若未来需要为维护型工作建执行通道，必须另立 SPEC 并论证为何不能走既有实现车道，不得复用本台账派发。
