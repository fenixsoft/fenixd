# judge 修复预算口径统一

<!-- knowledge: capability=judge-repair-budget-alignment rev=1
     sources=spec/archive/2026-10-30-fix-judge-budget-counters-alignment -->

场景原地修复预算（episode 级）与 judge 重跑硬上限（生命周期累计）两套计数的口径统一：预算耗尽后修复通道持久关闭（跨重启），人工裁决上下文完整——「不再重入」承诺真正兑现。

## 规则

- **耗尽后无修复纯归因模式**：场景原地修复预算耗尽（含其后的排程重验 episode，无论是否经历 daemon 重启）后，judge 后续轮次以无修复纯归因模式运行——可输出 product-bug / test-defect / env 定性；test-defect 仅记录于裁决产物，MUST NOT 改写场景文件、MUST NOT 申报 scenario-repaired、MUST NOT 触发场景重执行重入。
- **耗尽状态以 STATE 持久字段为准**：修复耗尽状态读 `_scenario_repair_exhausted_rounds`（STATE 持久字段），跨 daemon 重启持久；唯一清零点 = verified 落定 + 人工 unfreeze_spec（清零集含修复耗尽计数）——人工解冻后后续验证 episode 的 judge 修复通道恢复正常（重新获得修复预算）。
- **机械受理门 fail-closed**：修复通道门挂在 scenario-repaired 申报受理点（改写场景文件前），MUST NOT 依赖 judge prompt 约束（prompt 层约束会被模型漂移突破）；受理门命中拒收时 MUST 提前退出裁决采纳尾段（error 留痕、spec 保持 testing），MUST NOT 返回 False——否则穿透 plan-ready/bug-found 守卫落到 verified 收敛点，未重执行即假收敛为 verified；拒收伴随 WARNING 留痕「修复预算已耗尽，转纯归因」。
- **纯归因模式不新增旗标**：无修复模式是「耗尽字段 ≥ 1 且非刚解冻」的推导态，MUST NOT 落新旗标（防双旗标漂移）；预算口径的计数留痕字段（生命周期修复申报轮数、耗尽后拒收轮数）与 `_judge_rerun_count` 同族（清零点同为 verified + 人工解冻），单点定义于 state_machine。
- **硬上限冻结告警附修复预算上下文**：`_judge_hard_cap_freeze` 冻结告警（description/evidence/recommended_action）附场景修复预算状态，三项各具名数据来源——①是否已耗尽（STATE 持久字段）；②生命周期累计修复申报轮数与耗尽后被拒轮数（受理门写点维护）；③最近一次修复申报摘要（judge 裁决产物，场景 id 级别）；MUST NOT 依赖日志回捞取数。人工裁决者能从告警直接判断「重跑超上限」由哪类重入贡献、剩余缺陷该走修复还是归因（recommended_action 按耗尽与否分叉）。
- **两套预算数值与语义不动**：场景修复预算数值与 per-episode 语义不变（人工解冻重获预算）；重跑硬上限保持生命周期累计语义。

## 溯源

- 2026-10-30 fix-judge-budget-counters-alignment（spec/archive/2026-10-30-fix-judge-budget-counters-alignment） — 新增本能力：预算耗尽后修复通道持久关闭（受理点机械门 + STATE 持久字段跨重启）、拒收出口契约（禁穿透假 verified）、硬上限冻结告警附三项具名修复预算上下文（动因实测：两套互不知情的预算下，重启后排程重验轮 judge 照样原地修复 8 场景申报 scenario-repaired，冻结告警看不出真实耗尽来源）
