# 验证报告：evo-judge-rerun-stability

> ⚠️ 本报告由框架于 2026-09-14T14:11:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T14:11:32.797889+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.22M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| pytest-full-verdict-stability-suite | R1/R2/R3 交付物单元测试全量回归（tests/test_verdict_stability.py，specs/verify-reliability/spec.md 验收标准「单元测试：verdict 稳定缓存判定、verified 放行后 legacy 覆盖被拒绝」）：11 用例全部通过——verdict 稳定缓存判定、verified 放行门（含共享文件 success 污染回归）、legacy 不改判、judge 重跑硬上限冻结、STATE.md 记账 | pass | 0/2 | - |
| pytest-class-verified-gate-polluted-shared | R2 验证（单元层）：verified 落盘后主树共享 .fenix-run-result.json 被 implementer 残留 status=success 污染，verified 一次性放行门仍拒绝降级 bug-found/blocked（tests/test_verdict_stability.py::TestVerifiedGateWithPollutedSharedFile 4 用例，污染不绕过 verified 门） | pass | 0/2 | - |
| pytest-class-legacy-no-override | R2 验证（单元层·集成）：真实驱动 _run_legacy_verification，共享文件被 status=success 污染（unknown-status 白名单外）时 legacy 不得改判 blocked，spec 保持 testing，_on_spec_bug_found 不触发（tests/test_verdict_stability.py::TestLegacyUnknownStatusNotOverridingVerified） | pass | 0/2 | - |
| pytest-class-stability-two-round | R1 验证（单元层）：连续两轮 verdict 一致且 spec 戳/report.json mtime 未变 → is_verdict_stable=True（第三轮复用）；两轮不一致/单轮 → False；_judge_dispatch_gate 稳定时返回复用结果；record_verdict_round 保留最近两轮；judge_rerun_count 超 _MAX_JUDGE_RERUNS=5 → blocked + _judge_cap_frozen（tests/test_verdict_stability.py::TestVerdictStabilityTwoRoundConsistency 6 用例） | pass | 0/2 | - |
| r1-verdict-stability-cache-direct | R1 行为级：直接驱动 core/verify_report.py 的 record_verdict_round/is_verdict_stable/compute_spec_stamp（verify_report.py:805-999，design.md「裁决缓存」）——无缓存/单轮/两轮不一致 → 保守不复用；两轮一致且 spec 戳/report.json mtime 未变 → 复用；spec 戳变化（场景集重写）或 mtime 变化 → 缓存失效；record_verdict_round 只保留最近两轮。驱动脚本 .history/verify-judge-rerun-stability/verify_r1.py 输出 JSON 逐项断言 | pass | 0/8 | - |
| r1-judge-dispatch-gate-direct | R1 行为级：直接驱动 VerificationPipeline._judge_dispatch_gate/_judge_rerun_count/_judge_hard_cap_freeze（verification.py:3905-3979，design.md「计数」）——verdict 稳定返回合成复用结果（run_id=verdict-stable-reuse，success=True，不新起 judge run）；不稳定返回 None 正常派发；judge_rerun_count 递增写 STATE.md；总数超 _MAX_JUDGE_RERUNS=5 → 返回 False + spec 冻结 blocked + _judge_cap_frozen=True（人工裁决通道）。驱动脚本 .history/verify-judge-rerun-stability/verify_r1_gate.py | pass | 0/7 | - |
| r2-verified-gate-regression-direct | R2 行为级：直接驱动 VerificationPipeline._verified_verdict_persisted/_verified_gate_refuses（verification.py:3981-4023，design.md「verified 放行」）——verified 落盘且 spec 戳匹配 → 拒绝降级 bug-found/blocked；回归：主树共享 .fenix-run-result.json 被 implementer status=success 污染仍拒绝降级（污染不绕过 verified 门）；场景集变更（spec 戳变化）→ 门失效允许降级；无稳定性数据 → 门不生效。驱动脚本 .history/verify-judge-rerun-stability/verify_r2.py | pass | 0/11 | - |
| r2-legacy-no-override-direct | R2 行为级：真实驱动 _run_legacy_verification（legacy 裁决应用出口 verification.py:3260-3300）——主树共享 .fenix-run-result.json 被 implementer 残留 status=success 污染（unknown-status 白名单外）时，verified 放行门拒绝改判 blocked，spec 保持 testing、_on_spec_bug_found 不触发、verified 结论不被推翻；对照：无自有 verdict 缓存时放行门不拦截。驱动脚本 .history/verify-judge-rerun-stability/verify_legacy.py | pass | 0/5 | - |
| r3-state-md-accounting-direct | R3 行为级：直接驱动 VerificationPipeline._judge_rerun_count/_record_verdict_adoption（verification.py:3884-4064，design.md「计数」）——judge_rerun_count 递增写 STATE.md；_judge_cap_frozen 冻结期间自动递增失效；verified 落定 → 计数归零 + 解除冻结标记；bug-found 打回不清零（失败链跨轮累计）；验证链 token 增量记账（_judge_token_delta/_judge_token_baseline，token 源复用 verify_report._sum_verify_chain_tokens/tokens.json）。驱动脚本 .history/verify-judge-rerun-stability/verify_r3.py | pass | 0/9 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

