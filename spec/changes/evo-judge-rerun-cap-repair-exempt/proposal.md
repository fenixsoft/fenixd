# judge-rerun-cap-repair-exempt

## Why

judge 重跑硬上限（`_MAX_JUDGE_RERUNS = 5`，core/pm_engine/verification/judge_gate.py:46）为纯生命周期累计：`_judge_rerun_count` 仅 bump 与冻结早退（judge_gate.py:701-742），清零点仅 verified 落定、人工 unfreeze、admin 清零三处，无任何「有产出修复推进」的进度感知。修复链型 spec 在接近真实收敛点时被计数冻结打断，每次冻结消耗一次 Arbiter/人工裁决：

- redesign-chain-panel-ui（2026-11-10）：第 6 轮裁决 18/22 → 修复闭环 → 修复后引擎轮 20/22（残留 2 场景为上轮 4 场景真子集），冻结恰好落在修复闭环后的首轮裁决轮界（fenixd.log 16:00:50.598Z）。本次验证链 40.64 美元 / 18.58M input tokens（STATE `_cost_usd`、`_judge_token_delta`），Arbiter 冻结裁决两 run 再耗约 4.56 美元。
- 历史复发 4 个 spec episode：add-freeze-stop-inflight-agents（2026-09-21，76 美元/80M token，spec/changes/fix-verify-loop-convergence/proposal.md:3）、potplayer-base（2026-10-03，core/state_machine.py:764 注释）、add-command-center（2026-10-27 同日 3 次冻结，.fenix/admin_alerts_archive.jsonl 行 485/486/491）、redesign-chain-panel-ui（2026-11-10）。

另两处放大器：(1) bump 发生在 verdict 稳定性复用检查之前（judge_gate.py:456 先于 460），连零真实派发的复用判定也烧账；(2) 冻结 evidence 只拼修复预算三字段（judge_gate.py:552-558），人工解冻决策拿不到失败集改进轨迹。

## What Changes

- **修复推进豁免额度**：修复申报受理（`_record_repair_claim`，core/pm_engine/verification/pipeline.py）时置一次性豁免旗标；judge 派发门 bump 后判定超上限时，若旗标在位则消费豁免、放行本次派发（该轮不触发硬上限冻结）。镜像 inconclusive 预算隔离的旗标分流 + 独立计数器范式（judge_gate.py:439-459、601-623）。豁免生命周期总消费次数封顶（默认 3 次），防毒 spec 无法借复位无限循环（对齐 state_machine.py:676-677 防毒约束：旗标只绑真实修复申报记账，不接任何人工/复位通道）。
- **冻结告警附失败集轨迹**：`_judge_hard_cap_freeze` evidence 追加 verdict_stability.json 轮内 failed_ids 序列（episode 作用域侧车已具备，读侧复用 core/verify_report.py 既有读取），人工解冻决策可直接看到「失败集是否在收缩」。
- **清零链同步**：新旗标与豁免计数随 verified 落定（verdict_evidence.py）、人工 unfreeze（state_machine.py `unfreeze_spec`）、admin 清零（core/dashboard/data/admin_actions.py）三处既有清零点成对清除。

## Capabilities

### New Capabilities
- `judge-rerun-budget`: judge 重跑硬上限的修复推进豁免——修复申报受理给一次机械豁免额度，冻结告警附失败集改进轨迹，豁免额度生命周期封顶且随终态清零

### Modified Capabilities

## Impact

- core/pm_engine/verification/judge_gate.py：派发门豁免消费（bump/判定段）+ `_judge_hard_cap_freeze` evidence 轨迹
- core/pm_engine/verification/pipeline.py：`_record_repair_claim` 受理点置豁免旗标
- core/state_machine.py：新字段定义与 `unfreeze_spec` 清零集、防毒注释同步
- core/pm_engine/verification/verdict_evidence.py：verified 落定清零分支
- core/dashboard/data/admin_actions.py：admin 清零点同步
- tests/test_judge_cap_repair_exempt.py（新建）

协同注记：在途 fix-verify-loop-convergence 第 4 项「硬上限诊断贯通」动同一冻结写点（其 design.md:104-110），本 SPEC 的 evidence 增强与之同写点合并落地、键名空间错开、互不覆盖——该 SPEC 治「假失败空转→停派」，本案治「有产出推进→放行」（其设计明写真·难修缺陷留在原路径、预算到顶仍冻结转人工，design.md:137-139、141）。