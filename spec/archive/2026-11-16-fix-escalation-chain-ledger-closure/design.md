# 设计：处置链路由 admin run 的处置台账闭合

## Context

2026-11-03「处置中断」告警 4 例同根因取证（详见 proposal）：链路由 admin run 的
pending DISPOSITION（`run_administrator` 派发时无条件写，`maintenance_runs.py:346`）
在链路径上永远无人闭合——只有 admin_monitor 直接路径 `_worker` 写 final 记录
（`core/admin_monitor.py:8214-8253`，带 `admin_run_id`，是 `_merge_admin_runs`
by_run 归并判定「run 已终结」的依据）。`_process_item` 见 `phase == "closed"` 直接
return（`escalation_chain.py:736-737`）；`_close_chain_success` 只做解冻/收口上升件/
写链事件。次生缺口：链成功路径不执行 `choice_id`（只做越界白名单复核）。

首例事件（run …6474）的修复由孪生直接路径 run 等效完成、spec 已 verified，但机制层
缺口在：**每例链路由 admin 处置（成功/转单/耗尽）15 分钟后必然升级一条假人工告警**，
且 payload 型 choice 链上被静默丢弃。

既有相关能力页：escalation-chain（rev=4，链痕单源/deferred 留痕/配额语义）、
human-escalation-alerts（rev=5，链痕抑制前置/归因按终态实证）、admin-run-wrapup-contract
（处置记录先行契约——administrator 提示词硬约束，与本 SPEC 的框架侧落账互补不冲突）。

## Goals

1. 链派发的 admin run 在 `run_administrator` 返回后台账即时闭合——孤儿看护不再对
   链路由处置产出假「处置中断」。
2. 链成功路径的 payload 型 choice 真实生效，失败 fail-closed 不伪造闭环。
3. 孤儿升级归因能区分「真中断」与「落账缺失」，不再对 success 终态写反向文案。
4. 兜底：历史缺口/落账失败残留的「链已闭环 + final 缺失」孤儿由看护对账终结不升级。

## Decisions

### D1 落账写点单源：AdminStore 新增 final 落账助手（而非两处各写）

- 新增 `AdminStore` 方法（如 `append_admin_final(signal, disp, error_note="") -> bool`）：
  duck-typed 读 disp（getattr，**不 import agent_runner**——admin_store 不反向依赖
  agent_runner，避免环），字段形状一处定义（对齐 `_worker` final append 全字段）。
- 直接路径 `_worker` 与链路径 `_run_admin_phase` 均改调该助手；契约测试比对两路径
  产出记录字段形状一致（防族孪漂移，对齐 code-review ledger hygiene 族既有教训）。
- append 失败 try/except：返回 False + WARN 留痕（含 run_id），调用方不阻断——
  pending 保持由孤儿看护既有语义兜底（宁多告警不静默）。

### D2 落账时点：run_administrator 返回后、分支判定前

- `_run_admin_phase` 的 attempt 循环内，`run_administrator` 一返回即落账（先落账、
  后 handoff/越界复核/成功闭环/失败计点判定）——三分支（closed/handoff/exhausted）
  一次覆盖，不留出口遗漏面。
- 不选「各出口分别落账」：出口判定与落账交织易在后续演进中再漂移（本缺口即
  「注释声称副作用已落」的实证）。
- 与 D2 配套的时序不变式：final 落账先于链 closed 事件——daemon 在两事件间被杀时，
  台账已闭合（pending 不孤儿），链 in_flight 残留由既有 6h reap 清理，2.1 链痕抑制
  在 reap 前兜住，无新增告警窗口。

### D3 choice 执行机器抽离：新模块 + AdminMonitor 委托（而非链上复制或构造 Monitor）

