# design — judge-rerun-cap-repair-exempt

## 机制选型

镜像既有 inconclusive 预算隔离范式（core/pm_engine/verification/judge_gate.py:439-459 旗标分流 + 601-623 独立计数器）：主计数 `_judge_rerun_count` 语义不变（生命周期累计、三处清零点不变），新增旁路豁免额度，不动「唯一清零点」主账语义（state_machine.py:735-738 注释）。

## 数据结构

STATE 新字段（state_machine.py 字段单点区，:695-697 同段）：

- `_judge_cap_repair_exempt_avail: bool`——待消费豁免旗标
- `_judge_cap_exempt_used: int`——生命周期豁免消费计数（封顶默认 3）

## 写点与消费点

1. 置位：`_record_repair_claim`（core/pm_engine/verification/pipeline.py:3977 一带）受理修复申报的同一原子写中，若 `_judge_cap_exempt_used < 3` 则置 `_judge_cap_repair_exempt_avail=True`。
2. 消费：judge_gate.py:456-459 bump 后判定段——`count > _MAX_JUDGE_RERUNS` 且旗标在位时：清旗标、`_judge_cap_exempt_used += 1`、放行本次派发（不进 `_judge_hard_cap_freeze`）。主计数不回退（保持 verdict_evidence.py:1437-1439 注释的「失败链中计数跨轮累计直至上限」语义）。
3. 清零链三处成对清除（与 `_judge_rerun_count`/`_judge_cap_frozen` 同族）：
   - verified 落定：core/pm_engine/verification/verdict_evidence.py:1455-1456 同段
   - 人工 unfreeze：core/state_machine.py:2752-2753 `unfreeze_spec` 清零集
   - admin 清零：core/dashboard/data/admin_actions.py:1746-1747
4. evidence 轨迹：`_judge_hard_cap_freeze`（judge_gate.py:499-583）evidence 拼装段追加读 verify-progress 下 verdict_stability.json 的 rounds[].failed_ids 序列（读侧复用 core/verify_report.py 既有读取；侧车为 episode 作用域、verified/reset 会清空，pipeline.py:1508，缺失时降级省略）。

## 防毒约束

state_machine.py:676-677 明文「MUST NOT 在中间转换清零——防毒 spec 借复位重置计数无限循环」。本设计遵守：

- 豁免旗标唯一置位点是修复申报受理记账（机械、有 impl run 事实支撑），不接任何人工/复位通道；
- 生命周期消费封顶（默认 3 次），即便反复申报修复也至多放行 3 次超额派发；
- 主计数永不因豁免回退，防毒 spec 无法借豁免把主账归零。

## 与在途 SPEC 的协同

- fix-verify-loop-convergence D5「硬上限诊断贯通」动同一冻结写点（其 design.md:104-110）：其向 error/evidence 注入 repeat/零实质变更诊断，本案 evidence 追加失败集轨迹——同写点合并实现，evidence 键名空间错开（`fail_history_trajectory` vs 其诊断键），无语义冲突。
- 其 repeat 闸门与实质变更判定不消费本案新字段；本案不触其判据与 VERDICT_CLASSES 词表。
- 消费侧 core/pm_engine/arbiter.py:97、core/adjudication_narrative.py:137 已登记 judge_rerun_cap 信号，evidence 增字段对透传零改动。

## 测试策略

- 豁免放行路径：构造 count 达 5 + 修复申报受理 → 下一轮派发放行、旗标消费、主计数照常累计；
- 封顶路径：消费 3 次后第 4 次申报不置旗标、超上限即冻结；
- 清零链回归：verified / unfreeze_spec / admin 清零三点后两新字段归零；
- evidence 轨迹：冻结 evidence 含 failed_ids 序列；侧车缺失时降级不报错。