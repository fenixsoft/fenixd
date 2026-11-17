# judge 重跑硬上限的修复推进豁免
<!-- knowledge: capability=judge-rerun-budget rev=1 sources=spec/changes/evo-judge-rerun-cap-repair-exempt -->

spec 级 judge 重跑硬上限（`_MAX_JUDGE_RERUNS=5`）的修复推进豁免额度：修复申报受理授予一次性超额派发放行，接近真实收敛点的修复链不再被计数冻结打断；冻结告警附失败集轨迹供人工解冻决策。轮内派发治理见 [judge-rerun-governance](judge-rerun-governance.md)，修复预算口径见 [judge-repair-budget-alignment](judge-repair-budget-alignment.md)。

## 规则

- 置位唯一源：修复申报受理（`_record_repair_claim` 同一原子写）时，若 spec 生命周期豁免消费计数未达封顶（`JUDGE_CAP_EXEMPT_MAX`，缺省 3）则置待消费豁免旗标；每次申报至多置一枚、消费即清。旗标 MUST NOT 接受任何人工或复位通道置位（对齐防毒约束：旗标只绑真实修复申报记账，不接 admin 处置/daemon 恢复/中间转换）。
- 消费与放行：judge 派发门 bump 后冻结阈值判定为真（预算近满压缩分支 `count > base + 压缩余量`、常规分支 `count > 硬上限 5`，两处同接豁免）且旗标在位时消费豁免——清旗标、消费计数 +1、放行本次派发（不进 `_judge_hard_cap_freeze`）；判定短路保证未超上限不消费（旗标保留待后续轮）；inconclusive 分流分支（独立计数器）不涉及豁免。
- 消费写失败口径：清旗标失败按未消费处置、走既有冻结路径（fail-closed——冻结误触好过豁免失控放行）；清旗标成功后的消费计数 bump 失败仅 WARNING 留痕、不回滚放行（计数下偏至多损失一次封顶额度，由封顶兜底）。
- 主计数语义不变：豁免轮 `_judge_rerun_count` 照常累计、MUST NOT 回退（保持「打回轮计数跨轮累计直至上限」语义）；其生命周期累计与既有三清零点语义均不变。
- 清零链成对清除：豁免旗标与消费计数随 verified 落定、人工 unfreeze_spec、admin 手动清零三类终态清零点成对清除（与 `_judge_rerun_count` / `_judge_cap_frozen` 同族）。
- 封顶终局：消费计数达封顶后受理点不再置位，超上限恢复现行冻结流程（error、`_judge_cap_frozen`、升级告警均不变）。
- 已知损耗口径：豁免消费点先于 verdict 稳定性复用检查，复用命中轮可能零真实派发即消费豁免——与既有 bump 语义同口径，由生命周期封顶兜底，设计内接受。
- 冻结告警附失败集轨迹：`_judge_hard_cap_freeze` evidence 除既有修复预算三项上下文外，追加 verdict_stability 侧车的轮内 failed_ids 序列与当轮 pass/failed 统计（键 `fail_history_trajectory`，与在途诊断增强键名空间错开）；侧车仅保留最近两轮，轨迹至多两个轮次点；侧车缺失/损坏时该段降级省略、不阻塞冻结本身。人工解冻决策据此直接判断失败集是否收缩。

## 代码锚点

- 派发门豁免消费与 evidence 轨迹：`core/pm_engine/verification/judge_gate.py`（`_consume_judge_cap_repair_exempt`、`_judge_hard_cap_freeze`）
- 置位点：`core/pm_engine/verification/pipeline.py`（`_record_repair_claim` 受理原子写）
- STATE 字段与 unfreeze 清零集：`core/state_machine.py`（`JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD` / `JUDGE_CAP_EXEMPT_USED_FIELD` 单点定义）
- verified 清零：`core/pm_engine/verification/verdict_evidence.py`；admin 清零：`core/dashboard/data/admin_actions.py`
- 守卫测试：`tests/test_judge_cap_repair_exempt.py`（豁免放行/封顶/三清零链/evidence 轨迹四组行为）

## 溯源

- 2026-11-17 evo-judge-rerun-cap-repair-exempt（spec/changes/evo-judge-rerun-cap-repair-exempt/） — 新建本页：修复申报受理置一次性推进豁免（两处冻结判定同接、消费封顶 3、主计数不回退、三类终态清零点成对清除）与冻结告警 evidence 附失败集轨迹。动因实测：修复闭环后的首轮裁决恰被计数冻结打断（redesign-chain-panel-ui 单次验证链 40.64 美元 + Arbiter 裁决再耗 4.56 美元，历史同形态 4 次 episode 复发）
