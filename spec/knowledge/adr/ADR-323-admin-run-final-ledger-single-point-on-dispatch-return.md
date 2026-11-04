# ADR-323：admin run 处置台账终态落账单点化——派发返回即落账、先于链闭环事件

date: 2026-11-04
status: accepted

## Context

处置链上线后每例链路由 admin 处置必然产出一假「处置中断」人工告警（首日 4/4 复现）：pending DISPOSITION 由派发方无条件落账，闭合责任却留在消费路径——只有 admin_monitor 直接路径 `_worker` 写 final 记录，链路径全部出口（closed/handoff/exhausted/deferred）无人闭合，pending 成为永久孤儿。「在各出口分别落账」的补法会把落账与分支判定交织，本缺口正是「注释声称副作用已落」这类出口散落写点漂移的产物。次生时序窗口：若落账晚于链 closed 事件，daemon 在两事件之间被杀会留下「链已闭环 + pending 孤儿」形态，孤儿看护必然误报。

## Decision

pending 的闭合收口为单点单时点：AdminStore `append_admin_final` 单源落账助手（final 字段形状一处定义；duck-typed 读 disp，admin_store 不反向依赖 agent_runner 避免环），admin_monitor 直接路径与链路径 `_run_admin_phase` 共用同一助手，禁止各自另写。落账时点钉死在 `run_administrator` 返回后、一切分支判定（handoff/越界复核/成功闭环/失败计点）之前——一次覆盖全出口，无出口遗漏面。时序不变式：final 落账先于链 closed 事件。append 失败 try/except 降级 WARN 留痕（含 run_id）不阻断链分支判定，pending 交孤儿看护既有语义兜底（宁多告警不静默）。不变式守卫：任何派发路径收尾后必须存在带该 run_id 的非 pending 处置记录，两路径产出字段形状一致性由契约测试钉死。

## Consequences

未来新增 admin 派发通道必须复用同一落账助手并在返回即落账，「消费路径负责闭合」的责任模型与出口散落落账形态属禁止复辟面；落账与链闭环事件之间不再存在孤儿窗口，daemon 任意时刻被杀台账至多落后一个已闭合事件；落账失败退化为「孤儿看护兜底 + 可能一条真告警」，接受宁多告警不静默的保守方向；字段形状演进须同步两路径契约用例（防族孪漂移）。绕开助手另写 final、或移动落账时点到分支判定之后，须显式 supersede。