- `_apply_choice_execution` 与 `_persist_choice_step_records` 的执行核心抽为新模块
  `core/admin_choice_exec.py` 模块级函数（`execute_choice_for_disposition(signal, disp,
  logger)` / `persist_choice_step_records(store, signal, signal_rec, disp, outcome,
  logger)`），AdminMonitor 同名方法委托之——直接路径行为回归零变化（既有用例全绿为锚）。
- 链 closed 出口调用同一模块级函数：越界白名单复核（既有，保持先行）→ 执行 →
  逐动作落账 → 成功才 `_close_chain_success`；白名单内 choice 的执行失败/执行器
  主动跳过（载荷缺失等）fail-closed：不写 chain-closed、不计成功，该件按链既有
  失败语义处理（计一次失败，error 注入链事件）。白名单外 choice 不属此列——既有
  越界复核转单、不计失败（与能力规格「白名单外 choice 保持转单」Scenario 同口径）。
- 不选「链构造 AdminMonitor 单例调用方法」：Monitor 构造面远宽于所需（巡检状态/
  冷却/执行器池），引入隐性耦合；不选「链上复制执行逻辑」：与人工 alert-resolve、
  直接路径三处同源纪律（`execute_adjudication_choice` 单执行机器）冲突。
- escalate / handoff 出口不执行 choice（转单/上升语义，修复责任随件流转），与
  能力规格「closed 出口执行」范围一致。
- 已知共存行为（非本 SPEC 引入）：同 spec 并行直接路径 run 的同款 choice 可能重复
  执行（首例事件实证 2 次），执行器自带写前快照+失败回滚，验证已端到端通过——
  不在本次治理面。

### D4 归因子型：读 result 事件 subtype

- `_orphan_run_attribution` 的 `ev_type == "result"` 分支读 `subtype` 字段：
  `success` → 新归因「处置结论成功但 final 处置记录缺失（落账缺口或收尾中断）——
  先核对处置台账与链事件再定处置」；其余子型 → 既有文案不变。
- 不选「success 子型直接抑制升级」：落账缺失时人工仍应知情（可能伴随真收尾中断），
  只修正归因方向性，不动升级行为。

### D5 chain-closed 对账兜底：链事件补结构字段 + 看护升级前联查

- 写侧：链 admin 相事件（chain-closed/chain-handoff）的 `run_id` 字段落实际
  admin run id（现取 `arbiter_run_id` 对 admin 相恒空）；arbiter 相事件语义不变。
- 读侧：孤儿看护 pending 分支（终态确认、interrupted 豁免、链痕抑制均未命中后）
  升级前按 run_id 联查链事件台账（arbiter_ledger jsonl，既有单源）——命中
  chain-closed/chain-handoff → 补终结记录（result=resolved，actions_taken 注明
  「链侧已闭环但 final 记录缺失，由看护对账补记」）不升级；查询异常按零命中放行
  （fail-open，对齐链痕抑制既有降级口径，宁多告警不漏告警）。
- 查询口放链单例（`chain_events_for_run(run_id)` 只读聚合，monitor 不直读台账内部
  结构——对齐既有链痕抑制查询口「数据属主封装」决策：monitor 侧经链单例函数内
  lazy import 既有形态，`core/admin_monitor.py:6691` 先例）。

## Risks

- **双路径字段漂移复发**：D1 单源 + 契约测试比对两路径记录形状钉死。
- **choice 执行在链线程内耗时**：链 worker 本就以同步方式跑完整个 admin agent
  （分钟级），执行器秒级动作不改变量级；互斥/单飞守卫均在派发侧不受影响。
- **import 环**：新模块对 dashboard data 层沿用函数内 lazy import 既有形态；
  escalation_chain 对新模块同为 lazy import。
- **fail-open 面扩大**：D5 查询异常放行升级——保守方向与链痕抑制/链缺席口径一致，
  宁多告警不静默漏。
- **存量孤儿**：4 例告警对应 stale pending 已被「升级即终结」记录闭合，无残留
  待迁移面；本 SPEC 落地后首例验证以守卫测试承载。
