# add-repair-claim-fingerprint-gate

## Why

2026-11-12 add-session-advanced-search（dsh-plugins 项目）实证「单测绿但真机无效」的修复申报环：implementer 申报 tsc 零错+vitest 120/120+产物核验 ctx.get 在场（impl-result.json，16:54Z，自述「run 内未重复执行全量回归」）→ e37d005 合入 → lib 重建部署并被 17:01:36Z 新启实例加载 → 17:01 与 17:13 两轮真机稳态逐字节复现同一失败签名（5 候选 title=''/conf=0/纯活跃排序；verification-report.md L30 与 report.json dg stderr 同串）——修复机制真机无效，白烧 impl+合入+部署+14 场景整轮重验，并把 judge 重跑预算直接推至上限冻结（6/5，冻结与报告落盘仅隔 0.139s），连带 2 个 arbiter 处置 run（$2.52/$2.73）。同 spec 当日 _judge_repair_claim_rounds=4、sas-web-entry-injection 六轮修复申报受理后场景仍失败——「申报受理不核效果」形态当日复发 6+ 次；2026-11-10 redesign-chain-panel-ui（修复闭环后残留子集重验仍失败→冻结）为跨 spec 第二例。

结构性缺口（已回源核实）：受理面无任何效果核验机械——

- `_apply_bug_found`（core/pm_engine/verification/pipeline.py:1214-1262）派修复时不随单附失败指纹；
- `_record_repair_claim`（pipeline.py:3971）只记 id 级截断摘要（`_judge_repair_last_summary`），不比对被修场景失败指纹是否变化；
- 实现者模板 agents/implementer.md 无真机效果探针义务（grep 仅命中长任务前台运行指引）。

比对素材已在盘面，零新增取数体系：verdict_cache.json 每场景带 definition/build/verify_config 四元组指纹（dg=143de6fb3cc9cc7c），verdict_stability.json 已记轮级 stamp（ef83e42b→9769c8b2）。

## What Changes

- **修复申报受理指纹门**：`_record_repair_claim` 受理路径比对被修场景盘面最新失败指纹与派单指纹——指纹未变化（同一失败签名原样复现）即拒收本轮修复，复用既有 rejected 记账与重派上下文回传语义（与在途 judge-repair-scenario-writeback-gate 的拒收接线形态同源），不重入执行；指纹已变化或无基线照常受理。
- **随单附指纹**：bug-found 派修复的上下文注入被修场景失败指纹（场景 id + 失败断言签名摘要），供实现者申报自检与受理门双向对表；无基线置 null 不阻断派发。
- **实现者申报探针义务**：agents/implementer.md 修复类申报前 MUST 附被修场景的最小真机探针结果（单场景/API 级复跑或服务可达性探针）并标注与派单指纹的一致性；探针复现派单指纹不得申报 success，申报缺探针标注由受理门按同语义拒收。义务范围限被修场景，不引入全量回归义务（全量重验仍由验证链承担）。

## Capabilities

### New Capabilities
- judge-repair-claim-gate: 修复申报效果核验门——bug-found 随单附失败指纹、受理时指纹比对拒收零进展修复、实现者申报真机探针义务。

## Impact

- Affected specs: 无（新能力页 judge-repair-claim-gate）
- Affected code:
  - core/pm_engine/verification/pipeline.py（_apply_bug_found 随单附指纹、_record_repair_claim 受理指纹门）
  - agents/implementer.md（修复申报探针义务段）
  - tests/test_repair_claim_fingerprint_gate.py（新增门行为测试）
- 与在途 SPEC 协调：fix-verify-loop-convergence（路由面零进展闸门）与本门（受理面指纹门）互补、拦截点一前一后；两案均触 pipeline.py，实现须串行避让（本门后落地时以在途案合并后的管线为基线）。judge-repair-scenario-writeback-gate 的拒收接线形态（rejected 记账、回传清单、不穿透守卫）作为本门分支样式先例。