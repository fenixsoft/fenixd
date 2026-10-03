# 验证报告：evo-add-verify-dispatch-single-flight-7c1997

> ⚠️ 本报告由框架于 2026-10-03T21:00:38Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T21:00:38.150005+00:00+run-result@mtime1791061238181146990

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.47M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sf-enqueue-guard-rejects-all-three-paths | verify 车道同 spec 单飞：在飞期间经三路重复入队（spec_implemented 事件、repair 链尾段 _enqueue_front、admin 复位直通道）及旁路兜底（出队分流）均被拒绝且结构化留痕，不产生第二个并发验证 run。出处：core/pm_engine/dispatch/queue.py:221/:263/:823、core/admin_monitor.py:4816、core/pm_engine/dispatch/repair_lane.py:625、tests/test_verify_dispatch_single_flight.py | pass | 0/5 | - |
| sf-requeue-allowed-after-finish-and-dedup-preserved | 在飞验证 run 收工（在飞集合摘除）后同 spec 再入队放行、出队正常登记在飞——合法重验不被单飞守卫阻塞（空状态/回归点）；且无在飞时既有队列去重语义不变（重复入队仍折叠为单条目）。出处：core/pm_engine/dispatch/queue.py:104/:1035、tests/test_verify_dispatch_single_flight.py | pass | 0/4 | - |
| sf-prepare-host-lock-serializes-cross-process | prepare 并发护栏行为探针（独立双进程）：主树形态（.git 为目录）下 prepare 段持主机级 fcntl 锁——子进程持锁期间 run_prepare_steps 等待不执行构建，持有者释放后取得锁并完成构建（串行化不互踩），持有期锁文件写入持有者 pid（残留可诊断）。出处：core/verify_contract.py:969/:987、tests/test_verify_dispatch_single_flight.py | pass | 0/2 | - |
| sf-prepare-host-lock-timeout-fail-visible | 锁等待超时 fail-visible 行为探针（真实双进程）：持有者持锁不放时等待方在 timeout 上限附近快速返回未获锁（非 bypassed 降级），holder_pid 可读到持有者 pid 供残留诊断；持有方释放后新调用可正常取得锁。出处：core/verify_contract.py:987-1080 | pass | 0/2 | - |
| sf-prepare-guard-unit-behaviors | prepare 护栏其余单元行为：线程级串行化（持有者未释放前不执行）、锁等待超时返回结构化错误（附锁路径与持有者 pid、步骤未执行）、worktree 调用（.git 为文件）不加锁零开销不落锁文件、锁内构建步骤失败错误原样透出不被护栏吞。出处：core/verify_contract.py:965-1100、tests/test_verify_dispatch_single_flight.py | pass | 0/5 | - |
| sf-adaptive-backoff-budget | 碰撞退避预算自适应：锁龄 100s（peer 预计 900s）预算延长至 800s 不再 210s 定额耗尽；锁龄超 peer 预计（滞留/僵死形态）预算归零快速放弃零空转并留痕 early give-up；锁龄不可知保守回固定 30/60/120 序列（零回退）；配置封顶 worktree.acquire_backoff_max_budget_seconds 截短预算；延长预算内 peer 排空照常取得 worktree。出处：core/agent_runner/runner.py:3386-3455、tests/test_verify_dispatch_single_flight.py | pass | 0/6 | - |
| sf-degrade-triage-contention-vs-non-contention | 降级分流：worktree 竞争类失败（异常链含 gave up: parallel run or manual freeze）且锁已释放→先重入新流程一次、成功即不降级 legacy；重试仍败→降级 legacy 并附两次错误与降级计数留痕；锁仍活跃→不重试直接降级；非竞争类失败→维持既有直接降级。出处：core/pm_engine/engine.py:2568/:2606-2649、tests/test_verify_dispatch_single_flight.py | pass | 0/5 | - |
| sf-new-single-flight-suite-full-green | 本 SPEC 新增测试套全量 20 例一次通过（整体基线：单飞入队/出队守卫、admin 直通道收敛、prepare 主机锁、自适应退避、降级分流整体绿）。出处：tests/test_verify_dispatch_single_flight.py | pass | 0/2 | - |
| sf-regression-dispatch-repair-lane | 回归点：queue.py 与 repair_lane.py 改动的既有派发与 repair 车道测试零回退（test_pm_dispatch、test_dispatch_aging、test_repair_lane_dedup、test_dual_dispatch_and_freeze、test_mergeback_repair_lane）。出处：tests/ | pass | 0/2 | - |
| sf-regression-worktree-backoff | 回归点：worktree 竞争退避相关既有测试零回退（test_worktree_acquire_backoff、test_verify_parallel_backoff、test_transient_backoff、test_transient_unseal_backoff）——自适应预算不得改变既有固定序列语义。出处：tests/ | pass | 0/2 | - |
| sf-regression-worktree-conflict-admin-cross-type | 回归点：worktree 并发保护/conflict-recovery/admin 跨类型重复派发既有测试零回退（test_worktree_merge_guard、test_worktree_reuse、test_worktree_stray_and_identical、test_worktree_wip_artifact_scope、test_stash_pop_conflict_triage、test_admin_dispatch_escalation）——单飞守卫不改 dual-dispatch guard 语义。出处：tests/ | pass | 0/2 | - |
| sf-regression-verify-contract | 回归点：verify 契约既有测试零回退（test_verify_contract、test_verify_contract_autodraft、test_verify_contract_template_preflight）——prepare 护栏单点收敛于 run_prepare_steps，不改契约既有语义。出处：tests/ | pass | 0/2 | - |
