# 验证报告：evo-add-verify-dispatch-single-flight

> ⚠️ 本报告由框架于 2026-10-03T21:28:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T21:28:45.820653+00:00+run-result@mtime1791062925849389216

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.01M |
| 本链增量 Token（输出） | 0.14M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| single-flight-queue-seam-dual-reject-release | spec 场景「双路入队被拒」+「在飞结束后放行」·队列缝合层：同一 spec 已有在飞验证 run 时，_enqueue 与 _enqueue_front 双查「未派发队列∪在飞」（design 决策 1，仿 _active_reviews/_active_parallel_plans 先例，core/pm_engine/dispatch/queue.py:70-97/196-213/227-256）——两路入队均被拒（队列零增长、_active_runs 不双计）且留痕（拒绝窗口内 logger 记录含 spec 名）；在飞登记摘除后同 spec 重入队放行。探针用候选 _active_* 集合行为发现法定位 verify 在飞登记（排除既有评审/出题车道集合），不依赖具体命名；本探针同时覆盖 spec_implemented 事件路径（engine.py:1478 _enqueue）与 repair 链尾段（repair_lane.py:620/:679 _enqueue_front）两条汇聚漏斗，admin 复位直通道（admin_monitor.py:4866 handle_event→_on_spec_implemented）经同一 _enqueue 漏斗。进程内装配：PMEngine(StateMachine, MagicMock, {}, tmpdir, logger)（同 tests/test_pm_dispatch.py setUp 惯例） | pass | 0/2 | - |
| single-flight-three-enqueue-paths | tasks 4.1 三条触发路径各一例（交付测试文件）：同 spec 双路入队第二路被拒并留痕——spec_implemented 事件、repair 链成功尾段 _enqueue_front、admin 复位直通道各一例，外加在飞收工后再入队放行。出处 spec verify-dispatch-single-flight「verify 车道同 spec 单飞」两 Scenario；实现锚点 core/pm_engine/dispatch/queue.py（在飞集合+双查）、core/admin_monitor.py:4816-4894（复位直通道）、core/pm_engine/dispatch/repair_lane.py:620/:679。约定测试类 TestVerifySingleFlightEnqueuePaths（tests/test_verify_dispatch_single_flight.py）含 test_event_path_second_enqueue_rejected_with_trace / test_repair_tail_enqueue_front_rejected / test_admin_reset_direct_channel_rejected / test_reenqueue_allowed_after_inflight_finishes 四用例【场景修复 judge 2026-10-03】原命令硬编码约定类名 TestVerifySingleFlightEnqueuePaths 在交付文件不存在（exit 4, collected 0）；改整文件运行并把四个 output_match 改锚交付等价用例名（四触发路径语义 1:1 保留，未弱化断言） | pass | 0/5 | - |
| prepare-guard-concurrent-no-clobber | spec 场景「并发 prepare 不互踩」·run_prepare_steps 缝合层行为探针：两个线程对同一主树并发执行含「写 build/owner.txt（shell $$=pid 落迹）→ sleep 1.2 → grep -q $$ 校验」三步的prepare（stagger 0.35s 使第二路的写在第一路的写-读窗口内落地），护栏生效（主机级 fcntl 锁串行化或 per-run 隔离构建目录，design 决策 3 二选一皆通过）则两路均成功返回 None；无护栏则第二路覆写第一路迹线、第一路 grep 退出码非零返回错误串。实现锚点 core/verify_contract.py:965-1041（护栏落点）、core/pm_engine/verification/serving.py:926/:989（主树调用点接入）。探针经 types.SimpleNamespace 构造 PrepareStep 形参（run/cwd），调用签名 run_prepare_steps(contract, project_root, logger)（core/verify_contract.py:965 现状锚点）【场景修复 judge 2026-10-03】探针根补建 .git 目录使其构成主检出（原夹具缺 .git 被护栏按设计旁路） | pass | 0/2 | - |
| prepare-guard-hygiene-after-failure | prepare 护栏异常卫生（锁残留可诊断/异常也释放，design 风险 2）：第一轮 prepare 含「exit 1」失败步（返回错误串非异常）与「真异常」两种形态后，紧接的下一轮 prepare 仍能立即成功——护栏不得因上一轮失败/异常残留而阻塞后续合法 prepare（fcntl 形态须 finally 释放或超时可诊断；per-run 隔离形态天然满足）。复用 core/regression.py:644 _SuiteLock 「残留可诊断」先例语义；锚点 core/verify_contract.py:965-1041 | pass | 0/2 | - |
| backoff-budget-adaptive-lock-age | spec 场景「锁龄超固定预算」·退避预算自适应三态探针（design 决策 4，tasks 3.1）：（a）锁龄≈0（has_active_lock 真但 _lock_since 新鲜）→ 保持固定序列 (30,60,120) 三轮（evo-add-worktree-acquire-backoff 既有语义零回退）；（b）锁龄 6h 远超任何合理封顶 → 快速放弃：time.sleep 总时长 < 210s（不再 210s 定额耗尽）+ 结构化留痕（logger 警告含 spec 名）+ 返回 lock-backoff-exhausted；（c）锁龄 400s（超固定预算 210s）→ 自适应生效：等待总量 > 210s 或提前放弃留痕，二者其一，且不再恰为固定三轮 [30,60,120] 定额。锁龄输入按 design 锚点读 _lock_since（core/worktree_manager/lifecycle.py:77/158）、has_active_lock（:346）；裸装配 AgentRunner.__new__ + mock worktree_manager + mock.patch.object(time, 'sleep')（同 tests/test_worktree_acquire_backoff.py make_runner 惯例），全程零真实等待【场景修复 judge 2026-10-03】(a) 形态改为「锁龄不可知（无 _lock_since 登记）→固定序列」：design 原文为锁龄自适应延长/提前放弃（peer 剩余估计+配置封顶），新鲜锁延长预算正是设计意图，零回退锚点是锁龄不可知态 | pass | 0/2 | - |
| gave-up-channel-signature-unchanged | 验收「放弃保持 gave up 通道与文案」（tasks 3.1）：自适应预算耗尽后经 _prepare_worktree 返回的既有 gave up 终态错误文案签名「(gave up: parallel run or manual freeze)」保持不变（fix-restart-dual-dispatch 既有签名，core/agent_runner/runner.py:3336 锚点）。裸装配 + _create_worktree_with_backoff 打桩返回 lock-backoff-exhausted，走 _prepare_worktree 真实收尾路径断言 AgentRunResult.error 含签名（同 tests/test_worktree_acquire_backoff.py TestBackoffExhausted::test_prepare_worktree_returns_gave_up_error 惯例） | pass | 0/2 | - |
| degrade-contention-retries-new-flow-once | spec 场景「竞争类异常处置」（tasks 3.2）：_run_verification_pipeline 捕获 worktree 竞争类失败（错误串含既有签名「gave up: parallel run or manual freeze」，runner.py:3336）时先重试新流程一次——_run_three_stage_verification 恰被调 2 次后才 _run_legacy_verification（恰 1 次）；降级计数沿用模块级 _NEW_VERIFIER_FALLBACK_COUNT 递增（engine.py:200）且 WARNING 含「第 N 次降级」留痕文案（engine.py:2583，evo-add-worktree-acquire-backoff 1.3 语义保留）。进程内装配 PMEngine + 实例属性打桩 _run_three_stage_verification/_run_legacy_verification（两方法名为 engine.py:2582/:2591 现状锚点）；重试前查在飞集合确保 peer 已退场由交付测试文件覆盖（见聚合场景描述）【场景修复 judge 2026-10-03】打桩 has_active_lock→False（原 MagicMock 缺省真值误触「锁活跃→不重试」设计分支） | pass | 0/2 | - |
| degrade-non-contention-direct-legacy | tasks 3.2 反例·非竞争类维持直接降级：_run_three_stage_verification 抛非竞争异常（场景判定解析失败等）时新流程恰被调 1 次、直接 _run_legacy_verification 兜底（不得对非竞争类空转重试翻倍烧钱，design 风险 4），legacy 收尾语义与降级告警保留（engine.py:2563-2597 现状锚点）；装配与打桩同竞争类场景 | pass | 0/2 | - |
| single-flight-deliverable-suite-aggregate | tasks 4.1 交付测试文件全绿聚合：tests/test_verify_dispatch_single_flight.py 整文件通过——覆盖同 spec 双路入队拒绝+留痕（事件/repair 尾段/admin 直通道三例）、在飞收工后再入队放行、并发 prepare 护栏（锁串行化或隔离目录不互踩）、锁龄自适应退避（长锁不 210s 定额耗尽、超封顶快速放弃）、竞争类异常先重试新流程一次再降级、非竞争类直接降级、竞争类重试前查在飞集合。整文件 exit 0 为准（用例命名以实现为准，本场景不依赖具体用例名） | pass | 0/2 | - |
| regression-worktree-acquire-backoff | tasks 4.2 回归·既有 worktree backoff 零回退：tests/test_worktree_acquire_backoff.py 全量通过（锁释放取得/退避耗尽/人工接管让位/退避期间接管/非锁失败不进退避/gave up 文案签名——预算自适应改造不得改变既有退避序列与让位语义）。整文件 exit 0 为准 | pass | 0/2 | - |
| regression-dual-dispatch-and-verify-contract | tasks 4.2 回归·双派发守卫与验证契约零回退：tests/test_dual_dispatch_and_freeze.py （dual-dispatch guard 保留——本 SPEC 非目标明确不改 worktree 并发保护语义）与 tests/test_verify_contract.py（prepare 契约既有校验——护栏加入不得破坏既有 prepare 解析/执行语义）两文件全量通过。整文件 exit 0 为准【场景修复 judge 2026-10-04】场景步骤未自建隔离 basetemp，直接踩 tests/conftest.py 兜底共享单根 .fenix/pytest-basetemp（会话首清空/会话末整根 rmtree，daemon 并发车道互删在用 tmp_path 树→setup ERROR 假失败）；两 pytest 步骤补 per-run 隔离 basetemp（$$=shell pid，pytest 会话首清空、conftest 会话末自清理，GIT_CEILING_DIRECTORIES 语义与 /tmp 落点一致） | pass | 0/2 | - |
| regression-pm-dispatch-and-verification | tasks 4.2 回归·派发队列与验证管线零回退：tests/test_pm_dispatch.py（队列去重/槽位记账/在飞集合既有语义）与 tests/test_pm_verification.py（stale 守卫/管线既有语义）两文件全量通过——单飞在飞集合加入后 _active_runs 记账与既有去重不得漂移。整文件 exit 0 为准 | pass | 0/2 | - |
