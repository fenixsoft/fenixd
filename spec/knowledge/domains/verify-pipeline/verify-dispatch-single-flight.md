# verify 车道派发单飞
<!-- knowledge: capability=verify-dispatch-single-flight rev=2 sources=spec/archive/2026-10-09-evo-add-verify-dispatch-single-flight-7c1997,spec/archive/2026-10-11-evo-add-verify-dispatch-single-flight -->

验证车道在派发队列层按 spec 维护在飞集合，同 spec 至多一个在飞验证 run；配套 prepare 构建互斥与 worktree 竞争类失败的降级分流，杜绝双路并发验证引发的构建互踩、伪失败与无谓降级。

## 规则

- 同 spec 单飞：验证车道按 spec 单键维护在飞集合。同 spec 已有在飞验证 run 时，第二路经任一入队路径（spec_implemented 事件、repair 链尾段、admin 复位直通道）入队一律拒绝并留痕，不产生第二个并发验证 run；守卫覆盖全部入队路径，入口存在旁路则在入口补查。在飞验证 run 收工（成功或失败）后同 spec 再次入队正常派发，不阻塞合法重验。
- 登记与出队同锁段：在飞登记与出队判定在同一队列锁段内完成（出队分流锁内原子「查在飞→命中即拒绝留痕并丢弃条目→未命中即登记」），不得延后到线程启动后的「派发成功」点——出队到登记的窗口内同 spec 再入队会复现双派发竞态。摘除对齐派发收尾点：派发异常回滚与 worker 收尾 finally 均幂等释放。
- 拒绝优于排队：重复入队不引入延迟派发排队语义，处置为拒绝＋结构化留痕＋admin 通道显式放行。
- prepare 并发护栏：验证契约 prepare 步骤对共享主树构建目录的并发执行具备互斥或隔离。护栏落在 run_prepare_steps 函数内、按调用 cwd 判定主树路径生效——主树调用方为纯 cli 与 web/api 两个 serving 入口及契约校验入口（validate_contract），worktree 路径调用天然隔离、不涉及护栏。契约显式支持构建目录参数化时用 per-run 隔离构建目录；缺省对 prepare 加主机级 fcntl 互斥锁（带超时与 pid 记录，残留可诊断，护栏异常也须释放不得阻塞后续合法 prepare），不出现并发 clean 擦除产物导致的伪失败。
- 竞争类失败降级分流：新验证流程因 worktree 竞争类失败（异常链含 `gave up: parallel run or manual freeze` 特征，按子串匹配、允许包装、不得全等比较）先重试新流程一次，仍失败才降级旧版 verifier，降级计数与 degrade_context 留痕保留。重试前置校验为 worktree 锁已释放（lifecycle.has_active_lock/_lock_since）——派发在飞集合对同 spec 自指、自身条目必然在飞，无 peer 判别力，不得用作重试前置判据。非竞争类失败维持直接降级。
- 分层互补：单飞是进程内队列层守卫，与 worktree 锁层单飞（lock_key=spec:agent_type）分层协作——队列层挡入队、锁层挡创建；跨 daemon 重启的防护由持久层守卫承担。

## 关键行为

- 验证管线内部分环境类失败刻意静默让路不 raise，该类本就不进降级分支、无需分流。

## 溯源

- 2026-10-09 evo-add-verify-dispatch-single-flight-7c1997（spec/archive/2026-10-09-evo-add-verify-dispatch-single-flight-7c1997） — 新增本页：verify 车道派发层同 spec 单飞（拒绝＋留痕＋admin 显式放行，覆盖三条入队路径）、prepare 共享构建目录主机级互斥护栏、worktree 竞争类失败先重试新流程一次再降级 legacy
- 2026-10-11 evo-add-verify-dispatch-single-flight（spec/archive/2026-10-11-evo-add-verify-dispatch-single-flight） — 同 delta 重落地并修正两处判据：竞争类重试前置校验由「查在飞集合」改为「worktree 锁已释放」（在飞集合同 spec 自指无判别力）；prepare 护栏落点明确为 run_prepare_steps 内按 cwd 判定主树路径（含契约校验入口，护栏异常也释放）
