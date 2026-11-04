# 提案：处置链路由 admin run 的处置台账闭合（fix-escalation-chain-ledger-closure）

## Why

2026-11-03「Administrator 处置中断」人工告警一天 4 例（run …04385 / …12861 / …12913 / …6474），
取证为**同一结构性根因**且每例链路由 admin run 都会复现：

- `run_administrator` 派发时无条件写 pending DISPOSITION（`core/agent_runner/maintenance_runs.py:346`），
  但只有 admin_monitor 直接路径 `_worker` 收尾写 final 记录（带 `admin_run_id`，
  `core/admin_monitor.py:8214`）；
- 链路由路径全出口（closed / handoff / exhausted / deferred 中实际派发的前三者）**都不写 final
  记录、不关 pending**——`_process_item` 见 `phase == "closed"` 直接 return
  （`core/pm_engine/escalation_chain.py:736`），`_close_chain_success` 只做解冻/收口上升件/写链事件；
- pending 永久孤儿 → 15 分钟 grace 后孤儿看护照章升级假「处置中断」（链痕已闭环，
  2.1 抑制不命中）；归因模板把任何 result 终态一律写「非成功结论」
  （`core/admin_monitor.py:6764`），不读 success 子型——首例 run 实为 success，文案与事实相反。

次生缺口（更重）：**链成功路径不执行 choice**——`_run_admin_phase` 对 `disp.choice_id` 只做
越界白名单复核，无 `_apply_choice_execution` 等效物。payload 型 choice（如
revise_scenario_reverify）的真实修复动作（成对写场景文件、spec 复位、重派 verifier）只有
直接路径会执行。单通道链路由处置成功 = 链闭环但修复静默跳过、spec 停滞且零告警。
首例事件的修复实际由孪生直接路径 run（…6475，manual-intervention 信号）等效完成，掩盖了该缺口。

影响面：链上线（add-escalation-chain-admin-arbiter）后**每例链路由 admin 处置必然产出一
条假人工告警**（已实证 4/4），且 payload 型 choice 在链上被静默丢弃。不修则告警噪音与
链闭环可信度持续恶化。

## What Changes

- **链侧 final 落账单点**：`_run_admin_phase` 在 `run_administrator` 返回后、后续分支判定前，
  立即写 final DISPOSITION 记录（字段形状与直接路径 final append 一致，含 `admin_run_id` /
  `result` / `choice_id` / `choice_payload` 等）；写点单源（直接路径与链路径共用同一落账助手，
  字段形状一处定义），append 失败 try/except 降级留痕不阻断。
- **链成功路径 choice 执行**：closed 出口在 `_close_chain_success` 前执行注册表 choice
  （复用与人工 alert-resolve、直接路径同一执行机器，抽为可直接调用的模块级助手；
  AdminMonitor 方法委托不复制逻辑）；越界白名单复核保持先行，执行结果 fail-closed 语义与
  直接路径同款（失败不伪造闭环——链事件记执行失败，该件按链失败语义处理）。
- **归因模板补 success 子型**：`_orphan_run_attribution` 对 result 终态读子型——success
  写「处置结论成功但 final 处置记录缺失（落账缺口或收尾中断），先核对处置台账与链事件」，
  非 success 保持现文案。
- **看护 chain-closed 兜底**：链事件写侧把 admin run id 落入链事件的 `run_id` 结构字段
  （现为空、只在文案里）；孤儿看护 pending 分支升级前查链事件——同 run_id 存在
  chain-closed/chain-handoff 事件时补终结记录不升级人工（fail-open：查询异常照常升级）。

## Capabilities

- escalation-chain（既有能力，MODIFIED）：链上 admin run 的终态落账契约与 choice 执行语义
- human-escalation-alerts（既有能力，MODIFIED）：归因子型与 chain-closed 对账兜底

## Impact

- 代码：`core/pm_engine/escalation_chain.py`（落账 + choice 执行 + 事件 run_id 字段）、
  `core/admin_monitor.py`（归因子型 + pending 分支兜底查询 + choice 执行机器抽离委托）、
  落账/执行助手的新家模块
- 测试：`tests/test_escalation_chain.py`、`tests/test_admin_disposition_reschedule.py`、
  choice 执行助手相关测试
- 行为：链路由 admin 处置完成后台账即时闭合（假告警消失）；payload 型 choice 链上真实生效；
  孤儿升级归因可区分「真中断」与「落账缺失」
- 不变式（守卫钉死）：任何经链派发的 admin run 在 `run_administrator` 返回后必须存在带其
  run_id 的非 pending 处置记录
