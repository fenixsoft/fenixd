# provider 配额重置感知与派发冻结
<!-- knowledge: capability=provider-quota-awareness rev=1 sources=spec/changes/evo-quota-reset-dispatch-freeze -->

供应商返回携带重置时间戳的限流响应（429 配额耗尽）时，框架解析重置时刻并把该 provider 的派发冻结至重置时刻——小时级配额窗口内不再按固定冷却反复「到期→再试→再死」白烧。

## 规则

- 解析与冻结：provider 返回携带重置时间戳的限流响应（RATE_LIMIT 类，如 code 1310「限额将在 … 重置」）时，冷却到期时间取 max(既有固定冷却, 报文重置时刻)，重置时刻前 MUST NOT 对该 provider 派发新 run；重置时刻早于既有固定冷却到期时按固定时长执行，不因重置时刻提前；报文无可解析的重置时间戳（格式变化或缺失）或解读出的时刻已过期时，回退既有固定冷却，行为不劣于无解析形态。
- 时钟口径：报文重置时刻为 naive 墙钟，按宿主本地时区解读为 aware 时刻、经墙钟差值换算为冷却单调截止（冷却真源 `switch_cooldown_until` 为单调秒，两种时钟不可直接比较）；解读出的重置时刻早于当前时刻按解析失败同判回退固定冷却。
- 闸门触发边界：派发闸门廉价失败仅当该派发候选链无可用候选（全链冻结/冷却）且冷却候选中存在配额冻结（重置时刻已知）时触发；链上仍存在可用候选时维持既有链前进语义（跳过冻结候选、选用可用候选），MUST NOT 因单一候选冻结拦截整个派发；空链（无 provider 分配的默认网关路径）与全链冷却但无配额冻结（普通 switch 冷却）均不进本闸门、走既有 chain_exhausted 语义。闸门判定链异常 fail-open 放行——闸门故障 MUST NOT 阻塞派发主链。
- 廉价失败语义：冻结期命中的派发不启动真实 run、不计入失败重试与预算计数；chain_exhausted 失败归因注入配额冻结注记（provider 与重置时刻清单），派发器读侧据此识别配额冻结形态。
- 告警单条化：不逐 run 产生独立失败告警；每个冻结 provider 只维护一条汇总告警（signal_type `provider_quota_freeze`，含重置时刻与命中计数），重复命中只更新计数与证据不新建；同步经 infra breaker 通道按运行时字符串键 `quota-freeze:<provider>` 记账（link 维度扩展，既有 spec-review 用法不受影响）。
- 收口挂到期翻转：本代码库无到期事件分发机制——汇总告警核销与 breaker link 复位挂配额冻结闸门查询路径的到期翻转（查询侧发现 provider 已不在 switch 冷却即收口并复位，未来再冻结重新起算），不做轮询/异步扫描；watch 表空时零开销。
- 状态生命周期：冻结真源为 provider_circuit 进程内存冷却结构（`switch_cooldown_until`），daemon 重启随内存态清零，由下一次限流失败重新解析重建；汇总告警在册表与命中计数同为进程内存态。
- 适用面：限流冷却与配额冻结为 provider 级共享记账，dispatch attempt 环与八条 LLM 车道候选环（见 [failover-dispatch](failover-dispatch.md)、[maintenance-lane-provider-failover](maintenance-lane-provider-failover.md)）共用同一解析与冻结判据，两环链选择均跳过冻结候选。

## 代码锚点

- 解析与冷却取 max：`core/agent_runner/provider_circuit.py`（`parse_quota_reset_epoch`、限流冷却记账 `reset_epoch` 入参）
- 派发闸门与汇总告警：`core/pm_engine/dispatch/queue.py`（`_quota_frozen_candidates`、`_record_quota_freeze_hits`、`_upsert_quota_freeze_alert`、`_sweep_expired_quota_freeze_alerts`）
- 两环冻结记账与 chain_exhausted 注记：`core/agent_runner/runner.py`（`provider_chain_freeze_report` 委托、链推进冷却记账两注入点）
- 守卫测试：`tests/test_quota_reset_dispatch_freeze.py`

## 溯源

- 2026-11-17 evo-quota-reset-dispatch-freeze（spec/changes/evo-quota-reset-dispatch-freeze/） — 新建本页：限流报文重置时刻解析（naive 本地时区解读+墙钟差换算单调截止、冷却取 max 固定冷却）、全链无可用候选时的派发廉价失败（配额冻结归因注记、不计失败与预算）、单条汇总告警（infra breaker link 维度扩展）与闸门查询路径到期翻转收口
