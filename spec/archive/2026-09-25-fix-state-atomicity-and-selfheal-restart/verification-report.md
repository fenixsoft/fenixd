# 验证报告：fix-state-atomicity-and-selfheal-restart

> ⚠️ 本报告由框架于 2026-09-21T18:23:48Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-21T18:23:48.797516+00:00

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.98M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| atomic-read-modify-write-inside-filelock | 独立行为探针（state-write-atomicity / Requirement「STATE.md 写入的原子性（无丢失更新）」）：在 `update_spec` 执行期间探 `.STATE.md.lock` 是否已被持有——把 `StateMachine.read_all` 包一层探针，在探针内用第二个 fd 对该锁文件做 `flock(LOCK_EX\|LOCK_NB)`，EWOULDBLOCK 即证明『读』发生在同一把文件锁内（Linux flock 按 open file description 生效，同进程异 fd 亦互斥）。这是对『读 → 改 → 写收进单次 flock』的结构性取证，不依赖竞态运气。出处：core/state_machine.py:644（_mutate_locked）、core/state_machine.py:777（update_spec）。 | pass | 0/2 | - |
| atomic-concurrent-writers-keep-all-fields | 正向并发路径（Requirement「STATE.md 写入的原子性」/ Scenario 并发更新不同字段均保留）：8 个线程各自构造独立 StateMachine 实例（模拟 daemon 多 worker + dashboard 独立进程），经 `threading.Barrier` 对齐起跑后并发 `update_spec` 写同一 spec 的**不同**字段，断言 8 个字段全部保留（旧实现各持陈旧快照整体回写，必然丢更新）。字段名用 `_` 前缀（serialize 只持久化固定键集 + `_` 前缀键，见 core/state_machine.py:436-465，故探针写 `_probe_i`）；值为字符串（STATE.md 为文本格式，回读统一为 str）。出处：core/state_machine.py:777（update_spec）、core/state_machine.py:644（_mutate_locked）。 | pass | 0/4 | - |
| atomic-cross-process-flock-serializes | 跨进程并发写入不丢失更新（Requirement「STATE.md 写入的原子性」/ Scenario 跨进程并发写入不丢失更新）：两条证据——① 独立行为探针：`os.fork` 出的**子进程**先持有 `.STATE.md.lock` 的 `flock(LOCK_EX)` 3 秒，父进程随后 `update_spec` 必须被阻塞 ≥1s（`blocked=true`）且解阻塞后写入成功、`branch` 落盘——证明锁是跨进程文件锁而非进程内单例锁；② 交付测试 `TestCrossProcessLock`（真实 subprocess 写入者）作为契约锚点。出处：core/state_machine.py:644（_mutate_locked）、tests/test_state_write_atomicity.py:252（TestCrossProcessLock）。 | pass | 0/6 | - |
| atomic-reviewer-run-anchor-not-clobbered | 事故直接复现路径（Requirement「STATE.md 写入的原子性」/ Scenario 评审派发写入的 reviewer_run 不被并发覆盖）：交付测试 TestConcurrentWriteNoLostUpdate 以「每个 read_all 之后插入汇合屏障」确定性逼迫两个写者都先持快照再回写（旧实现必然同快照回写，用例在未修补实现上必失败），断言 `reviewer_run` 与并发写入的 `branch` 均保留、且 reviewer_run 不被覆盖回 null。含并发 add_spec / remove_spec 同源收敛（查重与插入、剔除与回写均须在同一锁内）。出处：tests/test_state_write_atomicity.py:109-166、core/state_machine.py:1060（add_spec）、core/state_machine.py:1096（remove_spec）。 | pass | 0/5 | - |
| atomic-frozen-error-persists-and-unfreeze-restores | 回归锚点（Requirement「冻结 error 的可靠持久化」两条 Scenario 合并）：走生产入口 `freeze_for_human` 冻结（error 内嵌「原状态 reviewing」），随后 3 个并发写者（独立 StateMachine 实例、Barrier 对齐）分别写 `reviewer_run`/`branch`/`implementer_run`；断言 ① `error` 未被清除；② `parse_orig_status` 读出真实原状态 `reviewing`（而非回退 ready）；③ 以该原状态解冻后 `status == reviewing`、`error` 清空。这是把 2026-09-21 事故（解冻只能回退 ready）翻成可断言契约。出处：core/state_machine.py:861（freeze_for_human）、core/state_machine.py:148（parse_orig_status）、core/state_machine.py:969（unfreeze_spec）。 | pass | 0/7 | - |
| atomic-frozen-error-contract-tests | 契约测试锚点（Requirement「冻结 error 的可靠持久化」）：交付测试 TestFrozenErrorPersistence——① 冻结 error 在并发写入后仍可读且 parse_orig_status 返回 reviewing；② 解冻（未显式指定 status）恢复原状态而非回退 ready；③ 冻结剥离判定基于锁内最新条目（并发冻结期间到达的自动 status 写被剥离并记 warning）。③ 是加锁后新增的语义：锁外快照会把「刚被冻结」误判为「未冻结」而漏剥离。出处：tests/test_state_write_atomicity.py:169-207、core/state_machine.py:789-818（_mutate 冻结剥离）。 | pass | 0/4 | - |
| atomic-write-traceability-construction-audit | 「写入必留痕」的构造层前提（Requirement「STATE.md 写入的原子性」/ Scenario STATE.md 写入必留痕，含其构造层附注）：以 AST 审计全库 `StateMachine(...)` 构造点（core/ 全部 .py + fenixd.py + bin/），断言不存在「未传 logger 或传字面 None」的构造——即无一处会落回 `_NullLogger` 静默兜底（core/state_machine.py:545）。覆盖 design D2 点名的三处 dashboard 跨进程写入者，并防止后续新增静默写入点。出处：core/state_machine.py:502（project_state_logger）、core/state_machine.py:473-489（_NullLogger）、core/dashboard/data/spec_archive.py:148、core/dashboard/routes/evolution_routes.py:32、core/dashboard/routes/code_review_routes.py:245。 | pass | 0/3 | - |
| atomic-write-traceability-runtime-log-and-tests | 写入必留痕的运行时证据（Requirement「STATE.md 写入的原子性」/ Scenario STATE.md 写入必留痕）：① 独立探针：`project_state_logger(临时项目根)` 返回**非** `_NullLogger` 的真实日志器；以其构造 StateMachine 执行 `update_spec` 后，`<root>/.fenix/logs/fenixd.log` 落盘且含 「Updated SPEC」（跨进程写入通道 `.fenix/logs/` 与 dashboard 同源）；② 交付测试 TestWriteTraceability 作为契约锚点（含日志 context 携带本次所改字段键）。出处：core/state_machine.py:502（project_state_logger）、core/state_machine.py:819-829（留痕点，在原子写成功后输出）、tests/test_state_write_atomicity.py:210-249。 | pass | 0/8 | - |
| atomic-writepath-convergence-source-forensics | 同源收敛取证（design D1/D2）：以 `inspect.getsource` 断言 `update_spec`/`add_spec`/`remove_spec` 三条 read-modify-write 路径**全部**经 `_mutate_locked` 执行，且 `_mutate_locked` 锁内只调 `_write_all_locked(specs)`、不含 `self.write_all(` 调用（同进程二次 flock 会自阻塞死锁，design D1 约束）；并断言 `remove_spec` docstring 已订正——不再残留与实现不符的 「a concurrent writer cannot resurrect the entry」声明（design D2 要求 MUST NOT 留有与实现不符的不变式）。出处：core/state_machine.py:644（_mutate_locked）、core/state_machine.py:609（_write_all_locked）、core/state_machine.py:1096（remove_spec docstring）。 | pass | 0/7 | - |
| idle-stalled-review-run-not-idle | 本 SPEC 的第二个事故面（stale-code-selfheal / Requirement「空闲判定语义」+「空闲感知的陈旧自愈触发」）：构造「评审车道在飞且转录停滞」的 run——`_active_runs == 0`（评审 run 从不递增它，core/pm_engine/dispatch/queue.py:556-564 显式 MUST NOT 增减）、`reviewer_run` 锚点非空、run 登记在 `running_run_ids()` 进程表、流文件停止增长——断言 `_is_idle()` 为 False，且 `_maybe_stale_selfheal_tick` 不写入 `restart_request`（不被自愈重启打断）。该用例在未修补实现上必失败（修补前 `_active_runs == 0` 即判空闲），构成回归锚点；同批覆盖「入队未落盘窗口」（has_queued_review）与「_active_reviews 已释放但锚点仍在飞」的接力窗口（防只加 `_active_reviews` 一维的退化实现）。出处：fenixd.py:987（_is_idle）、fenixd.py:1053（_review_lane_busy）、core/pm_engine/engine.py:3522/3535/3556、tests/test_stale_selfheal_idle.py:171-245。 | pass | 0/6 | - |
| idle-selfheal-trigger-and-reset-contract | 「空闲感知的陈旧自愈触发」既有 Scenario 回归（Requirement「空闲感知的陈旧自愈触发」，本次仅加强其「空闲」定义、触发协议语义不变）：交付/既有测试 TestIdleSelfhealTrigger 断言——① 连续空闲达标 `idle_confirm_seconds` 时写入 `.fenix/restart_request` 并记触发日志；② 出现活跃 run 立即清零计时且不写该文件；③ admin 处置池在途判非空闲；④ `restart_request` 已在册时不重复写入；⑤ 双源皆空（无 agent run、无在飞评审、admin 池空）判空闲；⑥ 未受 supervisor 托管 / 配置关闭时阻断自愈。②~⑤ 是本次加「评审车道」维度后 MUST 保持不回归的边界。出处：fenixd.py:1108（_maybe_stale_selfheal_tick）、fenixd.py:1174-1197（计时清零与 touch 落盘）、tests/test_stale_code_selfheal.py:148-257。 | pass | 0/8 | - |
| idle-anchor-facade-readonly-and-resilient | 只读门面契约（tasks 3.1：engine.py 的改动即为此提供只读门面，MUST NOT 改 `_active_runs`/`_active_reviews` 语义）：交付测试 TestReviewAnchorFacade 断言 `PMEngine.review_anchors()` 只把 `reviewer_run` 非空的 spec 圈为候选（候选收窄），且 STATE 不可读时返回空 dict + WARNING 而非抛出（不代判在飞）。出处：core/pm_engine/engine.py:3556（review_anchors）、fenixd.py:1027（_review_anchor_candidates 短 TTL 候选缓存）、tests/test_stale_selfheal_idle.py:247-264。 | pass | 0/3 | - |
| idle-criteria-source-reuse | 判据同源取证（design D3「MUST 复用既有判据，不得新造在飞判定」）：以 `inspect.getsource` 断言 ① `_is_idle` 调用 `_review_lane_busy()`；② `_review_lane_busy` 同时使用 `has_queued_review`（入队未落盘窗口）、`is_review_in_flight`（per-spec 登记）、`reviewer_in_flight`（进程表 / 流新鲜 / 陈旧锚点分层）——即与派发守卫同口径的双判据合取；③ 其函数体**不含** `_run_stream_alive(` 单独在飞依据（停滞 run 的转录本就不增长，以流新鲜度为唯一依据即缺陷原样复现）；④ 候选经 `_review_anchor_candidates` 收窄，后者调 `PMEngine.review_anchors()`，且该方法只枚举 `reviewer_run` 非空条目。出处：fenixd.py:987/1027/1053、core/pm_engine/engine.py:3556。 | pass | 0/9 | - |
| regression-state-and-selfheal-suites | 回归点（tasks 4.3/4.4：状态机与调度相关既有测试零回归）：一次运行状态机、状态布局契约、陈旧自愈、取消保持相关测试套件 + 本 SPEC 两个新增测试文件，断言整批零失败。`-q` 输出形态为汇总行「N passed」（不使用 -v，二者并列会互相覆盖——见项目约定）；以 `exit_code=0` 为第一层仲裁，辅以负向 `failed` 匹配防汇总行被误读。出处：tests/test_state_machine.py、tests/test_state_layout_contract.py、tests/test_stale_code_selfheal.py、tests/test_state_write_atomicity.py、tests/test_stale_selfheal_idle.py。 | pass | 0/3 | - |
| api-evolution-items-route-still-served | 回归点（交付物 core/dashboard/routes/evolution_routes.py 的 logger 注入改动不得影响该路由模块的服务能力）：GET /api/evolution/items 应返回 200 + `{items: [...]}`。该模块内 `_state_machine()` 构造点本次由 `StateMachine(..., None)` 改为注入 `project_state_logger(FRAMEWORK_ROOT)`（design D2 点名的三处之一），本场景在真实 dashboard 实例上确认路由模块可正常导入与响应。出处：core/dashboard/routes/evolution_routes.py:26-36（_state_machine）、:36-45（_api_evolution_items）、core/dashboard/routes/base.py:315（GET /api/evolution/items 路由登记）。 | pass | 0/3 | - |
| api-code-review-items-route-still-served | 回归点（交付物 core/dashboard/routes/code_review_routes.py 的 logger 注入改动不得影响该路由模块的服务能力）：GET /api/code-review/items?project=scheduling-showcase 应返回 200 + `{items: [...]}`。该模块内 `_code_review_state_machine()` 构造点本次由无 logger 改为注入 `project_state_logger(project_path)`（design D2 点名的三处之一）。夹具项目 scheduling-showcase 由 verify.yaml prepare 步幂等 provision 并登记注册表。出处：core/dashboard/routes/code_review_routes.py:232-247（_code_review_state_machine）、:31-45（_api_code_review_items）、core/dashboard/routes/base.py:322（路由登记）、bin/fixture_scheduling_showcase.py:76（_ensure_registered）。 | pass | 0/3 | - |
| idle-stale-anchor-does-not-occupy-forever | 反向约束（design D3「MUST NOT 引入永真条件」/ Requirement「空闲判定语义」Scenario 陈旧锚点不永久占据非空闲）：交付测试断言「`reviewer_run` 锚点残留但 run 进程已退出、流文件末行已终态」时经 `LivenessSupervisor.reviewer_in_flight` 判据 4 返回 `(False, "stale")`，该 spec 不计入非空闲、`_is_idle()` 可返回真——防止「锚点非空即非空闲」的自造永真条件使自愈永不触发。出处：core/agent_runner/liveness.py:454（reviewer_in_flight 分层判据）、fenixd.py:1076-1078（反向约束注释）、tests/test_stale_selfheal_idle.py:208-217。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

