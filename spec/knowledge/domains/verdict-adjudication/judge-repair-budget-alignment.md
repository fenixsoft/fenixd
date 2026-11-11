# judge 修复预算口径统一

<!-- knowledge: capability=judge-repair-budget-alignment rev=2
     sources=spec/archive/2026-10-30-fix-judge-budget-counters-alignment,spec/knowledge/_inbox/done/judge-pure-attribution-testing-hold-orphan-1111.md -->

场景原地修复预算（episode 级）与 judge 重跑硬上限（生命周期累计）两套计数的口径统一：预算耗尽后修复通道持久关闭（跨重启），人工裁决上下文完整——「不再重入」承诺真正兑现。

## 规则

- **耗尽后无修复纯归因模式**：场景原地修复预算耗尽（含其后的排程重验 episode，无论是否经历 daemon 重启）后，judge 后续轮次以无修复纯归因模式运行——可输出 product-bug / test-defect / env 定性；test-defect 仅记录于裁决产物，MUST NOT 改写场景文件、MUST NOT 申报 scenario-repaired、MUST NOT 触发场景重执行重入。
- **耗尽状态以 STATE 持久字段为准**：修复耗尽状态读 `_scenario_repair_exhausted_rounds`（STATE 持久字段），跨 daemon 重启持久；唯一清零点 = verified 落定 + 人工 unfreeze_spec（清零集含修复耗尽计数）——人工解冻后后续验证 episode 的 judge 修复通道恢复正常（重新获得修复预算）。
- **机械受理门 fail-closed**：修复通道门挂在 scenario-repaired 申报受理点（改写场景文件前），MUST NOT 依赖 judge prompt 约束（prompt 层约束会被模型漂移突破）；受理门命中拒收时 MUST 提前退出裁决采纳尾段（error 留痕、spec 保持 testing），MUST NOT 返回 False——否则穿透 plan-ready/bug-found 守卫落到 verified 收敛点，未重执行即假收敛为 verified；拒收伴随 WARNING 留痕「修复预算已耗尽，转纯归因」。
- **纯归因模式不新增旗标**：无修复模式是「耗尽字段 ≥ 1 且非刚解冻」的推导态，MUST NOT 落新旗标（防双旗标漂移）；预算口径的计数留痕字段（生命周期修复申报轮数、耗尽后拒收轮数）与 `_judge_rerun_count` 同族（清零点同为 verified + 人工解冻），单点定义于 state_machine。
- **硬上限冻结告警附修复预算上下文**：`_judge_hard_cap_freeze` 冻结告警（description/evidence/recommended_action）附场景修复预算状态，三项各具名数据来源——①是否已耗尽（STATE 持久字段）；②生命周期累计修复申报轮数与耗尽后被拒轮数（受理门写点维护）；③最近一次修复申报摘要（judge 裁决产物，场景 id 级别）；MUST NOT 依赖日志回捞取数。人工裁决者能从告警直接判断「重跑超上限」由哪类重入贡献、剩余缺陷该走修复还是归因（recommended_action 按耗尽与否分叉）。
- **纯归因收尾即无驱动悬置（设计内挂起）**：judge 以无修复纯归因模式收尾（受理门拒收 scenario-repaired 申报、场景文件不改写、不重入执行、保持 testing）后，车道不再调度任何后续驱动——不重验入队、不派发、不升级；spec 从此悬置 testing 态属设计内挂起（无主动续接的时序缺口），不是 daemon 故障。隐式续接依赖孤儿态探测的分钟级短阈值唤起 Administrator，零动作 resolved 处置走复位直通道——分支已合并则 `transition_gate(testing)` 幂等 + 清 error + verifier 重验入队（见 [孤儿状态信号](../run-resilience/orphaned-state-signal.md)）；处置时无需重启、无需手动 reset。
- **悬置形态鉴别与零动作结案**：该悬置形态的鉴别特征为四项齐备——spec error 字段为「修复预算已耗尽……保持 testing」拒收留痕文案、`_judge_rerun_count` 触顶、judge run 已归档、verify-progress mtime 停在 judge 轮结束时刻；命中即零动作写 resolved 结案，勿开启新诊断分支。
- **两套预算数值与语义不动**：场景修复预算数值与 per-episode 语义不变（人工解冻重获预算）；重跑硬上限保持生命周期累计语义。

## 溯源

- 2026-10-30 fix-judge-budget-counters-alignment（spec/archive/2026-10-30-fix-judge-budget-counters-alignment） — 新增本能力：预算耗尽后修复通道持久关闭（受理点机械门 + STATE 持久字段跨重启）、拒收出口契约（禁穿透假 verified）、硬上限冻结告警附三项具名修复预算上下文（动因实测：两套互不知情的预算下，重启后排程重验轮 judge 照样原地修复 8 场景申报 scenario-repaired，冻结告警看不出真实耗尽来源）
- 2026-11-11 judge-pure-attribution-testing-hold-orphan-1111（spec/knowledge/_inbox/done/judge-pure-attribution-testing-hold-orphan-1111.md） — 折叠交互排查结论：纯归因收尾终态不再调度任何后续驱动，testing 悬置为设计内挂起（孤儿探测 + Administrator 零动作 resolved 复位续接），登记四项鉴别特征与「命中即零动作结案」处置口径
