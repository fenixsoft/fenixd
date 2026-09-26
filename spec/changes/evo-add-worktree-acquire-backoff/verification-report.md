# 验证报告：evo-add-worktree-acquire-backoff

> ⚠️ 本报告由框架于 2026-09-26T18:31:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T18:31:40.547158+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.72M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| backoff-sequence-shipped-constant | 设计 1·退避序列落盘常量：模块常量 WORKTREE_ACQUIRE_BACKOFF_SEQUENCE 应为 (30, 60, 120)（core/agent_runner/runner.py:2868 定义），锁活跃等待重试在 _prepare_worktree 内完成、不消耗 attempt 重试额度（runner.py:2800-2806 注释锚点） | pass | 0/2 | - |
| fallback-counter-module-global | 设计 3·降级计数为模块级：_NEW_VERIFIER_FALLBACK_COUNT 须是 core/pm_engine/engine.py 模块级可导入属性（engine.py:196-198 定义、:2429-2430 global 累加）——PMEngine 按 run 重建实例时计数仍跨实例累计，不复现实例级计数恒为 1 的教训 | pass | 0/2 | - |
| lock-release-acquires-worktree | spec 场景「持锁方排空后取得 worktree」：create 首败（同 spec:agent_type 锁被并行 run 持有）后按退避序列等锁，锁释放后下一轮 create 即取得并打点 acquired after lock wait，不触发新验证流程降级（tests/test_worktree_acquire_backoff.py::TestLockReleaseAcquires，实现 core/agent_runner/runner.py:2928-2936） | pass | 0/5 | - |
| backoff-exhausted-gave-up-signature | spec 场景「重试耗尽仍锁活跃」：退避完整走完 30s/60s/120s 仍锁活跃则返回 lock-backoff-exhausted，经 _prepare_worktree 得既有 gave up 错误且文案签名「Failed to create worktree (gave up: parallel run or manual freeze)」保持不变（core/agent_runner/runner.py:2823-2829 错误签名锚点；tests/test_worktree_acquire_backoff.py::TestBackoffExhausted） | pass | 0/4 | - |
| human-takeover-immediate-yield | spec 场景「手动冻结立即让位」：frozen / _cancelled_hold / status 迁出预期态三种人工接管态下 create 失败即返回 human-takeover，零 sleep、不走锁探针，行为与现状一致（core/agent_runner/runner.py:2899-2902 分探针 1 check_lock=False；tests/test_worktree_acquire_backoff.py::TestHumanTakeoverImmediateYield） | pass | 0/6 | - |
| takeover-during-backoff-wait | spec 场景「退避期间人工接管」：退避等待期间 spec 被冻结/status 迁出预期态（含并行 run 完成后的状态迁移），下一轮重探前复查命中即立即让位、不得再探 create 照常取得 worktree（core/agent_runner/runner.py:2917-2927 每轮复查；tests/test_worktree_acquire_backoff.py::TestTakeoverDuringBackoffWait） | pass | 0/4 | - |
| non-lock-failure-attempt-retry-preserved | 异常路径·非锁失败不进退避：非锁、非人工接管的 create 失败（git 错误等其它原因）保持既有 attempt 层语义——attempt<max_retries 时 do_continue+sleep(5) 重试；退避等待中锁已释放但 create 仍失败即返回 create-failed 不空转退避（core/agent_runner/runner.py:2903-2906、2937-2940；tests/test_worktree_acquire_backoff.py::TestNonLockFailurePreservesAttemptRetry） | pass | 0/4 | - |
| verifier-fallback-counter-increments | spec 场景「降级可统计」：新验证流程降级 WARNING 文案含「第 N 次降级」累计计数（第 1 次→第 2 次递增、跨 PMEngine 实例重建仍累计），新流程成功不计数不降级（core/pm_engine/engine.py:2424-2435；tests/test_worktree_acquire_backoff.py::TestVerifierFallbackCounter） | pass | 0/5 | - |
| acquire-backoff-full-suite-aggregate | 回归点·交付测试文件全绿聚合：tests/test_worktree_acquire_backoff.py 全部 16 条用例一次通过（锁释放取得/退避耗尽/人工接管立即与等待期间让位/非锁失败保持/降级计数五组全覆盖），且无任何 FAILED | pass | 0/3 | - |
| worktree-name-collision-regression | tasks 2.2 回归·worktree 命名冲突换名重试与锁语义不变：already exists 换名重试（evo-fix-worktree-name-collision-retry 既有签名）、并发创建只有一个赢家、give_up_decision 四参数化判定（[lock-active]/[frozen] 后缀形态）、has_active_lock 语义（tests/test_dual_dispatch_and_freeze.py::TestWorktreeLockIdempotency + TestRetryGiveUp） | pass | 0/7 | - |
| pm-verification-pipeline-regression | tasks 2.2 回归·验证管线既有语义不变：tests/test_pm_verification.py 全量 75 通过 + 1 预期失败（uniform failure 复位、verified gate 证据竞态、降级通道等），确认本次改动未波及验证管线既有行为 | pass | 0/3 | - |
