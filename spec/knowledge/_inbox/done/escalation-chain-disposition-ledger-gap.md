# 处置链路由 admin run 的 pending 台账永不闭合（「处置中断」告警结构性误报源）

## 背景

2026-11-03「Administrator 处置中断」人工告警一天 4 例（run …04385/…12861/…12913/…6474），
全部为 pending disposition 超 15 分钟 grace 后被 AdminMonitor 孤儿检测
（`_recover_orphaned_dispositions`）升级。取证发现 4 例同根因，且为结构性必然而非偶发：
当日恰是升级处置链（add-escalation-chain-admin-arbiter）上线首日，链路由 admin 处置
首次批量发生，每例链路由 admin run 都会复现本告警。

## 结论（当前事实）

- `run_administrator` 派发时无条件写 pending DISPOSITION 记录（core/agent_runner/maintenance_runs.py:346）。
  该记录的关闭责任分两条路径，只有一条尽了责：
  - **直接信号路径**：admin_monitor `_worker` 收尾写 final 记录（带 `admin_run_id`，
    core/admin_monitor.py:8214-8253）→ `_merge_admin_runs` 的 by_run 归并把该 run 判为已终结 →
    pending 不再孤儿。健康。
  - **链路由路径**：`_run_admin_phase` 成功后 `_close_chain_success` 只做解冻（status_after）、
    收口上升件、写链事件三件事（core/pm_engine/escalation_chain.py:1185-1218），`_process_item`
    见 `phase == "closed"` 直接 return（escalation_chain.py:736-737，注释声称「side-effects 已落」
    与事实不符）。**链全路径（closed/handoff/exhausted/deferred）都不写 final 处置记录、不关
    pending。** pending 自派发起即为永久孤儿。
- 孤儿 pending 的下游链：15 分钟 grace 后，孤儿检测扫到「pending 超时 + run 文件终态 + 链痕已
  闭环（2.1 链痕抑制不命中，因链在 success 时已清 in_flight）」→ 升级 critical 告警。
  即：**每例链路由 admin run（成功或转单）在派发 15 分钟后必然产出一条假「处置中断」**。
- 归因模板误导：`_orphan_run_attribution` 对任何 result 终态一律写「run 以 result 终态退出但
  处置未完成（非成功结论）」（core/admin_monitor.py:6764-6765），不读 result 的 success 子型。
  首例事件 run 实为 success 终态，文案与事实相反。
- 链成功路径不执行 choice：`_run_admin_phase` 对 disp.choice_id 只做越界复核（allowlist，
  escalation_chain.py:859-880），无 `_apply_choice_execution` 等效物。payload 型 choice
  （如 revise_scenario_reverify）的真实修复动作（成对写场景文件、spec 复位、重派 verifier）
  只有直接路径 `_worker` 会执行。若某信号仅链路由单通道处置，链闭环后修复动作被静默跳过，
  spec 停滞且零告警（比误报告警更重的功能缺口）。
- 首例事件（run …6474）的处置实际由孪生直接路径 run …6475（同 spec 并行 manual-intervention
  信号）等效执行成功，spec add-knowledge-inbox-pipeline 已 verified（14/14 场景 pass）。
  4 例告警的处置效果在链外均达成，全为假阳性中断；但机制层 pending 确实孤儿。
- 附带形态分歧：`_persist_choice_step_records` 写的逐动作 DISPOSITION 记录不带 `admin_run_id`
  （对比同秒 final 记录带）。逐动作记录若先于 final 落盘而 final 因故缺失，by_run 归并同样断裂。

## 证据

- 4 例 run 名下记录核对（.fenix/admin_alerts.json）：…04385/…12861/…12913/…6474 均
  「pending + escalation + escalated」三条、final 结果记录 0 条；对照组 …03779（直接路径）
  有 final 记录。
- 链台账（.fenix/escalation_chain_state.json）：4 个签名 admin_attempts 均 ≥1 且链均已闭环/转单；
  in_flight 空 → 2.1 链痕抑制不命中。
- 结构化日志（.fenix/logs/fenixd.log）：run …6474 于 14:39:17.997 落车道指标（administrator
  success）、14:39:18.005 链记「Admin 处置成功链闭环」，此后无任何 final 落账；14:42:36.576/.637
  孪生 run …6475 落逐动作记录（无 run id）+ final 记录（带 run id）；14:45:36 supervisor
  restart_request 重启（与本缺口无关——不重启告警同样会在 14:49:34+ 巡检触发）；14:51:35
  孤儿检测升级。
- 代码锚点：maintenance_runs.py:346（pending 写点）、escalation_chain.py:736-737（closed 早退）、
  escalation_chain.py:881-888（成功→闭环→return）、
  escalation_chain.py:1185-1218（_close_chain_success 副作用清单）、admin_monitor.py:6764-6765
  （归因模板）、admin_monitor.py:6558-6561 注释（by_run 归并语义：非 pending 记录带同 run id
  才算终结）。
