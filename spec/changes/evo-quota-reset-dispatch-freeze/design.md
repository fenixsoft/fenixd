# Design: quota-reset-dispatch-freeze

## Context

现状：core/agent_runner/provider_circuit.py:84-95 三种冷却全为固定时长，429 报文中的重置时间戳（「限额将在 … 重置」，实测报文该时刻为 naive 无时区，如「2026-11-10 10:43:04」）无人解析；provider 冷却检查与廉价失败挂点在 core/agent_runner/runner.py——链选择 `_select_chain_candidate`（约 :2494）跳过冷却候选，全候选被跳过走 chain_exhausted 廉价失败分支（约 :6321-6367，既有语义即「不启动进程、不计入 spec 重试消耗」）；core/pm_engine/dispatch/queue.py 当前无 provider 级检查点（如需 queue 层拦截属新增分支而非扩展既有检查）；infra breaker 通道（core/pm_engine/infra_breaker.py）明示仅 v1 接驳 spec-review 链路，link 为运行时字符串键可扩展。2026-11-09~11-10 事件：12.5h 窗口 13/13 连灭。

## Goals / Non-Goals

- Goals：重置时刻驱动的 provider 冻结；冻结期派发廉价失败；告警单条化。
- Non-Goals：不改自省调度（last_run_date 防风暴设计保持）；不改既有固定冷却时长语义（只取 max）；不做多 provider 配额预测。

## Design

1. **解析（provider_circuit.py）**：RATE_LIMIT（code 1310 等）失败分支解析报文重置时间戳；解析成功→冷却到期 = max(现值, 重置时刻)；解析失败/无时间戳→维持现状固定冷却。冻结状态沿用既有 provider 冷却结构（switch_cooldown_until 字段），不新增存储形态。
   - **时钟口径（评审补）**：switch_cooldown_until 为单调秒（monotonic，provider_circuit.py:807-809 docstring 明示），报文重置时刻为 naive 墙钟，两者不可直接 max。约定：naive 时间戳按宿主本地时区解读为 aware 时刻（对齐仓库时区分层约定），经「墙钟差值」换算为单调截止（同 runner.py:5204 既有换算先例「时钟口径统一」）；解读出的重置时刻早于当前时刻（已过期）按解析失败处理，回退固定冷却。
2. **闸门消费（runner.py、queue.py）**：派发前既有 provider 冷却检查处，命中冻结即廉价失败（返回明确原因，不计失败重试与预算计数），并经 infra breaker 通道维护单条汇总告警（扩展 breaker 的 link 维度以支持 provider 级条目）。
   - **触发边界（评审补）**：廉价失败仅当候选链无可用候选（全链冻结/冷却）时触发——既有 chain_exhausted 分支（runner.py:6321-6367）已承载该语义；链上存在可用候选时维持既有链前进（runner.py:2494-2496 链选择跳过冻结候选），MUST NOT 因单一候选冻结拦截整个派发（否则打破 add-provider-failover 既有切换语义）。
3. **告警生命周期**：汇总告警在冻结解除时走既有告警收口路径；重复命中只更新计数不新建。
   - **收口挂点（评审补）**：本代码库无到期事件分发机制（provider_circuit.py:1356-1361 先例明示核销 MUST 复用过期分支、不做轮询/异步扫描）——provider 冻结解除的告警核销挂闸门查询路径的到期翻转（对齐 transient break 到期核销先例：查询侧发现已到期即收口）。冻结真源为 provider_circuit 进程内存态；breaker link 条目仅承载告警呈现与命中计数，daemon 重启后冻结随内存态清零，由下一次 429 失败重新解析重建（breaker 条目经到期翻转自然收口）。

## Risks / Trade-offs

- 重置时间戳格式变化：解析失败回退固定冷却，行为不劣于现状。
- 廉价失败与预算记账的边界：明确「拦截不计失败」，避免冻结期反而烧预算计数；单测覆盖。

## Migration

无数据迁移；解析即时生效于新失败事件。