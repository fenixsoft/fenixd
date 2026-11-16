# design — judge-rerun-cap-repair-exempt

## 机制选型

镜像既有 inconclusive 预算隔离范式（core/pm_engine/verification/judge_gate.py:539-553 旗标分流 + :762-861 独立计数器 helper，2026-11-16 实测锚点）：主计数 `_judge_rerun_count` 语义不变（生命周期累计、三处清零点不变），新增旁路豁免额度，不动「唯一清零点」主账语义（state_machine.py:799-807 字段注释）。

## 数据结构

STATE 新字段（state_machine.py 字段单点区，JUDGE_RERUN_COUNT_FIELD 常量段 :799-811 同段）：

- `_judge_cap_repair_exempt_avail: bool`——待消费豁免旗标
- `_judge_cap_exempt_used: int`——生命周期豁免消费计数（封顶默认 3）

## 写点与消费点

1. 置位：`_record_repair_claim`（core/pm_engine/verification/pipeline.py:3977 一带）受理修复申报的同一原子写中，若 `_judge_cap_exempt_used < 3` 则置 `_judge_cap_repair_exempt_avail=True`。
2. 消费：judge_gate.py 派发门 bump 后判定段（评审实测 :587-592 预算近满压缩分支与 :594-596 常规分支两处 bump+冻结判定；:456-459 已漂移为轮内停派告警段）——**两处冻结判定同接豁免**：冻结阈值判定为真（压缩分支 `count > base + _JUDGE_CONSERVE_REMAINING`、常规分支 `count > _MAX_JUDGE_RERUNS`）且旗标在位时：清旗标、`_judge_cap_exempt_used += 1`、放行本次派发（不进 `_judge_hard_cap_freeze`）；inconclusive 分流分支（:539-553，独立计数器）不涉及豁免。主计数不回退（保持 verdict_evidence.py:1486 注释的「失败链中计数跨轮累计直至上限」语义）。注：豁免消费点先于 verdict 稳定性复用检查（:598），复用命中轮可能零真实派发即消费豁免——与既有 bump 语义同口径，生命周期封顶 3 次兜底，接受该损耗。
3. 清零链三处成对清除（与 `_judge_rerun_count`/`_judge_cap_frozen` 同族）：
   - verified 落定：core/pm_engine/verification/verdict_evidence.py:1505-1511 verified 清零原子写同段
   - 人工 unfreeze：core/state_machine.py:2992-2993 `unfreeze_spec` 清零集
   - admin 清零：core/dashboard/data/admin_actions.py:1766-1767
4. evidence 轨迹：`_judge_hard_cap_freeze`（评审实测 def :639，evidence 拼装段 :711-717 一带）追加读 verify-progress 下 verdict_stability.json 的 rounds[].failed_ids 序列（读侧复用 core/verify_report.py `read_verdict_stability` :1776，缺失/损坏 fail-open 返回 None → 降级省略、不阻塞冻结；侧车仅保留最近两轮，verify_report.py:1813/1864——轨迹至多两个轮次点，验收按此口径；评审时 pipeline.py:1508 引用作废，pipeline.py 全文无 verdict_stability 引用）。

## 防毒约束

state_machine.py:746-748（`_scenario_repair_exhausted_rounds` 字段注释「MUST NOT 在 admin 处置复位 / daemon 恢复 / 中间转换清零——否则『毒 spec 借每次 admin 复位重置计数 → 无限循环』敞口复开」）与 :841-845（inconclusive 隔离字段同族口径）明文。本设计遵守：

- 豁免旗标唯一置位点是修复申报受理记账（机械、有 impl run 事实支撑），不接任何人工/复位通道；
- 生命周期消费封顶（默认 3 次），即便反复申报修复也至多放行 3 次超额派发；
- 主计数永不因豁免回退，防毒 spec 无法借豁免把主账归零。

## 与在途 SPEC 的协同

- fix-verify-loop-convergence D5「硬上限诊断贯通」动同一冻结写点（其 design.md:104-110）：其向 error/evidence 注入 repeat/零实质变更诊断，本案 evidence 追加失败集轨迹——同写点合并实现，evidence 键名空间错开（`fail_history_trajectory` vs 其诊断键），无语义冲突。
- 其 repeat 闸门与实质变更判定不消费本案新字段；本案不触其判据与 VERDICT_CLASSES 词表。
- 消费侧 core/pm_engine/arbiter.py:97、core/dashboard/data/adjudication_choices.py:270 已登记 judge_rerun_cap 信号（评审实测：原引用 core/adjudication_narrative.py:137 已随 ede2a5342「写侧退役」删除，作废），evidence 增字段对透传零改动。

## 测试策略

- 豁免放行路径：构造 count 达 5 + 修复申报受理 → 下一轮派发放行、旗标消费、主计数照常累计；
- 封顶路径：消费 3 次后第 4 次申报不置旗标、超上限即冻结；
- 清零链回归：verified / unfreeze_spec / admin 清零三点后两新字段归零；
- evidence 轨迹：冻结 evidence 含 failed_ids 序列；侧车缺失时降级不报错。