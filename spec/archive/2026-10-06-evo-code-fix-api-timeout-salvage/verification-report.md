# 验证报告：evo-code-fix-api-timeout-salvage

> ⚠️ 本报告由框架于 2026-09-27T18:50:53Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-27T18:50:52.966948+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.98M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-timeout-signature-two-forms-no-mislabel | Requirement 1 验收场景 1+2：api_timeout 签名判别两形态命中（末次 result 事件 terminal_reason==api_error、result 文本含 CLI 合成超时文本 Request timed out）与非超时不误标（确定性 TypeError 失败、turn_limit、成功终局、空 result 均判 False）。出处：core/agent_runner/runner.py:392 is_api_timeout_signature；交付测试 tests/test_code_fix_api_timeout_salvage.py::TestApiTimeoutSignature | pass | 0/7 | - |
| api-timeout-signature-direct-probe-json | Requirement 1 直接探针：不经交付测试、直接 import 交付函数 is_api_timeout_signature 核验判别契约——两形态命中、四类非超时输入（确定性失败/turn_limit/空 result/超时文本仅出现在 stderr 字段不扩散误标）逐字段以 JSON 结构化输出断言。出处：core/agent_runner/runner.py:389 API_TIMEOUT_RESULT_TEXT、core/agent_runner/runner.py:392 is_api_timeout_signature | pass | 0/7 | - |
| run-code-fix-envelope-structured-signature | Requirement 1（任务 1.2）：run_code_fix 失败信封透出结构化签名——api_timeout 布尔标记上信封、exit_code 与 stderr 尾行摘要保留、失败记录 error 文本携带 api_timeout=True/exit_code=1 供日志落痕；确定性失败标 api_timeout=False；无信号异常 error 保持原文不添噪；产物硬门失败路径（except 未执行）不误标不炸。出处：core/agent_runner/maintenance_runs.py:1842 _stderr_tail_summary、core/agent_runner/maintenance_runs.py:2060 结构化签名透出；交付测试 TestRunCodeFixSignatureEnvelope | pass | 0/6 | - |
| salvage-commit-lands-on-batch-branch-legacy-reuse | Requirement 2 验收场景 3：api_timeout 终局且工作区脏时的失败现场保全——真实 WorktreeManager 建 code-fix 批树，WIP 以 salvage commit 落批分支（不再只留悬空快照），cleanup(success=False) 按 recovery legacy 机制登记保全（宽限期内豁免陈旧清扫），编排器补 mark_legacy_reusable 置 reuse 标记。出处：core/code_fix.py:3097 _salvage_api_timeout_wip、core/code_fix.py:3133 _mark_salvage_reusable；交付测试 TestSalvageLegacyClaimPath::test_salvage_commit_lands_on_batch_branch_and_reuse_marked | pass | 0/3 | - |
| api-timeout-clean-worktree-skips-salvage | Requirement 2 验收场景 4（空状态）：api_timeout 终局但工作区无改动——跳过 salvage 按现状清理、无 salvage 提交产生、跳过行为留痕日志、recovery legacy 照常登记但不置 reuse（下一批全新建树）。出处：core/code_fix.py:3097 _salvage_api_timeout_wip 工作区干净分支；交付测试 TestNonApiTimeoutFailureUnchanged::test_api_timeout_clean_worktree_skips_salvage | pass | 0/3 | - |
| salvage-full-chain-orchestrator-e2e | Requirement 2+3 交互流程（端到端编排链）：第 1 批 api_timeout 终局且工作区脏 → WIP salvage 提交批分支 → 失败批跳批推进（链继续不 halt）→ 第 2 批经既有认领通路在同目录同分支继承 salvaged 工作 → salvaged 修复随重试批合回进主树（不再悬空蒸发）→ 条目核销语义不变（失败批保持 open、成功批 resolved）→ salvage 事件写日志留痕。出处：core/code_fix.py:3258 _run_batch_created 失败分支；交付测试 TestApiTimeoutSalvageChain::test_full_chain_salvage_reuse_and_next_batch_claim | pass | 0/3 | - |
| next-batch-create-claims-salvaged-branch | Requirement 3 验收场景 5 THEN：同链下一批建树接续 salvaged 现场——mark_legacy_reusable 后 wm.create 经既有 _take_reusable_worktree 认领通路继承 salvaged 载体（同目录同分支）、salvaged 提交对重试批可见、认领即摘出 legacy。出处：core/worktree_manager/lifecycle.py:168 create 认领门（agent_type 白名单扩入 code-fix）；交付测试 TestSalvageLegacyClaimPath::test_next_batch_create_claims_salvaged_branch | pass | 0/3 | - |
| claim-unavailable-fails-open-fresh-worktree | Requirement 3 验收场景 5 AND（异常路径）：认领不可用 fail-open——salvaged 载体被外力删除（模拟陈旧清扫/换壳失败）后下一批 create 不阻断链推进、全新建树落新分支、无效 legacy 被清除，不出现车道死锁。出处：core/worktree_manager/lifecycle.py:168 认领门 fail-open 回退；交付测试 TestSalvageLegacyClaimPath::test_claim_unavailable_fails_open_to_fresh_worktree | pass | 0/3 | - |
| deterministic-failure-dirty-worktree-no-salvage | design D4 行为保形（Requirement 1 验收场景 2 延伸）：非 api_timeout 的确定性失败即使工作区脏也不做 salvage——立即清理（cleanup success=False）、条目入 chain_skipped、失败日志仍带 api_timeout=False 结构化签名便于追溯。出处：core/code_fix.py:3258 _run_batch_created 失败分支非 salvage 路径；交付测试 TestNonApiTimeoutFailureUnchanged::test_deterministic_failure_dirty_worktree_no_salvage | pass | 0/3 | - |
| regression-salvage-infra-reuse-legacy-suites | 回归点：本 SPEC 改动的邻接面——salvage 提交基础设施（add-codefix-commit-first-contract 交付的 _salvage_commit 编排侧范本 tests/test_code_fix_salvage.py）、worktree 复用认领（认领白名单扩入 code-fix 后既有 agent_type 认领语义不变 tests/test_worktree_reuse.py）、recovery legacy 登记语义（tests/test_recovery_legacy.py）三套件合计 30 例全过 | pass | 0/2 | - |
| regression-code-fix-orchestrator-suite | 回归点：code-fix 编排器既有 112 例全过——run_code_fix 信封新增可选字段（api_timeout/exit_code/stderr_summary 缺省不改变成功路径形态）与 _run_batch_created 失败分支改造不破坏既有失败/跳批/合回语义（design D4：失败=chain_skipped 跳批推进与重试预算语义不变）。出处：tests/test_code_fix.py | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

